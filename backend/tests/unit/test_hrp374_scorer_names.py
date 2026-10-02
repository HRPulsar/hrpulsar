"""HRP-374 REDO: the Round average tooltip names every evaluator.

REDO 11.09: one line per evaluator as ``{Full name}: {score}`` — a
colleague and an invited external evaluator alike are named in full, so
the aggregate carries the display name for both and nothing else the
tooltip would have to abbreviate.
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


class TestScorerNames:
    async def test_internal_and_external_scorers_are_named_in_full(
        self, db: AsyncSession, tenant, user
    ):
        cv, rd_id = await _round(db, tenant, user)
        comp = uuid.uuid4()
        internal = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db, tenant.id, user.id, internal.id, comp, CompetenceScoreIn(score_value=4)
        )
        external = await _external_sheet(db, tenant, cv, rd_id, name="Ivan Petrov")
        await service.set_competence_score(
            db, tenant.id, None, external.id, comp, CompetenceScoreIn(score_value=2)
        )
        await service.submit_assessment(db, tenant.id, None, external.id)

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        scorers = {s["evaluator_type"]: s for s in agg["competences"][0]["scorers"]}
        # The colleague's full name as the user row spells it, never an
        # abbreviation (REDO 11.09), and no initials field to abbreviate with.
        assert scorers["internal"]["evaluator"] == service._user_full_name(user)
        assert " " in scorers["internal"]["evaluator"]
        assert scorers["external"]["evaluator"] == "Ivan Petrov"
        assert all("initials" not in s for s in scorers.values())
        assert {s["score"] for s in scorers.values()} == {4, 2}

    async def test_a_scored_competence_always_has_scorers_to_show(
        self, db: AsyncSession, tenant, user
    ):
        """The icon is unconditional, so the data behind it must be too.

        One evaluator can never diverge, and that row still has to carry
        the breakdown the neutral (i) tooltip renders.
        """
        cv, rd_id = await _round(db, tenant, user)
        comp = uuid.uuid4()
        internal = await service.get_or_create_assessment(
            db, tenant.id, rd_id, evaluator_user_id=user.id
        )
        await service.set_competence_score(
            db, tenant.id, user.id, internal.id, comp, CompetenceScoreIn(score_value=3)
        )

        agg = await service.round_aggregate(db, tenant.id, rd_id)
        row = agg["competences"][0]
        assert row["diverges"] is False
        assert len(row["scorers"]) == 1
