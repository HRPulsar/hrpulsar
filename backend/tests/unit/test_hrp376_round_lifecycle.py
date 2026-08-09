"""HRP-376: completing, reopening, archiving and restoring a round.

Task 1 — `Mark as complete` has to actually close the round: the button
stays gone, the own sheet turns read-only and every live external link is
revoked so its holder sees "This invitation was revoked".

Task 2 — the tab kebab adds Archive/Restore; an archived round keeps its
scores but drops out of the candidate's aggregate.
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp186_manager_assessment import (
    _make_candidate_vacancy,
    _make_profile,
    _make_vacancy,
)


async def _round(db: AsyncSession, tenant, user, kind: str = "interview"):
    vacancy = await _make_vacancy(db, tenant)
    await _make_profile(db, tenant, vacancy)
    cv = await _make_candidate_vacancy(db, tenant, vacancy)
    rd = await service.create_round(
        db, tenant.id, user.id, cv.id, RoundCreate(type=kind)
    )
    return cv, uuid.UUID(str(rd["id"]))


async def _invite(db: AsyncSession, tenant, user, cv, round_id, *, status="pending"):
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
            round_id=round_id,
        ),
    )
    inv = await db.get(AssessmentInvite, rows[0]["id"])
    if status != "pending":
        inv.status = status
        await db.commit()
    return inv


class TestCompleteRound:
    async def test_completing_twice_is_refused(self, db: AsyncSession, tenant, user):
        _, rd_id = await _round(db, tenant, user)
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")
        with pytest.raises(HTTPException) as exc:
            await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")
        assert exc.value.status_code == 409

    async def test_own_sheet_is_submitted_and_read_only(
        self, db: AsyncSession, tenant, user
    ):
        _, rd_id = await _round(db, tenant, user)
        own = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")

        await db.refresh(own)
        assert own.status == "submitted"
        assert own.submitted_at is not None
        with pytest.raises(HTTPException) as exc:
            await service.set_competence_score(
                db,
                tenant.id,
                user.id,
                own.id,
                uuid.uuid4(),
                CompetenceScoreIn(score_value=3),
            )
        assert exc.value.status_code == 409

    async def test_live_invites_are_revoked(self, db: AsyncSession, tenant, user):
        cv, rd_id = await _round(db, tenant, user)
        inv = await _invite(db, tenant, user, cv, rd_id)

        await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")

        await db.refresh(inv)
        assert inv.status == "revoked"
        assert inv.revoked_at is not None
        # The evaluator following the link gets the documented message.
        with pytest.raises(HTTPException) as exc:
            await public_service.resolve_invite_by_token(db, inv.token)
        assert exc.value.status_code == 410
        assert exc.value.detail == "This invitation was revoked"

    async def test_submitted_invites_are_left_alone(
        self, db: AsyncSession, tenant, user
    ):
        cv, rd_id = await _round(db, tenant, user)
        inv = await _invite(db, tenant, user, cv, rd_id, status="submitted")

        await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")

        await db.refresh(inv)
        # A submitted evaluation still feeds the aggregate — rewriting it
        # to revoked would silently drop it.
        assert inv.status == "submitted"
        assert inv.revoked_at is None

    async def test_expired_invites_keep_their_status(
        self, db: AsyncSession, tenant, user
    ):
        cv, rd_id = await _round(db, tenant, user)
        inv = await _invite(db, tenant, user, cv, rd_id)
        inv.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await db.commit()

        await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")

        await db.refresh(inv)
        assert inv.revoked_at is None

    async def test_no_new_evaluators_or_invites_on_a_complete_round(
        self, db: AsyncSession, tenant, user
    ):
        cv, rd_id = await _round(db, tenant, user)
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")

        with pytest.raises(HTTPException) as exc:
            await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)
        assert exc.value.status_code == 409
        with pytest.raises(HTTPException) as exc2:
            await _invite(db, tenant, user, cv, rd_id)
        assert exc2.value.status_code == 409


class TestReopenRound:
    async def test_reopen_hands_scoring_back(self, db: AsyncSession, tenant, user):
        _, rd_id = await _round(db, tenant, user)
        own = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")
        rd = await service.apply_round_action(db, tenant.id, user.id, rd_id, "reopen")

        assert rd["status"] == "in_progress"
        assert rd["completed_at"] is None
        # Scoring works again.
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            own.id,
            uuid.uuid4(),
            CompetenceScoreIn(score_value=3),
        )
        # …and so does adding evaluators / external links.
        await service.add_evaluator(db, tenant.id, user.id, rd_id, user.id)

    async def test_revoked_invites_are_not_resurrected(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-376 §7c decision: a dead token stays dead.

        The holder was told the link no longer works; silently re-arming it
        would re-open access we have no record of. Re-inviting is one click
        and leaves an audit trail.
        """
        cv, rd_id = await _round(db, tenant, user)
        inv = await _invite(db, tenant, user, cv, rd_id)
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "reopen")

        await db.refresh(inv)
        assert inv.status == "revoked"
        with pytest.raises(HTTPException) as exc:
            await public_service.resolve_invite_by_token(db, inv.token)
        assert exc.value.status_code == 410


