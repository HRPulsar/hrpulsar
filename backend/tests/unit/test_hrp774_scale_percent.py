"""HRP-774: one formula for the manager's percent of scale.

The vacancy matrix (Compact / Canvas / % match column) used to print a
level as ``level / max`` — 3 on "Standard 1-4" as 75 % — while the round
header printed the same level through the scale's level weights — 66 %.
The weights are the canonical conversion: they are what the scale builder
asks for next to every level and what the saved final Manager score is
already rebased onto (``manager_score_weight``). :func:`scale_percent` is
now the only level → percent rule, and every surface reads it.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.recruitment import manager_assessment_service, service
from app.modules.recruitment.manager_assessment_schemas import (
    CompetenceScoreIn,
    RoundCreate,
    ScaleCreate,
    ScaleLevelIn,
)
from app.modules.recruitment.models import AIAnalysisRun
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    VacancyCreate,
    VacancyProfileUpdate,
)
from app.modules.recruitment.score_normalization import scale_percent, weighted_levels
from sqlalchemy.ext.asyncio import AsyncSession

# A deliberately non-linear scale: 3 is worth 60, not 66 and not 75.
_LEVELS = [(1.0, 0.0), (2.0, 30.0), (3.0, 60.0), (4.0, 100.0)]


class TestScalePercent:
    def test_a_level_is_worth_its_weight(self) -> None:
        assert scale_percent(3, _LEVELS) == 60.0
        assert scale_percent(1, _LEVELS) == 0.0
        assert scale_percent(4, _LEVELS) == 100.0

    def test_an_average_sits_between_its_neighbours(self) -> None:
        # 3.5 is halfway from 60 to 100 — not the nearest level's 60.
        assert scale_percent(3.5, _LEVELS) == 80.0
        assert scale_percent(1.5, _LEVELS) == 15.0

    def test_out_of_range_levels_clamp_to_the_ends(self) -> None:
        assert scale_percent(0, _LEVELS) == 0.0
        assert scale_percent(7, _LEVELS) == 100.0

    def test_level_order_does_not_matter(self) -> None:
        assert scale_percent(2.5, list(reversed(_LEVELS))) == 45.0

    def test_a_scale_without_weights_is_linear_from_floor_to_ceiling(self) -> None:
        # The legacy tenant ScaleConfig: two points, (min, 0) and (max, 100).
        assert scale_percent(3, [(0.0, 0.0), (5.0, 100.0)]) == 60.0
        assert scale_percent(3, [(1.0, 0.0), (5.0, 100.0)]) == 50.0

    def test_nothing_to_convert_is_none(self) -> None:
        assert scale_percent(None, _LEVELS) is None
        assert scale_percent(3, []) is None

    def test_weighted_levels_reads_snapshot_dicts(self) -> None:
        snapshot_levels = [
            {"value": 1, "weight": 0, "label": "L1"},
            {"value": 2, "weight": 30},
            {"value": None, "weight": 50},
            "garbage",
        ]
        assert weighted_levels(snapshot_levels) == [(1.0, 0.0), (2.0, 30.0)]


_COMPETENCES = [
    {"id": "python-skills", "name": "Python", "group": "Hard"},
    {"id": "communication", "name": "Communication", "group": "Soft"},
]


async def _scored_candidate(
    db: AsyncSession, tenant, user, scores: dict[str, int]
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Vacancy on the non-linear scale, one candidate, one scored round."""
    scale = await manager_assessment_service.create_scale(
        db,
        tenant.id,
        user.id,
        ScaleCreate(
            name="Weighted",
            is_default=True,
            levels=[
                ScaleLevelIn(value=int(v), label=f"L{int(v)}", weight=int(w))
                for v, w in _LEVELS
            ],
        ),
    )
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    vacancy_id = uuid.UUID(str(vacancy["id"]))
    await service.save_profile(
        db,
        tenant.id,
        vacancy_id,
        VacancyProfileUpdate(profile_data={"competences": _COMPETENCES}),
    )
    await manager_assessment_service.set_vacancy_scale(
        db, tenant.id, user.id, vacancy_id, uuid.UUID(str(scale["id"]))
    )
    candidate = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="Ada",
            last_name="Lovelace",
            email=f"ada-{uuid.uuid4().hex[:6]}@example.com",
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=uuid.UUID(str(candidate["id"])), vacancy_id=vacancy_id
        ),
    )
    cv_id = uuid.UUID(str(cv["id"]))
    rnd = await manager_assessment_service.create_round(
        db, tenant.id, user.id, cv_id, RoundCreate(type="interview")
    )
    round_id = uuid.UUID(str(rnd["id"]))
    sheet = await manager_assessment_service.get_or_create_assessment(
        db, tenant.id, round_id, evaluator_user_id=user.id
    )
    for slug, value in scores.items():
        await manager_assessment_service.set_competence_score(
            db,
            tenant.id,
            user.id,
            sheet.id,
            service.normalize_competence_id(slug),
            CompetenceScoreIn(score_value=value),
        )
    return vacancy_id, cv_id, round_id


