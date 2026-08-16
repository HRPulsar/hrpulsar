"""HRP-383: a withdrawn external evaluation stops counting.

After HRP-369 the sheets of revoked / declined invites no longer hold the
single pre_interview slot — but their stored scores kept feeding
``round_aggregate`` and ``manager_score``. An external evaluator who
scored before their invite was pulled, followed by an internal user
taking the freed slot, left a "single evaluator" round averaging two.

The rule these tests pin: the invite states that free the slot are
exactly the invite states that drop out of the aggregate.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.modules.recruitment import manager_assessment_public as public_service
from app.modules.recruitment import manager_assessment_service as service
from app.modules.recruitment.manager_assessment_schemas import (
    CompetenceScoreIn,
    ManagerAssessmentInviteCreate,
    ManagerAssessmentInviteIn,
    RoundCreate,
)
from app.modules.recruitment.models import AssessmentInvite, CandidateVacancy
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp186_manager_assessment import (
    _make_candidate_vacancy,
    _make_profile,
    _make_vacancy,
)

COMPETENCE_ID = uuid.uuid4()


async def _scored_external_invite(
    db: AsyncSession, tenant, user, *, round_type: str = "pre_interview", score: int = 4
):
    """A round whose only evaluator is an external one who submitted."""
    vacancy = await _make_vacancy(db, tenant)
    await _make_profile(db, tenant, vacancy)
    cv = await _make_candidate_vacancy(db, tenant, vacancy)
    rd = await service.create_round(
        db, tenant.id, user.id, cv.id, RoundCreate(type=round_type)
    )
    rd_id = uuid.UUID(str(rd["id"]))
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
            round_id=rd_id,
        ),
    )
    inv = await db.get(AssessmentInvite, rows[0]["id"])
    sheet = await service.get_or_create_assessment(
        db, tenant.id, rd_id, evaluator_invite_id=inv.id
    )
    await service.set_competence_score(
        db,
        tenant.id,
        None,
        sheet.id,
        COMPETENCE_ID,
        CompetenceScoreIn(score_value=score),
    )
    # Submit through the public flow so both the sheet and the invite land
    # in the same state a real evaluator leaves them in.
    await public_service.public_submit(db, inv.token)
    return cv, rd_id, inv, sheet


class TestRevokedExternalScores:
    async def test_a_submitted_external_score_counts_until_revoked(
        self, db: AsyncSession, tenant, user
    ):
        cv, rd_id, inv, _ = await _scored_external_invite(db, tenant, user)

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["average"] == 4.0

        await service.revoke_invite(db, tenant.id, user.id, inv.id)

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["average"] is None
        assert agg["competences"] == []

    async def test_a_revoked_submission_stays_readable(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-577: dropping out of the aggregates is not deletion — the
        recruiter still opens the sheet from the invite's kebab, and the
        UI keys that on ``submitted_at`` surviving the revoke."""
        _, rd_id, inv, sheet = await _scored_external_invite(db, tenant, user)

        revoked = await service.revoke_invite(db, tenant.id, user.id, inv.id)
        assert revoked["status"] == "revoked"
        assert revoked["submitted_at"] is not None
        assert revoked["revoked_at"] is not None

        rows = await service.list_assessments_for_round(
            db, tenant.id, rd_id, viewer_user_id=user.id
        )
        readable = next(a for a in rows if a["evaluator_invite_id"] == inv.id)
        assert readable["id"] == sheet.id
        assert readable["status"] == "submitted"

    async def test_revoking_rebuilds_the_denormalized_manager_score(
        self, db: AsyncSession, tenant, user
    ):
        """The vacancy's Candidates block reads a stored number, so the
        aggregate fix alone would leave it quoting a withdrawn evaluation."""
        cv, _, inv, _ = await _scored_external_invite(db, tenant, user)

        row = await db.get(CandidateVacancy, cv.id)
        await db.refresh(row)
        assert row.manager_score == 4.0

        await service.revoke_invite(db, tenant.id, user.id, inv.id)

        await db.refresh(row)
        assert row.manager_score is None
        assert row.manager_score_source_round_id is None

    async def test_the_pre_interview_round_reports_one_evaluator(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        """The ticket's scenario end to end.

        External scores 4 and submits, the recruiter pulls the invite, an
        internal user takes the freed slot and scores 2. The round holds a
        single evaluator, so the average must be that user's 2 — not 3.
        """
        _, rd_id, inv, _ = await _scored_external_invite(db, tenant, user)
        await service.revoke_invite(db, tenant.id, user.id, inv.id)

        # HRP-369: the slot is free again, so this must not 409.
        own = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            own.id,
            COMPETENCE_ID,
            CompetenceScoreIn(score_value=2),
        )

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["average"] == 2.0
        scorers = agg["competences"][0]["scorers"]
        assert [s["evaluator_type"] for s in scorers] == ["internal"]
        assert [s["score"] for s in scorers] == [2]

    async def test_a_declined_invite_also_drops_out(
        self, db: AsyncSession, tenant, user
    ):
        """Defence in depth: the aggregate must not depend on a gate above
        it holding.

        The state built here is deliberately **synthetic** —
        ``public_decline`` answers 409 on a submitted invite, so
        declined-over-submitted is not reachable through the API today.
        It is pinned anyway because the exclusion rule should hold on the
        data itself, not on that gate staying in place.
        """
        _, rd_id, inv, _ = await _scored_external_invite(
            db, tenant, user, round_type="interview"
        )
        inv.status = "declined"
        await db.commit()

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["average"] is None

    async def test_an_untouched_submission_keeps_counting(
        self, db: AsyncSession, tenant, user
    ):
        """Only revoked/declined drop out — a completed external evaluation
        is the normal case and must survive."""
        _, rd_id, inv, _ = await _scored_external_invite(
            db, tenant, user, round_type="interview"
        )
        assert inv.status == "submitted"

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["average"] == 4.0

    async def test_an_expired_invite_keeps_counting(
        self, db: AsyncSession, tenant, user
    ):
        """``expired`` is excluded from the uncounted set on purpose: the
        deadline passing does not withdraw an evaluation that was already
        submitted. Pinned because only a comment said so."""
        _, rd_id, inv, _ = await _scored_external_invite(
            db, tenant, user, round_type="interview"
        )
        inv.status = "expired"
        inv.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await db.commit()

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["average"] == 4.0

    async def test_internal_sheets_are_untouched_by_the_filter(
        self, db: AsyncSession, tenant, user
    ):
        """An internal sheet carries no invite, so the NOT EXISTS must not
        catch it — including while it is still a draft."""
        vacancy = await _make_vacancy(db, tenant)
        await _make_profile(db, tenant, vacancy)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="pre_interview")
        )
        rd_id = uuid.UUID(str(rd["id"]))
        own = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            own.id,
            COMPETENCE_ID,
            CompetenceScoreIn(score_value=3),
        )

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["average"] == 3.0