class TestArchiveAndRestore:
    async def _scored_round(self, db, tenant, user, *, score: int):
        cv, rd_id = await _round(db, tenant, user)
        a = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a.id,
            uuid.uuid4(),
            CompetenceScoreIn(score_value=score),
        )
        return cv, rd_id

    async def test_archived_round_drops_out_of_the_average(
        self, db: AsyncSession, tenant, user
    ):
        cv, first = await self._scored_round(db, tenant, user, score=4)
        # A second round on the same candidate-vacancy, scored lower.
        second_row = await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        second = uuid.UUID(str(second_row["id"]))
        a2 = await service.get_or_create_assessment(
            db, tenant.id, second, evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            a2.id,
            uuid.uuid4(),
            CompetenceScoreIn(score_value=2),
        )

        cv_row = await db.get(CandidateVacancy, cv.id)
        await db.refresh(cv_row)
        assert cv_row.manager_score == 2.0

        await service.apply_round_action(db, tenant.id, user.id, second, "archive")
        await db.refresh(cv_row)
        # The archived round no longer feeds the candidate's score.
        assert cv_row.manager_score == 4.0

    async def test_restore_returns_an_in_progress_round(
        self, db: AsyncSession, tenant, user
    ):
        _, rd_id = await _round(db, tenant, user)
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "archive")
        rd = await service.apply_round_action(db, tenant.id, user.id, rd_id, "restore")
        assert rd["status"] == "in_progress"
        assert rd["archived_at"] is None

    async def test_restore_returns_a_completed_round_to_complete(
        self, db: AsyncSession, tenant, user
    ):
        # A bare status write cannot express this — hence the action verb.
        _, rd_id = await _round(db, tenant, user)
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "complete")
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "archive")
        rd = await service.apply_round_action(db, tenant.id, user.id, rd_id, "restore")
        assert rd["status"] == "complete"
        assert rd["completed_at"] is not None

    async def test_scores_survive_the_archive_round_trip(
        self, db: AsyncSession, tenant, user
    ):
        cv, rd_id = await self._scored_round(db, tenant, user, score=3)
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "archive")
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "restore")

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        assert agg["average"] == 3.0

    async def test_archived_round_is_read_only(self, db: AsyncSession, tenant, user):
        _, rd_id = await _round(db, tenant, user)
        own = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "archive")

        with pytest.raises(HTTPException) as exc:
            await service.set_competence_score(
                db,
                tenant.id,
                user.id,
                own.id,
                uuid.uuid4(),
                CompetenceScoreIn(score_value=3),
            )
        assert exc.value.status_code == 409

    async def test_complete_and_reopen_are_refused_while_archived(
        self, db: AsyncSession, tenant, user
    ):
        _, rd_id = await _round(db, tenant, user)
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "archive")
        for action in ("complete", "reopen"):
            with pytest.raises(HTTPException) as exc:
                await service.apply_round_action(db, tenant.id, user.id, rd_id, action)
            assert exc.value.status_code == 409

    async def test_archiving_twice_is_refused(self, db: AsyncSession, tenant, user):
        """A second archive would restamp the date and drop the reason."""
        _, rd_id = await _round(db, tenant, user)
        first = await service.apply_round_action(
            db, tenant.id, user.id, rd_id, "archive", archived_reason="Wrong seniority"
        )
        with pytest.raises(HTTPException) as exc:
            await service.apply_round_action(db, tenant.id, user.id, rd_id, "archive")
        assert exc.value.status_code == 409

        rd = await service._load_round(db, tenant.id, rd_id)
        await db.refresh(rd)
        assert rd.archived_reason == "Wrong seniority"
        assert rd.archived_at == first["archived_at"]

    async def test_restore_on_a_live_round_is_refused(
        self, db: AsyncSession, tenant, user
    ):
        _, rd_id = await _round(db, tenant, user)
        with pytest.raises(HTTPException) as exc:
            await service.apply_round_action(db, tenant.id, user.id, rd_id, "restore")
        assert exc.value.status_code == 409

    async def test_unknown_action_is_rejected(self, db: AsyncSession, tenant, user):
        _, rd_id = await _round(db, tenant, user)
        with pytest.raises(HTTPException) as exc:
            await service.apply_round_action(db, tenant.id, user.id, rd_id, "nope")
        assert exc.value.status_code == 400


