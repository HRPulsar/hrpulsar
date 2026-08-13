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


class _FakeRedis:
    """Dict-backed stand-in honouring ``SET NX`` — enough for the throttle.

    Real Redis semantics that matter here: ``SET NX`` returns ``None``
    when the key is taken, and ``TTL`` answers the remaining seconds.
    """

    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.calls: list[tuple[str, bool | None, int | None]] = []

    async def set(self, key, value, nx=None, ex=None):
        self.calls.append((key, nx, ex))
        if nx and key in self.store:
            return None
        self.store[key] = ex
        return True

    async def ttl(self, key):
        return self.store.get(key, -2)

    async def aclose(self):
        return None


@pytest.fixture(autouse=True)
def resend_throttle(monkeypatch):
    """Stub the HRP-545 resend cooldown — autouse so no test in this
    module reaches the real Redis. The outage test re-patches
    ``from_url`` inside its own body."""
    fake = _FakeRedis()
    monkeypatch.setattr(
        "app.modules.recruitment.manager_assessment_service.aioredis.from_url",
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
            service.INVITE_RESEND_COOLDOWN_SECONDS
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
        assert ex == service.INVITE_RESEND_COOLDOWN_SECONDS

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
            "app.modules.recruitment.manager_assessment_service.aioredis.from_url",
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
            "app.modules.recruitment.manager_assessment_service.aioredis.from_url",
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
