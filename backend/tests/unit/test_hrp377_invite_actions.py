"""HRP-377: per-invitation actions behind the external-evaluator kebab.

Resend re-mails the *same* link (a fresh token would kill a tab the
evaluator may already have open); Revoke kills it immediately; the
submitted sheet stays readable so `View submission` has something to show.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from app.config import settings
from app.modules.recruitment import manager_assessment_public as public_service
from app.modules.recruitment import manager_assessment_service as service
from app.modules.recruitment.manager_assessment_schemas import (
    ManagerAssessmentInviteCreate,
    ManagerAssessmentInviteIn,
    RoundCreate,
)
from app.modules.recruitment.models import AssessmentInvite
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp186_manager_assessment import (
    _make_candidate_vacancy,
    _make_profile,
    _make_vacancy,
)


class _FakePipeline:
    """Queues commands like redis-py does — ``incrby``/``expire`` are
    synchronous queueing calls, only ``execute`` awaits."""

    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, str, int]] = []

    async def __aenter__(self) -> _FakePipeline:
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    def incrby(self, key, amount=1):
        self._ops.append(("incrby", (key, amount), {}))
        return self

    def decrby(self, key, amount=1):
        self._ops.append(("decrby", (key, amount), {}))
        return self

    def expire(self, key, seconds, **kwargs):
        self._ops.append(("expire", (key, seconds), kwargs))
        return self

    async def execute(self):
        out = [
            await getattr(self._redis, op)(*args, **kwargs)
            for op, args, kwargs in self._ops
        ]
        self._ops.clear()
        return out


class _FakeRedis:
    """Dict-backed stand-in honouring ``SET NX``, ``INCRBY`` and ``TTL``.

    Real Redis semantics that matter here: ``SET NX`` returns ``None``
    when the key is taken, ``TTL`` answers the remaining seconds (``-2``
    for a missing key), and a counter survives until its TTL runs out.
    ``ttl_override`` lets a test pin what ``TTL`` reports, which is how
    the "partway through the window" and "TTL already gone" branches of
    the ``Retry-After`` fallback get exercised.
    """

    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.ttls: dict[str, int | None] = {}
        self.calls: list[tuple[str, bool | None, int | None]] = []
        self.ttl_override: int | None = None

    async def set(self, key, value, nx=None, ex=None):
        self.calls.append((key, nx, ex))
        if nx and key in self.store:
            return None
        self.store[key] = value
        self.ttls[key] = ex
        return True

    async def incrby(self, key, amount=1):
        self.store[key] = int(self.store.get(key, 0)) + amount
        return self.store[key]

    async def decrby(self, key, amount=1):
        self.store[key] = int(self.store.get(key, 0)) - amount
        return self.store[key]

    async def delete(self, key):
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return 1

    async def expire(self, key, seconds, nx=False):
        # Real EXPIRE NX only sets a TTL on a key that has none.
        if nx and self.ttls.get(key):
            return False
        self.ttls[key] = seconds
        return True

    async def ttl(self, key):
        if self.ttl_override is not None:
            return self.ttl_override
        if key not in self.store:
            return -2
        return self.ttls.get(key) or -1

    def pipeline(self, transaction=True):
        return _FakePipeline(self)

    async def aclose(self):
        return None


@pytest.fixture(autouse=True)
def resend_throttle(monkeypatch):
    """Stub the invitation-mail throttles — autouse so no test in this
    module reaches the real Redis. The outage tests re-patch
    ``from_url`` inside their own body."""
    fake = _FakeRedis()
    monkeypatch.setattr(
        "app.core.redis.aioredis.from_url",
        lambda *_a, **_kw: fake,
    )
    return fake


async def _round_with_invite(db: AsyncSession, tenant, user):
    vacancy = await _make_vacancy(db, tenant)
    await _make_profile(db, tenant, vacancy)
    cv = await _make_candidate_vacancy(db, tenant, vacancy)
    rd = await service.create_round(
        db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
    )
    rows = await service.create_invites(
        db,
        tenant.id,
        user.id,
        cv.id,
        ManagerAssessmentInviteCreate(
            invitees=[
                ManagerAssessmentInviteIn(
                    email=f"{uuid.uuid4().hex[:8]}@example.com", name="Ext Eval"
                )
            ],
            round_id=uuid.UUID(str(rd["id"])),
        ),
    )
    inv = await db.get(AssessmentInvite, rows[0]["id"])
    return cv, uuid.UUID(str(rd["id"])), inv


class TestResendInvite:
    async def test_resend_reuses_the_same_token(self, db: AsyncSession, tenant, user):
        _, _, inv = await _round_with_invite(db, tenant, user)
        original_token = inv.token

        with patch("app.core.email.enqueue_email") as enqueue:
            out = await service.resend_invite(db, tenant.id, user.id, inv.id)

        await db.refresh(inv)
        # A new token would break a tab the evaluator already has open.
        assert inv.token == original_token
        assert out["delivery_retry_count"] == 1
        assert inv.delivery_status == "sent"
        assert enqueue.call_args.args[0] == inv.email

    async def test_bounced_invite_can_be_retried(self, db: AsyncSession, tenant, user):
        _, _, inv = await _round_with_invite(db, tenant, user)
        inv.status = "opened"
        inv.delivery_status = "delivery_failed"
        inv.delivery_error = "bounced"
        await db.commit()

        with patch("app.core.email.enqueue_email"):
            out = await service.resend_invite(db, tenant.id, user.id, inv.id)

        assert out["delivery_status"] == "sent"
        assert out["delivery_error"] is None

    async def test_an_opened_invite_is_not_re_nagged(
        self, db: AsyncSession, tenant, user
    ):
        _, _, inv = await _round_with_invite(db, tenant, user)
        inv.status = "in_progress"
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.resend_invite(db, tenant.id, user.id, inv.id)
        assert exc.value.status_code == 409

    async def test_terminal_invites_cannot_be_resent(
        self, db: AsyncSession, tenant, user
    ):
        for terminal in ("submitted", "declined"):
            _, _, inv = await _round_with_invite(db, tenant, user)
            inv.status = terminal
            await db.commit()
            with pytest.raises(HTTPException) as exc:
                await service.resend_invite(db, tenant.id, user.id, inv.id)
            assert exc.value.status_code == 409

    async def test_revoked_invite_cannot_be_resent(
        self, db: AsyncSession, tenant, user
    ):
        _, _, inv = await _round_with_invite(db, tenant, user)
        await service.revoke_invite(db, tenant.id, user.id, inv.id)
        with pytest.raises(HTTPException) as exc:
            await service.resend_invite(db, tenant.id, user.id, inv.id)
        assert exc.value.status_code == 409

    async def test_expired_invite_cannot_be_resent(
        self, db: AsyncSession, tenant, user
    ):
        _, _, inv = await _round_with_invite(db, tenant, user)
        inv.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await db.commit()
        with pytest.raises(HTTPException) as exc:
            await service.resend_invite(db, tenant.id, user.id, inv.id)
        assert exc.value.status_code == 409

    async def test_a_bounce_does_not_revive_a_dead_token(
        self, db: AsyncSession, tenant, user
    ):
        """The delivery escape hatch must not reach past the status gate.

        Re-mailing an expired (or declined) invitation would send a link
        whose first click answers 410 — under an email promising it
        "expires in 1 day", because the remaining-days clamp floors a
        negative delta at one.
        """
        for terminal in ("expired", "declined"):
            _, _, inv = await _round_with_invite(db, tenant, user)
            if terminal == "expired":
                inv.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
            else:
                inv.status = "declined"
            inv.delivery_status = "delivery_failed"
            inv.delivery_error = "bounced"
            await db.commit()

            with (
                patch("app.core.email.enqueue_email") as enqueue,
                pytest.raises(HTTPException) as exc,
            ):
                await service.resend_invite(db, tenant.id, user.id, inv.id)
            assert exc.value.status_code == 409
            enqueue.assert_not_called()

    async def test_send_failure_is_recorded_not_raised(
        self, db: AsyncSession, tenant, user
    ):
        _, _, inv = await _round_with_invite(db, tenant, user)
        with patch(
            "app.core.email.enqueue_email", side_effect=RuntimeError("smtp down")
        ):
            out = await service.resend_invite(db, tenant.id, user.id, inv.id)
        assert out["delivery_status"] == "delivery_failed"
        assert out["delivery_retry_count"] == 1

    async def test_cross_tenant_invite_is_not_found(
        self, db: AsyncSession, tenant, user
    ):
        _, _, inv = await _round_with_invite(db, tenant, user)
        with pytest.raises(HTTPException) as exc:
            await service.resend_invite(db, uuid.uuid4(), user.id, inv.id)
        assert exc.value.status_code == 404


class TestResendCooldown:
    """HRP-545: resend is free and unattended — throttle it per invite."""

    async def test_a_second_resend_inside_the_window_is_refused(
        self, db: AsyncSession, tenant, user, resend_throttle
    ):
        _, _, inv = await _round_with_invite(db, tenant, user)

        with patch("app.core.email.enqueue_email"):
            await service.resend_invite(db, tenant.id, user.id, inv.id)

        with (
            patch("app.core.email.enqueue_email") as enqueue,
            pytest.raises(HTTPException) as exc,
        ):
            await service.resend_invite(db, tenant.id, user.id, inv.id)

        assert exc.value.status_code == 429
        assert exc.value.headers["Retry-After"] == str(
            settings.invite_resend_cooldown_seconds
        )
        # The whole point: no second copy reaches the evaluator's inbox.
        enqueue.assert_not_called()

    async def test_the_slot_is_claimed_atomically_with_a_ttl(
        self, db: AsyncSession, tenant, user, resend_throttle
    ):
        _, _, inv = await _round_with_invite(db, tenant, user)

        with patch("app.core.email.enqueue_email"):
            await service.resend_invite(db, tenant.id, user.id, inv.id)

        key, nx, ex = resend_throttle.calls[-1]
        # SET NX EX, not read-then-write: two concurrent resends must not
        # both pass the check.
        assert key == f"recruitment:invite-resend:{inv.id}"
        assert nx is True
        assert ex == settings.invite_resend_cooldown_seconds

    async def test_the_cooldown_is_per_invite(self, db: AsyncSession, tenant, user):
        """One evaluator's cooldown must not block a different invite."""
        _, _, first = await _round_with_invite(db, tenant, user)
        _, _, second = await _round_with_invite(db, tenant, user)

        with patch("app.core.email.enqueue_email") as enqueue:
            await service.resend_invite(db, tenant.id, user.id, first.id)
            out = await service.resend_invite(db, tenant.id, user.id, second.id)

        assert out["delivery_status"] == "sent"
        assert enqueue.call_count == 2

    async def test_a_failed_delivery_still_consumes_the_slot(
        self, db: AsyncSession, tenant, user
    ):
        """The claim happens before the send, so breaking delivery is not
        a way to buy extra sends."""
        _, _, inv = await _round_with_invite(db, tenant, user)

        with patch(
            "app.core.email.enqueue_email", side_effect=RuntimeError("smtp down")
        ):
            out = await service.resend_invite(db, tenant.id, user.id, inv.id)
        assert out["delivery_status"] == "delivery_failed"

        with pytest.raises(HTTPException) as exc:
            await service.resend_invite(db, tenant.id, user.id, inv.id)
        assert exc.value.status_code == 429

    async def test_a_terminal_invite_does_not_burn_the_cooldown(
        self, db: AsyncSession, tenant, user, resend_throttle
    ):
        """The 409 gate runs first: a dead invite keeps answering the
        informative conflict rather than a misleading 'wait a few minutes'."""
        _, _, inv = await _round_with_invite(db, tenant, user)
        inv.status = "declined"
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.resend_invite(db, tenant.id, user.id, inv.id)

        assert exc.value.status_code == 409
        assert resend_throttle.calls == []

    async def test_redis_outage_fails_closed_on_saas(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        """On SaaS a flaking throttle must not silently reopen the flood
        gate — Redis is part of the platform there."""
        _, _, inv = await _round_with_invite(db, tenant, user)
        monkeypatch.setattr(
            "app.modules.recruitment.manager_assessment_service.settings."
            "deployment_mode",
            "saas",
        )

        def _boom(*_a, **_kw):
            raise ConnectionError("redis down")

        monkeypatch.setattr(
            "app.core.redis.aioredis.from_url",
            _boom,
        )

        with (
            patch("app.core.email.enqueue_email") as enqueue,
            pytest.raises(HTTPException) as exc,
        ):
            await service.resend_invite(db, tenant.id, user.id, inv.id)

        assert exc.value.status_code == 503
        enqueue.assert_not_called()

    async def test_redis_outage_fails_open_on_self_hosted(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        """Redis is optional in community builds — ``enqueue_email`` falls
        back to sending inline when the broker is down. Refusing there
        would break resend on installations where it works today, to
        protect an inbox the operator owns anyway."""
        _, _, inv = await _round_with_invite(db, tenant, user)
        monkeypatch.setattr(
            "app.modules.recruitment.manager_assessment_service.settings."
            "deployment_mode",
            "onprem",
        )

        def _boom(*_a, **_kw):
            raise ConnectionError("no redis on this box")

        monkeypatch.setattr(
            "app.core.redis.aioredis.from_url",
            _boom,
        )

        with patch("app.core.email.enqueue_email") as enqueue:
            out = await service.resend_invite(db, tenant.id, user.id, inv.id)

        assert out["delivery_status"] == "sent"
        enqueue.assert_called_once()


class TestRevokeFromTheKebab:
    async def test_revoked_link_stops_working_immediately(
        self, db: AsyncSession, tenant, user
    ):
        _, _, inv = await _round_with_invite(db, tenant, user)
        token = inv.token

        out = await service.revoke_invite(db, tenant.id, user.id, inv.id)
        assert out["status"] == "revoked"

        with pytest.raises(HTTPException) as exc:
            await public_service.resolve_invite_by_token(db, token)
        assert exc.value.status_code == 410
        assert exc.value.detail == "This invitation was revoked"


class TestViewSubmission:
    async def test_submitted_external_sheet_is_readable(
        self, db: AsyncSession, tenant, user
    ):
        _, rd_id, inv = await _round_with_invite(db, tenant, user)
        # Accept consent, then submit through the public flow.
        inv.consent_accepted_at = datetime.now(timezone.utc)
        await db.commit()
        await public_service.public_submit(
            db, inv.token, final_notes="Solid systems thinker"
        )

        rows = await service.list_assessments_for_round(
            db, tenant.id, rd_id, viewer_user_id=user.id
        )
        sheet = next(a for a in rows if a["evaluator_invite_id"] == inv.id)
        assert sheet["status"] == "submitted"
        assert sheet["final_notes"] == "Solid systems thinker"


class TestRetryAfterHeader:
    """HRP-576 (a)/(f): the throttle always says when to come back."""

    async def test_retry_after_reports_the_remaining_window(
        self, db: AsyncSession, tenant, user, resend_throttle
    ):
        _, _, inv = await _round_with_invite(db, tenant, user)
        with patch("app.core.email.enqueue_email"):
            await service.resend_invite(db, tenant.id, user.id, inv.id)

        # Partway through the window: the header must carry what Redis
        # reports, not the full cooldown.
        resend_throttle.ttl_override = 137
        with pytest.raises(HTTPException) as exc:
            await service.resend_invite(db, tenant.id, user.id, inv.id)

        assert exc.value.status_code == 429
        assert exc.value.headers["Retry-After"] == "137"

    @pytest.mark.parametrize("reported_ttl", [-1, -2, 0])
    async def test_retry_after_falls_back_when_ttl_is_unavailable(
        self, db: AsyncSession, tenant, user, resend_throttle, reported_ttl
    ):
        """A key without a TTL (or already gone between SET and TTL) must
        still produce a usable header rather than 'Retry-After: -1'."""
        _, _, inv = await _round_with_invite(db, tenant, user)
        with patch("app.core.email.enqueue_email"):
            await service.resend_invite(db, tenant.id, user.id, inv.id)

        resend_throttle.ttl_override = reported_ttl
        with pytest.raises(HTTPException) as exc:
            await service.resend_invite(db, tenant.id, user.id, inv.id)

        assert exc.value.headers["Retry-After"] == str(
            settings.invite_resend_cooldown_seconds
        )

    async def test_saas_outage_503_carries_retry_after_through_the_api(
        self, db: AsyncSession, tenant, user, auth_client, monkeypatch
    ):
        """HRP-576 (f): the negative path end-to-end — a SaaS deployment
        with an unreachable throttle answers 503 *with* the hint, not a
        bare refusal the client has to guess about."""
        _, _, inv = await _round_with_invite(db, tenant, user)
        monkeypatch.setattr(
            "app.modules.recruitment.manager_assessment_service.settings."
            "deployment_mode",
            "saas",
        )

        def _boom(*_a, **_kw):
            raise ConnectionError("redis down")

        monkeypatch.setattr("app.core.redis.aioredis.from_url", _boom)

        with patch("app.core.email.enqueue_email") as enqueue:
            resp = await auth_client.post(
                f"/api/v1/manager-assessment-invites/{inv.id}/resend"
            )

        assert resp.status_code == 503, resp.text
        assert resp.headers["Retry-After"] == str(
            service.THROTTLE_OUTAGE_RETRY_AFTER_SECONDS
        )
        enqueue.assert_not_called()


class TestRecipientMailCap:
    """HRP-576 (e): the per-invite cooldown only slowed resends — new
    invitations to the same mailbox were unlimited."""

    @pytest.fixture(autouse=True)
    def _cap(self, monkeypatch):
        monkeypatch.setattr(settings, "invite_mail_cap_per_recipient_per_hour", 2)

    async def _invite(self, db, tenant, user, cv, round_id, email, count=1):
        return await service.create_invites(
            db,
            tenant.id,
            user.id,
            cv.id,
            ManagerAssessmentInviteCreate(
                invitees=[
                    ManagerAssessmentInviteIn(email=email, name="Ext Eval")
                    for _ in range(count)
                ],
                round_id=round_id,
            ),
        )

    async def test_new_invites_to_one_address_stop_at_the_cap(
        self, db: AsyncSession, tenant, user
    ):
        cv, rd_id, _ = await _round_with_invite(db, tenant, user)
        email = f"{uuid.uuid4().hex[:8]}@example.com"

        with patch("app.core.email.enqueue_email"):
            await self._invite(db, tenant, user, cv, rd_id, email)
            await self._invite(db, tenant, user, cv, rd_id, email)

        with (
            patch("app.core.email.enqueue_email") as enqueue,
            pytest.raises(HTTPException) as exc,
        ):
            await self._invite(db, tenant, user, cv, rd_id, email)

        assert exc.value.status_code == 429
        assert exc.value.headers["Retry-After"] == str(
            service.INVITE_MAIL_WINDOW_SECONDS
        )
        enqueue.assert_not_called()

    async def test_a_refused_attempt_does_not_restart_the_window(
        self, db: AsyncSession, tenant, user, resend_throttle
    ):
        """The window is anchored at the first send. Re-arming the TTL on
        every refused retry would keep the address over cap forever, and
        ``Retry-After`` would never count down (review fix)."""
        cv, rd_id, _ = await _round_with_invite(db, tenant, user)
        email = f"{uuid.uuid4().hex[:8]}@example.com"
        with patch("app.core.email.enqueue_email"):
            await self._invite(db, tenant, user, cv, rd_id, email, count=2)
        key = service._invite_mail_key(email)
        resend_throttle.ttls[key] = 137  # partway through the hour

        with (
            patch("app.core.email.enqueue_email"),
            pytest.raises(HTTPException) as exc,
        ):
            await self._invite(db, tenant, user, cv, rd_id, email)

        assert exc.value.headers["Retry-After"] == "137"
        assert resend_throttle.ttls[key] == 137  # not re-armed
        assert resend_throttle.store[key] == 2  # the refusal rolled back

    async def test_a_refused_batch_leaves_no_partial_charge(
        self, db: AsyncSession, tenant, user
    ):
        """A batch that trips the cap on one address must not leave the
        other addresses charged for mail that was never sent."""
        cv, rd_id, _ = await _round_with_invite(db, tenant, user)
        hot = f"{uuid.uuid4().hex[:8]}@example.com"
        clean = f"{uuid.uuid4().hex[:8]}@example.com"
        with patch("app.core.email.enqueue_email"):
            await self._invite(db, tenant, user, cv, rd_id, hot, count=2)

        with (
            patch("app.core.email.enqueue_email"),
            pytest.raises(HTTPException),
        ):
            await service.create_invites(
                db,
                tenant.id,
                user.id,
                cv.id,
                ManagerAssessmentInviteCreate(
                    invitees=[
                        ManagerAssessmentInviteIn(email=clean, name="Ext Eval"),
                        ManagerAssessmentInviteIn(email=hot, name="Ext Eval"),
                    ],
                    round_id=rd_id,
                ),
            )

        # The clean address keeps its full budget: both sends still fit.
        with patch("app.core.email.enqueue_email") as enqueue:
            await self._invite(db, tenant, user, cv, rd_id, clean, count=2)
        enqueue.assert_called()

    async def test_a_failed_enqueue_refunds_the_recipient_budget(
        self, db: AsyncSession, tenant, user
    ):
        """The cap counts mail that reached the recipient — a broker
        refusal must not burn budget for an email that never left."""
        cv, rd_id, _ = await _round_with_invite(db, tenant, user)
        email = f"{uuid.uuid4().hex[:8]}@example.com"
        with patch(
            "app.core.email.enqueue_email", side_effect=RuntimeError("broker down")
        ):
            rows = await self._invite(db, tenant, user, cv, rd_id, email)
        assert rows[0]["delivery_status"] == "delivery_failed"

        # Both real sends still fit under the cap of 2.
        with patch("app.core.email.enqueue_email") as enqueue:
            await self._invite(db, tenant, user, cv, rd_id, email, count=2)
        assert enqueue.call_count == 2

    async def test_redis_outage_fails_closed_for_new_invites_on_saas(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        """The 503 branch of the recipient cap itself — distinct from the
        resend-slot outage tests, which raise before this code runs."""
        cv, rd_id, _ = await _round_with_invite(db, tenant, user)
        monkeypatch.setattr(
            "app.modules.recruitment.manager_assessment_service.settings."
            "deployment_mode",
            "saas",
        )
        monkeypatch.setattr(
            "app.core.redis.aioredis.from_url",
            lambda *_a, **_kw: (_ for _ in ()).throw(ConnectionError("redis down")),
        )

        with (
            patch("app.core.email.enqueue_email") as enqueue,
            pytest.raises(HTTPException) as exc,
        ):
            await self._invite(
                db, tenant, user, cv, rd_id, f"{uuid.uuid4().hex[:8]}@example.com"
            )

        assert exc.value.status_code == 503
        assert exc.value.headers["Retry-After"] == str(
            service.THROTTLE_OUTAGE_RETRY_AFTER_SECONDS
        )
        enqueue.assert_not_called()

    async def test_one_batch_counts_every_copy_of_the_same_address(
        self, db: AsyncSession, tenant, user
    ):
        """Repeating the address inside a single batch is the same flood —
        and the whole batch is refused before any row is written."""
        cv, rd_id, _ = await _round_with_invite(db, tenant, user)
        email = f"{uuid.uuid4().hex[:8]}@example.com"

        with (
            patch("app.core.email.enqueue_email") as enqueue,
            pytest.raises(HTTPException) as exc,
        ):
            await self._invite(db, tenant, user, cv, rd_id, email, count=3)

        assert exc.value.status_code == 429
        enqueue.assert_not_called()
        assert not [
            inv
            for inv in (await service.list_manager_invites(db, tenant.id, cv.id))
            if inv["email"] == email
        ]

    async def test_the_cap_is_per_address(self, db: AsyncSession, tenant, user):
        cv, rd_id, _ = await _round_with_invite(db, tenant, user)
        with patch("app.core.email.enqueue_email") as enqueue:
            for _ in range(3):
                await self._invite(
                    db, tenant, user, cv, rd_id, f"{uuid.uuid4().hex[:8]}@example.com"
                )
        assert enqueue.call_count == 3

    async def test_resends_count_against_the_recipient_cap(
        self, db: AsyncSession, tenant, user
    ):
        """Otherwise a fresh invitation per resend walks around the cap."""
        cv, rd_id, _ = await _round_with_invite(db, tenant, user)
        email = f"{uuid.uuid4().hex[:8]}@example.com"
        with patch("app.core.email.enqueue_email"):
            rows = await self._invite(db, tenant, user, cv, rd_id, email)
            second = await self._invite(db, tenant, user, cv, rd_id, email)

        with (
            patch("app.core.email.enqueue_email") as enqueue,
            pytest.raises(HTTPException) as exc,
        ):
            await service.resend_invite(db, tenant.id, user.id, rows[0]["id"])

        assert exc.value.status_code == 429
        assert second  # the second invite did go out, the third send did not
        enqueue.assert_not_called()