@pytest.mark.usefixtures("db")
class TestOneFormulaAcrossTheScreens:
    async def test_round_header_and_matrix_agree_on_one_score(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """The ticket's case: level 3 once. Header, cell and % match all say
        what the scale's weight says — 60 on this scale — and never 75."""
        vacancy_id, cv_id, round_id = await _scored_candidate(
            db, tenant, user, {"python-skills": 3, "communication": 3}
        )

        header = await manager_assessment_service.round_aggregate(
            db, tenant.id, round_id
        )
        assert header["average"] == 3.0
        assert header["average_weight"] == 60.0

        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        candidate = matrix["candidates"][0]
        assert candidate["manager_percent"] == 60.0
        assert all(cell["manager_percent"] == 60.0 for cell in candidate["cells"])

        rows, _total = await service.list_vacancy_candidates_enriched(
            db, tenant.id, vacancy_id
        )
        assert rows[0]["manager_percent"] == 60.0

    async def test_an_average_between_levels_is_not_snapped(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """3 and 4 average to 3.5: header 80 (halfway from 60 to 100), and
        the matrix mean of the two cells (60, 100) is the same 80."""
        vacancy_id, _cv_id, round_id = await _scored_candidate(
            db, tenant, user, {"python-skills": 3, "communication": 4}
        )
        header = await manager_assessment_service.round_aggregate(
            db, tenant.id, round_id
        )
        assert header["average"] == 3.5
        assert header["average_weight"] == 80.0
        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        assert matrix["candidates"][0]["manager_percent"] == 80.0

    async def test_unscored_competences_still_count_as_zero_coverage(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id, _cv_id, _round_id = await _scored_candidate(
            db, tenant, user, {"python-skills": 4}
        )
        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        candidate = matrix["candidates"][0]
        # (100 + 0) / 2 — the totals row pairs this with "1/2 scored".
        assert candidate["manager_percent"] == 50.0
        assert candidate["manager_scored_competences"] == 1

    async def test_ai_side_reads_the_same_weights(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """The AI's raw 0.5 lands on level 2.5 of 1-4, which this scale
        values at 45 — through the very same conversion, not raw x 100."""
        vacancy_id, cv_id, _round_id = await _scored_candidate(
            db, tenant, user, {"python-skills": 3}
        )
        db.add(
            AIAnalysisRun(
                tenant_id=tenant.id,
                candidate_vacancy_id=cv_id,
                mode="resume_only",
                status="completed",
                analysis_data={
                    "mode": "resume_only",
                    "competence_assessments": [
                        {"competence_id": slug, "score": 0.5, "status": "assessed"}
                        for slug in ("python-skills", "communication")
                    ],
                },
            )
        )
        await db.commit()

        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        candidate = matrix["candidates"][0]
        for cell in candidate["cells"]:
            assert cell["ai_score"] == 2.5
            assert cell["ai_percent"] == 45.0
        assert candidate["ai_percent"] == 45.0
