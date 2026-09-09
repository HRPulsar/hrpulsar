"""HRP-727: the vacancy Manager score comes from one round, chosen by
hiring order.

The old rule ordered the candidate rounds by ``created_at``, so a Final
closed before a forgotten Interview N lost to it, and the candidates
table showed a score from a round nobody would call the last one. The
order is now Pre-interview < Interview 1..N < Final, and the same
selector answers the read side, so the tooltip names exactly the round
the number was computed from.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.modules.recruitment import candidate_service
from app.modules.recruitment import manager_assessment_service as service
from app.modules.recruitment.manager_assessment_schemas import (
    CompetenceScoreIn,
    RoundCreate,
)
from app.modules.recruitment.models import CandidateVacancy
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp186_manager_assessment import (
    _make_candidate_vacancy,
    _make_vacancy,
    _scale_payload,
)


async def _vacancy_with_scale(db: AsyncSession, tenant, user):
    vacancy = await _make_vacancy(db, tenant)
    cv = await _make_candidate_vacancy(db, tenant, vacancy)
    scale = await service.create_scale(db, tenant.id, user.id, _scale_payload())
    await service.set_vacancy_scale(
        db, tenant.id, user.id, vacancy.id, uuid.UUID(str(scale["id"]))
    )
    return vacancy, cv


async def _score_round(
    db: AsyncSession, tenant, user, cv, round_type: str, level: int, **kwargs
) -> uuid.UUID:
    """Create a round, score one competence in it, return its id."""
    rd = await service.create_round(
        db, tenant.id, user.id, cv.id, RoundCreate(type=round_type, **kwargs)
    )
    round_id = uuid.UUID(str(rd["id"]))
    sheet = await service.get_or_create_assessment(
        db, tenant.id, round_id, evaluator_user_id=user.id
    )
    await service.set_competence_score(
        db,
        tenant.id,
        user.id,
        sheet.id,
        uuid.uuid4(),
        CompetenceScoreIn(score_value=level),
    )
    return round_id


async def _complete(db: AsyncSession, tenant, user, round_id: uuid.UUID) -> None:
    await service.update_round_status(db, tenant.id, user.id, round_id, "complete")


class TestSourceRoundIsPickedByHiringOrder:
    async def test_final_wins_even_when_an_interview_was_closed_later(
        self, db: AsyncSession, tenant, user
    ):
        """(a) Final closed first, Interview 2 closed after it — Final wins."""
        _, cv = await _vacancy_with_scale(db, tenant, user)
        final_id = await _score_round(db, tenant, user, cv, "final", 4)
        interview_id = await _score_round(db, tenant, user, cv, "interview", 2)
        await _complete(db, tenant, user, final_id)
        await _complete(db, tenant, user, interview_id)

        await db.refresh(cv)
        assert cv.manager_score == 4.0
        assert cv.manager_score_source_round_id == final_id

    async def test_open_final_loses_to_the_completed_interview(
        self, db: AsyncSession, tenant, user
    ):
        """(b) Interview N closed, Final open but scored — Interview N wins."""
        _, cv = await _vacancy_with_scale(db, tenant, user)
        interview_id = await _score_round(db, tenant, user, cv, "interview", 2)
        await _complete(db, tenant, user, interview_id)
        await _score_round(db, tenant, user, cv, "final", 4)

        await db.refresh(cv)
        assert cv.manager_score == 2.0
        assert cv.manager_score_source_round_id == interview_id

    async def test_archiving_the_last_round_falls_back_to_the_one_before(
        self, db: AsyncSession, tenant, user
    ):
        """(c) Archived rounds never count — the score recomputes below."""
        _, cv = await _vacancy_with_scale(db, tenant, user)
        interview_id = await _score_round(db, tenant, user, cv, "interview", 2)
        await _complete(db, tenant, user, interview_id)
        final_id = await _score_round(db, tenant, user, cv, "final", 4)
        await _complete(db, tenant, user, final_id)
        await db.refresh(cv)
        assert cv.manager_score_source_round_id == final_id

        await service.apply_round_action(db, tenant.id, user.id, final_id, "archive")

        await db.refresh(cv)
        assert cv.manager_score == 2.0
        assert cv.manager_score_source_round_id == interview_id

    async def test_no_scores_at_all_leaves_the_score_empty(
        self, db: AsyncSession, tenant, user
    ):
        _, cv = await _vacancy_with_scale(db, tenant, user)
        await service.create_round(
            db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
        )
        await service.recompute_manager_score(db, tenant.id, cv.id)

        await db.refresh(cv)
        assert cv.manager_score is None
        assert cv.manager_score_source_round_id is None

    async def test_interview_10_outranks_interview_2(
        self, db: AsyncSession, tenant, user
    ):
        """Numeric, not lexicographic — Interview 10 is the later round."""
        _, cv = await _vacancy_with_scale(db, tenant, user)
        second = await _score_round(
            db, tenant, user, cv, "interview", 2, round_number=2
        )
        tenth = await _score_round(
            db, tenant, user, cv, "interview", 4, round_number=10
        )
        await _complete(db, tenant, user, tenth)
        await _complete(db, tenant, user, second)

        await db.refresh(cv)
        assert cv.manager_score_source_round_id == tenth


class TestSourceRoundOnReadPaths:
    async def test_candidates_table_row_names_the_source_round(
        self, db: AsyncSession, tenant, user
    ):
        vacancy, cv = await _vacancy_with_scale(db, tenant, user)
        await _score_round(db, tenant, user, cv, "interview", 2)
        final_id = await _score_round(db, tenant, user, cv, "final", 4)
        await _complete(db, tenant, user, final_id)

        items, _total = await candidate_service.list_vacancy_candidates_enriched(
            db, tenant.id, vacancy.id
        )
        row = next(i for i in items if i["id"] == cv.id)
        assert row["manager_score"] == 4.0
        assert row["manager_score_round"]["id"] == final_id
        assert row["manager_score_round"]["type"] == "final"

    async def test_candidate_card_application_names_the_source_round(
        self, db: AsyncSession, tenant, user
    ):
        _, cv = await _vacancy_with_scale(db, tenant, user)
        await _score_round(db, tenant, user, cv, "interview", 2)
        final_id = await _score_round(db, tenant, user, cv, "final", 4)
        await _complete(db, tenant, user, final_id)

        card = await candidate_service.get_candidate_full_card(
            db, tenant.id, cv.candidate_id
        )
        app = next(a for a in card["vacancy_applications"] if a["cv_id"] == cv.id)
        assert app["manager_score"] == 4.0
        assert app["manager_score_round"]["id"] == final_id
        assert app["manager_score_round"]["type"] == "final"

    async def test_row_without_scores_has_no_source_round(
        self, db: AsyncSession, tenant, user
    ):
        vacancy, cv = await _vacancy_with_scale(db, tenant, user)

        items, _total = await candidate_service.list_vacancy_candidates_enriched(
            db, tenant.id, vacancy.id
        )
        row = next(i for i in items if i["id"] == cv.id)
        assert row["manager_score"] is None
        assert row["manager_score_round"] is None

    async def test_manual_manager_score_is_not_attributed_to_a_round(
        self, db: AsyncSession, tenant, user
    ):
        """A hand-typed score has no round behind it, so it names none."""
        vacancy, cv = await _vacancy_with_scale(db, tenant, user)
        row_cv = await db.get(CandidateVacancy, cv.id)
        assert row_cv is not None
        row_cv.manager_score = 3.0
        row_cv.manager_score_updated_at = datetime.now(timezone.utc)
        await db.commit()

        items, _total = await candidate_service.list_vacancy_candidates_enriched(
            db, tenant.id, vacancy.id
        )
        row = next(i for i in items if i["id"] == cv.id)
        assert row["manager_score"] == 3.0
        assert row["manager_score_round"] is None
