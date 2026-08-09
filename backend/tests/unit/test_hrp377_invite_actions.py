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