class TestEvaluatorFacingSlotConflict:
    """HRP-383: the public consent page must not quote internal jargon."""

    async def _pre_interview_with_invite(self, db: AsyncSession, tenant, user):
        vacancy = await _make_vacancy(db, tenant)
        await _make_profile(db, tenant, vacancy)
        cv = await _make_candidate_vacancy(db, tenant, vacancy)
        rd = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="pre_interview")
        )
        rd_id = uuid.UUID(str(rd["id"]))
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
                round_id=rd_id,
            ),
        )
        inv = await db.get(AssessmentInvite, rows[0]["id"])
        return rd_id, inv

    async def test_an_invited_evaluator_gets_evaluator_facing_copy(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        """Real race: the invite is out, an internal evaluator claims the
        slot before the external one opens their link."""
        rd_id, inv = await self._pre_interview_with_invite(db, tenant, user)
        # No sheet exists yet, so the internal claim goes through.
        await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )

        with pytest.raises(HTTPException) as exc:
            await service.get_or_create_assessment(
                db, tenant.id, rd_id, evaluator_invite_id=inv.id
            )

        assert exc.value.status_code == 409
        assert exc.value.code == "pre_interview_slot_taken_external"

    async def test_the_internal_message_is_unchanged(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        rd_id, _ = await self._pre_interview_with_invite(db, tenant, user)
        await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )

        with pytest.raises(HTTPException) as exc:
            await service.get_or_create_assessment(
                db, tenant.id, rd_id, evaluator_user_id=uuid.uuid4()
            )

        assert exc.value.status_code == 409
        assert exc.value.code == "pre_interview_single_evaluator"