class TestArchivedRoundOnThePublicSurface:
    """An archived round hands out no revocations, so the links stay live.

    Only ``complete`` kills the outstanding tokens (HRP-376 §7c), which
    leaves the external evaluator's page fully reachable after an archive.
    Every write it can make has to be refused server-side — otherwise the
    score endpoints 409 (they already check the round) while Submit sails
    through and flips the invite *and* its sheet to ``submitted`` with
    nothing scored behind them.
    """

    async def test_submit_is_refused(self, db: AsyncSession, tenant, user):
        cv, rd_id = await _round(db, tenant, user)
        inv = await _invite(db, tenant, user, cv, rd_id)
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "archive")

        with pytest.raises(HTTPException) as exc:
            await public_service.public_submit(db, inv.token)
        assert exc.value.status_code == 409
        await db.refresh(inv)
        assert inv.status != "submitted"
        assert inv.submitted_at is None

    async def test_final_notes_are_refused(self, db: AsyncSession, tenant, user):
        cv, rd_id = await _round(db, tenant, user)
        inv = await _invite(db, tenant, user, cv, rd_id)
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "archive")

        with pytest.raises(HTTPException) as exc:
            await public_service.public_save_final_notes(db, inv.token, "late note")
        assert exc.value.status_code == 409

    async def test_renaming_is_refused(self, db: AsyncSession, tenant, user):
        cv, rd_id = await _round(db, tenant, user)
        inv = await _invite(db, tenant, user, cv, rd_id)
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "archive")

        with pytest.raises(HTTPException) as exc:
            await public_service.public_update_name(db, inv.token, "New Name")
        assert exc.value.status_code == 409
        await db.refresh(inv)
        assert inv.evaluator_name == "Ext Eval"

    async def test_restoring_hands_the_page_back(self, db: AsyncSession, tenant, user):
        cv, rd_id = await _round(db, tenant, user)
        inv = await _invite(db, tenant, user, cv, rd_id)
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "archive")
        await service.apply_round_action(db, tenant.id, user.id, rd_id, "restore")

        out = await public_service.public_submit(db, inv.token)
        assert out["status"] == "submitted"


class TestLegacyStatusShape:
    async def test_status_complete_still_works(self, db: AsyncSession, tenant, user):
        _, rd_id = await _round(db, tenant, user)
        rd = await service.update_round_status(
            db, tenant.id, user.id, rd_id, "complete"
        )
        assert rd["status"] == "complete"

    async def test_status_archived_still_works(self, db: AsyncSession, tenant, user):
        _, rd_id = await _round(db, tenant, user)
        rd = await service.update_round_status(
            db, tenant.id, user.id, rd_id, "archived"
        )
        assert rd["status"] == "archived"
        assert rd["archived_at"] is not None

    async def test_unknown_status_is_rejected(self, db: AsyncSession, tenant, user):
        _, rd_id = await _round(db, tenant, user)
        with pytest.raises(HTTPException) as exc:
            await service.update_round_status(db, tenant.id, user.id, rd_id, "banana")
        assert exc.value.status_code == 400


class TestRevokeHelper:
    async def test_returns_the_number_of_killed_links(
        self, db: AsyncSession, tenant, user
    ):
        cv, rd_id = await _round(db, tenant, user)
        await _invite(db, tenant, user, cv, rd_id)
        await _invite(db, tenant, user, cv, rd_id)
        await _invite(db, tenant, user, cv, rd_id, status="declined")

        rd = await service._load_round(db, tenant.id, rd_id)
        killed = await service._revoke_round_invites(db, rd, user.id)
        await db.commit()
        assert killed == 2

        rows = (
            (
                await db.execute(
                    select(AssessmentInvite).where(AssessmentInvite.round_id == rd_id)
                )
            )
            .scalars()
            .all()
        )
        assert sorted(i.status for i in rows) == ["declined", "revoked", "revoked"]
