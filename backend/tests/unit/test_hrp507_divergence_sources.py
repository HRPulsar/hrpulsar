"""HRP-507: DIVERGENCE on the vacancy Candidates block stayed empty.

The compact matrix only ever read the two legacy tables — ``human_assessments``
(Canvas inline cells) and ``ai_assessments`` (interview-backed analyses).
Neither is written by the flows the ticket walks through: the Manager
assessments block stores per-competence scores on the round's evaluation
sheets, and a resume-only AI analysis stores its competence verdicts on the
analysis run. Both sides were therefore ``None`` and no cell could ever
diverge.

These tests drive the real product flows end to end instead of seeding the
legacy tables directly.

Everything below runs on the production default pairing: the manager side
scores on the seeded ``Standard 1-4`` AssessmentScale (weights
0/33/66/100) while the matrix renders the tenant ``ScaleConfig`` 0..5.
Levels therefore land on 0.0 / 1.65 / 3.3 / 5.0 — a fixture that wrote
score_value=5 into the 1..4 scale hid the mismatch that made a manager's
top mark disagree with the AI's top mark.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.recruitment import (
    manager_assessment_service,
    service,
    settings_service,
)
from app.modules.recruitment.manager_assessment_schemas import (
    CompetenceScoreIn,
    RoundCreate,
)
from app.modules.recruitment.models import AIAnalysisRun, CandidateVacancy
from app.modules.recruitment.schemas import (
    AssessmentScoreCreate,
    CandidateCreate,
    CandidateVacancyCreate,
    VacancyCreate,
    VacancyProfileUpdate,
)
from app.modules.recruitment.settings_schemas import ScaleConfigCreate
from sqlalchemy.ext.asyncio import AsyncSession

_COMPETENCE_SEED = [
    {"id": "python-skills", "name": "Python", "group": "Hard"},
    {"id": "communication", "name": "Communication", "group": "Soft"},
    {"id": "system-design", "name": "System Design", "group": "Hard"},
]


@pytest.fixture
async def matrix_scale(db: AsyncSession, tenant):
    return await settings_service.create_scale(
        db,
        tenant.id,
        ScaleConfigCreate(name="hrp507-0-5", min_value=0, max_value=5),
    )


async def _vacancy_with_candidate(db: AsyncSession, tenant, user):
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    vacancy_id = uuid.UUID(str(vacancy["id"]))
    await service.save_profile(
        db,
        tenant.id,
        vacancy_id,
        VacancyProfileUpdate(profile_data={"competences": _COMPETENCE_SEED}),
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
            candidate_id=uuid.UUID(str(candidate["id"])),
            vacancy_id=vacancy_id,
        ),
    )
    return vacancy_id, uuid.UUID(str(cv["id"]))


async def _score_via_round(
    db: AsyncSession, tenant, user, cv_id: uuid.UUID, scores: dict[str, int]
) -> uuid.UUID:
    """Score competences the way the Manager assessments block does."""
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
    return round_id


async def _resume_only_run(
    db: AsyncSession, tenant, cv_id: uuid.UUID, assessments: list[dict]
) -> AIAnalysisRun:
    """The row ``analyze_resume_only_task`` leaves behind."""
    run = AIAnalysisRun(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv_id,
        mode="resume_only",
        status="completed",
        analysis_data={
            "mode": "resume_only",
            "competence_assessments": assessments,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


class TestManagerSideReachesTheMatrix:
    async def test_round_sheet_scores_fill_manager_cells(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        vacancy_id, cv_id = await _vacancy_with_candidate(db, tenant, user)
        await _score_via_round(
            db, tenant, user, cv_id, {"python-skills": 4, "communication": 3}
        )

        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        cells = {str(c["competence_id"]): c for c in matrix["candidates"][0]["cells"]}
        python = cells[str(service.normalize_competence_id("python-skills"))]
        # Level 4 is the top of the 1..4 scale (weight 100) → 5.0 of 5.
        assert python["manager_score"] == 5.0
        assert python["manager_evaluator_count"] == 1
        comms = cells[str(service.normalize_competence_id("communication"))]
        # Level 3 → weight 66 → 3.3 of 5.
        assert comms["manager_score"] == 3.3
        # (5.0 + 3.3) / (5 * 3) * 100
        assert matrix["candidates"][0]["manager_percent"] == 55.3

    async def test_top_marks_on_both_sides_reach_full_match(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """Production default: manager 1..4 scale, tenant 0..5 ScaleConfig.

        The two halves of a cell used to be compared in different units,
        so a manager's maximum (4) sat 1.0 away from the AI's maximum
        (raw 1.0 → 5.0) — exactly the tenant divergence threshold — and
        perfect agreement was reported as disagreement, with manager %
        match unable to pass 80.
        """
        vacancy_id, cv_id = await _vacancy_with_candidate(db, tenant, user)
        await _score_via_round(
            db,
            tenant,
            user,
            cv_id,
            {"python-skills": 4, "communication": 4, "system-design": 4},
        )
        await _resume_only_run(
            db,
            tenant,
            cv_id,
            [
                {"competence_id": slug, "score": 1.0, "status": "assessed"}
                for slug in ("python-skills", "communication", "system-design")
            ],
        )

        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        candidate = matrix["candidates"][0]
        assert matrix["divergence_threshold"] == 1.0
        assert candidate["divergence_count"] == 0
        assert candidate["manager_percent"] == 100.0
        assert candidate["ai_percent"] == 100.0
        for cell in candidate["cells"]:
            assert cell["manager_score"] == cell["ai_score"] == 5.0

    async def test_archived_round_scores_are_ignored(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        from datetime import datetime, timezone

        from app.modules.recruitment.manager_assessment_models import AssessmentRound

        vacancy_id, cv_id = await _vacancy_with_candidate(db, tenant, user)
        round_id = await _score_via_round(
            db, tenant, user, cv_id, {"python-skills": 4}
        )
        rnd = await db.get(AssessmentRound, round_id)
        rnd.archived_at = datetime.now(timezone.utc)
        await db.commit()

        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        cells = {str(c["competence_id"]): c for c in matrix["candidates"][0]["cells"]}
        assert (
            cells[str(service.normalize_competence_id("python-skills"))]["manager_score"]
            is None
        )

    async def test_canvas_edit_supersedes_the_same_manager_round_score(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """One human, two surfaces — the newer opinion wins, no averaging.

        Canvas cells are entered against the tenant ScaleConfig already,
        so 3.0 stays 3.0 while the round's level 4 would have read 5.0.
        """
        vacancy_id, cv_id = await _vacancy_with_candidate(db, tenant, user)
        await _score_via_round(db, tenant, user, cv_id, {"python-skills": 4})
        await service.record_human_assessment(
            db,
            tenant.id,
            cv_id,
            user.id,
            AssessmentScoreCreate(
                competence_id=service.normalize_competence_id("python-skills"),
                score=3.0,
            ),
        )

        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        cells = {str(c["competence_id"]): c for c in matrix["candidates"][0]["cells"]}
        python = cells[str(service.normalize_competence_id("python-skills"))]
        assert python["manager_score"] == 3.0
        assert python["manager_evaluator_count"] == 1

    async def test_cell_detail_agrees_with_the_cell(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """The popover reports the cell's numbers, in the cell's units —
        both halves of it."""
        vacancy_id, cv_id = await _vacancy_with_candidate(db, tenant, user)
        await _score_via_round(db, tenant, user, cv_id, {"python-skills": 4})
        await _resume_only_run(
            db,
            tenant,
            cv_id,
            [{"competence_id": "python-skills", "score": 0.4, "status": "assessed"}],
        )
        competence_id = service.normalize_competence_id("python-skills")

        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        cell = next(
            c
            for c in matrix["candidates"][0]["cells"]
            if c["competence_id"] == competence_id
        )
        detail = await service.get_assessment_matrix_cell_detail(
            db, tenant.id, vacancy_id, cv_id, competence_id
        )

        assert [e["score"] for e in detail["manager_entries"]] == [cell["manager_score"]]
        assert detail["manager_entries"][0]["score"] == 5.0
        # Resume-only candidate: no AIAssessment row exists, so the
        # popover has to reach for the same analysis run the cell used.
        assert detail["ai_latest"] is not None
        assert detail["ai_latest"]["score"] == cell["ai_score"] == 2.0
        assert detail["ai_latest"]["status"] == "ready"

    async def test_cell_detail_rebases_interview_ai_scores(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """The interview-backed half needs the same rebase (raw 0.8 → 4.0)."""
        from app.modules.recruitment.models import AIAssessment, Interview

        vacancy_id, cv_id = await _vacancy_with_candidate(db, tenant, user)
        competence_id = service.normalize_competence_id("python-skills")
        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=cv_id,
            transcription_status="completed",
            analysis_status="completed",
        )
        db.add(interview)
        await db.commit()
        await db.refresh(interview)
        db.add(
            AIAssessment(
                tenant_id=tenant.id,
                interview_id=interview.id,
                competence_id=competence_id,
                score=0.8,
                status="assessed",
                citations=[],
            )
        )
        await db.commit()

        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        cell = next(
            c
            for c in matrix["candidates"][0]["cells"]
            if c["competence_id"] == competence_id
        )
        detail = await service.get_assessment_matrix_cell_detail(
            db, tenant.id, vacancy_id, cv_id, competence_id
        )
        assert detail["ai_latest"]["score"] == cell["ai_score"] == 4.0

    async def test_round_choice_matches_the_manager_score_column(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """Once a round is complete, only complete rounds count.

        ``recompute_manager_score`` narrows to complete rounds and yields
        None when none of them carries a score. The cells have to make the
        same choice, or the grid would show scores from a later
        in-progress round beside an empty Manager column.
        """
        from app.modules.recruitment import manager_assessment_service
        from app.modules.recruitment.manager_assessment_schemas import RoundCreate

        vacancy_id, cv_id = await _vacancy_with_candidate(db, tenant, user)
        first = await manager_assessment_service.create_round(
            db, tenant.id, user.id, cv_id, RoundCreate(type="pre_interview")
        )
        await manager_assessment_service.update_round_status(
            db, tenant.id, user.id, uuid.UUID(str(first["id"])), "complete"
        )
        # A later round that is still open does carry scores.
        await _score_via_round(db, tenant, user, cv_id, {"python-skills": 4})

        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        cells = {str(c["competence_id"]): c for c in matrix["candidates"][0]["cells"]}
        python = cells[str(service.normalize_competence_id("python-skills"))]
        cv = await db.get(CandidateVacancy, cv_id)
        await db.refresh(cv)
        assert cv.manager_score is None
        assert python["manager_score"] is None


class TestAiSideReachesTheMatrix:
    async def test_resume_only_run_fills_ai_cells(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        vacancy_id, cv_id = await _vacancy_with_candidate(db, tenant, user)
        await _resume_only_run(
            db,
            tenant,
            cv_id,
            [
                # Slug id, exactly as the model emits it — the matrix has to
                # normalise it onto the profile key itself.
                {"competence_id": "python-skills", "score": 0.8, "status": "assessed"},
                {"competence_id": "communication", "score": None, "status": "not_covered"},
            ],
        )

        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        cand = matrix["candidates"][0]
        cells = {str(c["competence_id"]): c for c in cand["cells"]}
        python = cells[str(service.normalize_competence_id("python-skills"))]
        # 0.8 raw on the canonical 0..1 scale → 4 on the tenant 0..5 scale.
        assert python["ai_score"] == 4.0
        assert python["ai_status"] == "ready"
        comms = cells[str(service.normalize_competence_id("communication"))]
        assert comms["ai_status"] == "not_covered"
        assert cand["ai_scored_competences"] == 1
        assert cand["ai_not_covered_competences"] == 1

    async def test_archived_run_does_not_fill_cells(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        from datetime import datetime, timezone

        vacancy_id, cv_id = await _vacancy_with_candidate(db, tenant, user)
        run = await _resume_only_run(
            db,
            tenant,
            cv_id,
            [{"competence_id": "python-skills", "score": 0.8, "status": "assessed"}],
        )
        run.archived_at = datetime.now(timezone.utc)
        await db.commit()

        matrix = await service.get_assessment_matrix(db, tenant.id, vacancy_id)
        assert matrix["candidates"][0]["ai_scored_competences"] == 0


class TestDivergenceEndToEnd:
    async def test_manager_round_vs_resume_only_ai_counts_divergence(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        vacancy_id, cv_id = await _vacancy_with_candidate(db, tenant, user)
        # Manager levels 4 / 4 / 3 → 5.0 / 5.0 / 3.3 of 5.
        # AI raw 1.0 / 0.4 / 0.66 → 5.0 / 2.0 / 3.3 — only the middle one moves.
        await _score_via_round(
            db,
            tenant,
            user,
            cv_id,
            {"python-skills": 4, "communication": 4, "system-design": 3},
        )
        await _resume_only_run(
            db,
            tenant,
            cv_id,
            [
                {"competence_id": "python-skills", "score": 1.0, "status": "assessed"},
                {"competence_id": "communication", "score": 0.4, "status": "assessed"},
                {"competence_id": "system-design", "score": 0.66, "status": "assessed"},
            ],
        )

        items, _total = await service.list_vacancy_candidates_enriched(
            db, tenant.id, vacancy_id
        )
        row = items[0]
        assert row["divergence_count"] == 1
        assert len(row["divergence_top"]) == 1
        top = row["divergence_top"][0]
        assert top["competence_name"] == "Communication"
        assert top["manager_score"] == 5.0
        assert top["ai_score"] == 2.0

    async def test_tooltip_preview_is_capped_at_five(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """The badge tooltip lists at most 5 competences (+ "N more")."""
        vacancy = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
        )
        vacancy_id = uuid.UUID(str(vacancy["id"]))
        seed = [{"id": f"comp-{i}", "name": f"Competence {i}"} for i in range(7)]
        await service.save_profile(
            db,
            tenant.id,
            vacancy_id,
            VacancyProfileUpdate(profile_data={"competences": seed}),
        )
        candidate = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(
                first_name="Grace",
                last_name="Hopper",
                email=f"grace-{uuid.uuid4().hex[:6]}@example.com",
            ),
        )
        cv = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=uuid.UUID(str(candidate["id"])),
                vacancy_id=vacancy_id,
            ),
        )
        cv_id = uuid.UUID(str(cv["id"]))
        await _score_via_round(
            db, tenant, user, cv_id, {f"comp-{i}": 4 for i in range(7)}
        )
        await _resume_only_run(
            db,
            tenant,
            cv_id,
            [
                {"competence_id": f"comp-{i}", "score": 0.2, "status": "assessed"}
                for i in range(7)
            ],
        )

        items, _total = await service.list_vacancy_candidates_enriched(
            db, tenant.id, vacancy_id
        )
        row = items[0]
        assert row["divergence_count"] == 7
        assert len(row["divergence_top"]) == 5
