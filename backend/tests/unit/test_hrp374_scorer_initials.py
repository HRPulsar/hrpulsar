"""HRP-374 REDO: the Round average tooltip names every evaluator.

The tooltip lists one line per evaluator — a colleague by the initials
their avatar shows in the round header, an invited external evaluator by
their full name, which is the only name the panel has for them. The
aggregate therefore has to carry both, not just the display name.
"""

from __future__ import annotations

import uuid

from app.modules.recruitment import manager_assessment_service as service
from app.modules.recruitment.manager_assessment_schemas import (
    CompetenceScoreIn,
    RoundCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp186_manager_assessment import (
    _external_sheet,
    _make_candidate_vacancy,
    _make_vacancy,
    _scale_payload,
)


async def _round(db: AsyncSession, tenant, user):
    vacancy = await _make_vacancy(db, tenant)
    cv = await _make_candidate_vacancy(db, tenant, vacancy)
    scale = await service.create_scale(db, tenant.id, user.id, _scale_payload())
    await service.set_vacancy_scale(
        db, tenant.id, user.id, vacancy.id, uuid.UUID(str(scale["id"]))
    )
    rd = await service.create_round(
        db, tenant.id, user.id, cv.id, RoundCreate(type="interview")
    )
    return cv, uuid.UUID(str(rd["id"]))


class TestScorerInitials:
    async def test_internal_scorer_carries_avatar_initials(
        self, db: AsyncSession, tenant, user
    ):
        cv, rd_id = await _round(db, tenant, user)
        comp = uuid.uuid4()
        internal = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            internal.id,
            comp,
            CompetenceScoreIn(score_value=4),
        )

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        scorer = agg["competences"][0]["scorers"][0]
        assert scorer["evaluator_type"] == "internal"
        # Same two letters the round header's avatar prints.
        assert scorer["initials"] == service._initials(scorer["evaluator"])
        assert len(scorer["initials"]) == 2

    async def test_external_scorer_has_no_initials_and_keeps_its_full_name(
        self, db: AsyncSession, tenant, user
    ):
        cv, rd_id = await _round(db, tenant, user)
        comp = uuid.uuid4()
        external = await _external_sheet(db, tenant, cv, rd_id, name="Ivan Petrov")
        await service.set_competence_score(
            db, tenant.id, None, external.id, comp, CompetenceScoreIn(score_value=2)
        )
        await service.submit_assessment(db, tenant.id, None, external.id)

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        scorer = agg["competences"][0]["scorers"][0]
        assert scorer["evaluator_type"] == "external"
        assert scorer["evaluator"] == "Ivan Petrov"
        assert scorer["initials"] is None

    async def test_a_scored_competence_always_has_scorers_to_show(
        self, db: AsyncSession, tenant, user
    ):
        """The icon is unconditional now, so the data behind it must be too.

        One evaluator can never diverge, and that row still has to carry
        the breakdown the neutral (i) tooltip renders.
        """
        cv, rd_id = await _round(db, tenant, user)
        comp = uuid.uuid4()
        internal = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db,
            tenant.id,
            user.id,
            internal.id,
            comp,
            CompetenceScoreIn(score_value=3),
        )

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        row = agg["competences"][0]
        assert row["diverges"] is False
        assert len(row["scorers"]) == 1
