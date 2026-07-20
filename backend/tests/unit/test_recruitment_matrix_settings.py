"""HRP-265: tenant-scoped divergence threshold + Compact matrix aggregates."""

from __future__ import annotations

import uuid

import pytest
from app.modules.recruitment import service, settings_service
from app.modules.recruitment.models import (
    AIAssessment,
    Interview,
)
from app.modules.recruitment.schemas import (
    AssessmentScoreCreate,
    CandidateCreate,
    CandidateVacancyCreate,
    VacancyCreate,
    VacancyProfileUpdate,
)
from app.modules.recruitment.settings_schemas import (
    MatrixSettingsUpdate,
    ScaleConfigCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def matrix_scale(db: AsyncSession, tenant):
    """1..5 scale used by the assessment-matrix tests below."""
    return await settings_service.create_scale(
        db,
        tenant.id,
        ScaleConfigCreate(name="matrix-1-5", min_value=0, max_value=5),
    )


async def _vacancy_with_competences(
    db: AsyncSession,
    tenant,
    user,
    competences: list[dict],
    n_candidates: int = 0,
) -> dict:
    """Build a vacancy with a saved profile and N attached candidates."""
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    await service.save_profile(
        db,
        tenant.id,
        uuid.UUID(str(vacancy["id"])),
        VacancyProfileUpdate(profile_data={"competences": competences}),
    )
    cv_links: list[dict] = []
    candidates: list[dict] = []
    for i in range(n_candidates):
        cand = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(
                first_name=f"First{i}",
                last_name=f"Last{i}",
                email=f"c{i}-{uuid.uuid4().hex[:6]}@example.com",
            ),
        )
        cv = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=uuid.UUID(str(cand["id"])),
                vacancy_id=uuid.UUID(str(vacancy["id"])),
            ),
        )
        candidates.append(cand)
        cv_links.append(cv)
    return {"vacancy": vacancy, "candidates": candidates, "cv_links": cv_links}


# ─── Tenant matrix settings ─────────────────────────────────────────


class TestMatrixSettings:
    async def test_get_returns_default_threshold(
        self, db: AsyncSession, tenant
    ) -> None:
        payload = await settings_service.get_matrix_settings(db, tenant.id)
        assert payload == {"divergence_threshold": 1.0}

    async def test_update_persists_and_round_trips(
        self, db: AsyncSession, tenant
    ) -> None:
        result = await settings_service.update_matrix_settings(
            db, tenant.id, MatrixSettingsUpdate(divergence_threshold=2.5)
        )
        assert result == {"divergence_threshold": 2.5}
        refetched = await settings_service.get_matrix_settings(db, tenant.id)
        assert refetched == {"divergence_threshold": 2.5}

    async def test_update_partial_keeps_existing(
        self, db: AsyncSession, tenant
    ) -> None:
        await settings_service.update_matrix_settings(
            db, tenant.id, MatrixSettingsUpdate(divergence_threshold=0.5)
        )
        # Send an empty body — schema with all-Optional fields → no-op.
        result = await settings_service.update_matrix_settings(
            db, tenant.id, MatrixSettingsUpdate()
        )
        assert result == {"divergence_threshold": 0.5}

    async def test_get_divergence_threshold_helper(
        self, db: AsyncSession, tenant
    ) -> None:
        await settings_service.update_matrix_settings(
            db, tenant.id, MatrixSettingsUpdate(divergence_threshold=1.7)
        )
        assert await settings_service.get_divergence_threshold(db, tenant.id) == 1.7
        # Unknown tenant short-circuits to the historical default.
        assert await settings_service.get_divergence_threshold(db, uuid.uuid4()) == 1.0

    async def test_invalid_range_rejected_by_schema(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MatrixSettingsUpdate(divergence_threshold=-0.5)
        with pytest.raises(ValidationError):
            MatrixSettingsUpdate(divergence_threshold=99.0)
        # threshold == 0 marks every (M, AI) cell as divergent — explicitly
        # banned by ``gt=0`` after the HRP-265 code review.
        with pytest.raises(ValidationError):
            MatrixSettingsUpdate(divergence_threshold=0.0)

    async def test_unknown_tenant_returns_404(self, db: AsyncSession) -> None:
        with pytest.raises(HTTPException) as exc:
            await settings_service.get_matrix_settings(db, uuid.uuid4())
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            await settings_service.update_matrix_settings(
                db, uuid.uuid4(), MatrixSettingsUpdate(divergence_threshold=1.0)
            )
        assert exc.value.status_code == 404


# ─── Assessment matrix aggregates ───────────────────────────────────


_COMPETENCE_SEED = [
    {
        "id": "python-skills",
        "name": "Python",
        "group": "Hard",
        "criticality": "critical",
    },
    {
        "id": "communication",
        "name": "Communication",
        "group": "Soft",
        "criticality": "important",
    },
    {
        "id": "system-design",
        "name": "System Design",
        "group": "Hard",
        "criticality": "important",
    },
    {
        "id": "leadership",
        "name": "Leadership",
        "group": "Soft",
        "criticality": "desirable",
    },
]


class TestAssessmentMatrixBasic:
    async def test_empty_vacancy_returns_empty_candidates(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=0
        )
        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        assert result["candidates"] == []
        assert result["divergence_threshold"] == 1.0
        assert result["max_score"] == 5.0
        # Competences are still surfaced so the UI can render the header row
        assert len(result["competences"]) == len(_COMPETENCE_SEED)

    async def test_per_candidate_aggregates(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv = ctx["cv_links"][0]

        # Manager scores: 5 / 4 on the first two competences, nothing on the
        # remaining two. Denominator stays max_score * total_competences (=20).
        for slug, score in [("python-skills", 5.0), ("communication", 4.0)]:
            await service.record_human_assessment(
                db,
                tenant.id,
                uuid.UUID(str(cv["id"])),
                user.id,
                AssessmentScoreCreate(
                    competence_id=service.normalize_competence_id(slug),
                    score=score,
                ),
            )

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        cand = result["candidates"][0]
        # (5+4) / (5*4) * 100 = 45%
        assert cand["manager_percent"] == 45.0
        assert cand["ai_percent"] is None
        assert cand["divergence_count"] == 0
        assert cand["manager_scored_competences"] == 2
        assert cand["ai_scored_competences"] == 0

    async def test_ai_not_covered_drops_out_of_denominator(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv = ctx["cv_links"][0]

        # AI scored 3/5 on the first two competences and explicitly skipped
        # the next one. Denominator must therefore be max_score * (4 - 1) = 15.
        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=uuid.UUID(str(cv["id"])),
            transcription_status="completed",
            analysis_status="completed",
        )
        db.add(interview)
        await db.commit()
        await db.refresh(interview)

        for slug, score, status in [
            ("python-skills", 3.0, "ready"),
            ("communication", 3.0, "ready"),
            ("system-design", None, "not_covered"),
        ]:
            db.add(
                AIAssessment(
                    tenant_id=tenant.id,
                    interview_id=interview.id,
                    competence_id=service.normalize_competence_id(slug),
                    score=score,
                    status=status,
                    citations=[],
                )
            )
        await db.commit()

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        cand = result["candidates"][0]
        # (3+3) / (5 * 3) * 100 = 40%, not 30% (which would use denom=20).
        assert cand["ai_percent"] == 40.0
        assert cand["ai_not_covered_competences"] == 1
        assert cand["ai_scored_competences"] == 2

    async def test_divergence_uses_tenant_threshold(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv = ctx["cv_links"][0]
        python_id = service.normalize_competence_id("python-skills")

        # Manager 5 / AI 3 — gap of 2.0.
        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=python_id, score=5.0),
        )
        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=uuid.UUID(str(cv["id"])),
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
                competence_id=python_id,
                score=3.0,
                status="ready",
                citations=[],
            )
        )
        await db.commit()

        # Default threshold = 1.0 → divergence True.
        first = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        assert first["divergence_threshold"] == 1.0
        assert first["candidates"][0]["divergence_count"] == 1

        # Bump threshold to 2.5 → the same 2.0 gap no longer counts.
        await settings_service.update_matrix_settings(
            db, tenant.id, MatrixSettingsUpdate(divergence_threshold=2.5)
        )
        second = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        assert second["divergence_threshold"] == 2.5
        assert second["candidates"][0]["divergence_count"] == 0

    async def test_production_ai_status_vocabulary(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """Regression: the real LLM pipeline writes ``assessed`` /
        ``not_covered`` / ``insufficient`` (per CompetenceAssessment in
        prompts_interview.py), not ``ready``. The matrix must treat
        ``assessed`` as a scored cell and ``insufficient`` as dropping
        out of the AI denominator (same posture as ``not_covered``)."""
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv = ctx["cv_links"][0]

        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=uuid.UUID(str(cv["id"])),
            transcription_status="completed",
            analysis_status="completed",
        )
        db.add(interview)
        await db.commit()
        await db.refresh(interview)

        # Two ``assessed`` rows + one ``insufficient`` + one ``not_covered``.
        # Denominator must collapse to max_score * scored = 5 * 2 = 10.
        # Numerator = 4 + 4 = 8. ai_percent = 80%.
        for slug, score, ai_status in [
            ("python-skills", 4.0, "assessed"),
            ("communication", 4.0, "assessed"),
            ("system-design", None, "insufficient"),
            ("leadership", None, "not_covered"),
        ]:
            db.add(
                AIAssessment(
                    tenant_id=tenant.id,
                    interview_id=interview.id,
                    competence_id=service.normalize_competence_id(slug),
                    score=score,
                    status=ai_status,
                    citations=[],
                )
            )
        await db.commit()

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        cand = result["candidates"][0]
        assert cand["ai_percent"] == 80.0
        assert cand["ai_scored_competences"] == 2
        # ``insufficient`` + ``not_covered`` both fall into the
        # not_covered bookkeeping bucket.
        assert cand["ai_not_covered_competences"] == 2

        # Cell-level ai_status normalisation: ``assessed`` → ``ready`` so
        # the frontend renders the score; ``insufficient`` → ``not_covered``.
        cells_by_comp = {str(c["competence_id"]): c for c in cand["cells"]}
        python_cell = cells_by_comp[
            str(service.normalize_competence_id("python-skills"))
        ]
        assert python_cell["ai_status"] == "ready"
        assert python_cell["ai_score"] == 4.0
        sysd_cell = cells_by_comp[str(service.normalize_competence_id("system-design"))]
        assert sysd_cell["ai_status"] == "not_covered"

    async def test_failed_ai_status_drops_out_of_denominator(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """``status='failed'`` (or any non-ready, non-not_covered) must not
        deflate the AI %-match — the cell is treated as if AI hadn't run."""
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv = ctx["cv_links"][0]

        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=uuid.UUID(str(cv["id"])),
            transcription_status="completed",
            analysis_status="completed",
        )
        db.add(interview)
        await db.commit()
        await db.refresh(interview)

        # Three scored + one failed. Denominator before fix would have
        # been 5 * 4 = 20 with numerator 3+3+3 = 9 → 45%. The fix drops
        # ``failed`` out of the denominator: 5 * 3 = 15 → 60%.
        for slug, score, ai_status in [
            ("python-skills", 3.0, "ready"),
            ("communication", 3.0, "ready"),
            ("system-design", 3.0, "ready"),
            ("leadership", None, "failed"),
        ]:
            db.add(
                AIAssessment(
                    tenant_id=tenant.id,
                    interview_id=interview.id,
                    competence_id=service.normalize_competence_id(slug),
                    score=score,
                    status=ai_status,
                    citations=[],
                )
            )
        await db.commit()

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        cand = result["candidates"][0]
        assert cand["ai_percent"] == 60.0
        # ``failed`` is folded into the not_covered bookkeeping bucket so the
        # exposed counters stay self-consistent for the UI.
        assert cand["ai_not_covered_competences"] == 1
        assert cand["ai_scored_competences"] == 3

    async def test_cell_detail_returns_evaluator_breakdown(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cv = ctx["cv_links"][0]
        python_id = service.normalize_competence_id("python-skills")

        await service.record_human_assessment(
            db,
            tenant.id,
            uuid.UUID(str(cv["id"])),
            user.id,
            AssessmentScoreCreate(competence_id=python_id, score=4.0, comment="solid"),
        )
        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=uuid.UUID(str(cv["id"])),
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
                competence_id=python_id,
                score=3.0,
                status="ready",
                citations=[{"text": "I built async services"}],
                reasoning="confident on async",
            )
        )
        await db.commit()

        detail = await service.get_assessment_matrix_cell_detail(
            db,
            tenant.id,
            uuid.UUID(str(ctx["vacancy"]["id"])),
            uuid.UUID(str(cv["id"])),
            python_id,
        )
        assert detail["competence_id"] == python_id
        assert len(detail["manager_entries"]) == 1
        assert detail["manager_entries"][0]["score"] == 4.0
        assert detail["manager_entries"][0]["comment"] == "solid"
        assert detail["ai_latest"]["score"] == 3.0
        assert detail["ai_latest"]["status"] == "ready"
        assert detail["ai_history"] == []


# ─── HRP-361: candidate identity in the Compact matrix ─────────────


class TestMatrixCandidateIdentity:
    async def test_name_uses_denormalised_full_name(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        """Resume-sourced candidates have no Person row (person_id is
        optional since HRP-181 REDO) — the matrix must fall back to the
        denormalised ``Candidate.full_name`` instead of "Unknown"."""
        from app.modules.recruitment.models import Candidate

        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        cand = await db.get(Candidate, uuid.UUID(str(ctx["candidates"][0]["id"])))
        assert cand is not None
        cand.person_id = None
        await db.commit()

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        assert result["candidates"][0]["name"] == "First0 Last0"

    async def test_stage_name_resolved(
        self, db: AsyncSession, tenant, user, matrix_scale
    ) -> None:
        from app.modules.recruitment.models import CandidateVacancy, VacancyStage

        ctx = await _vacancy_with_competences(
            db, tenant, user, _COMPETENCE_SEED, n_candidates=1
        )
        stage = VacancyStage(
            tenant_id=tenant.id,
            vacancy_id=uuid.UUID(str(ctx["vacancy"]["id"])),
            name="Interview",
            code=f"interview-{uuid.uuid4().hex[:4]}",
            sort_order=1,
        )
        db.add(stage)
        await db.commit()
        await db.refresh(stage)

        cv = await db.get(CandidateVacancy, uuid.UUID(str(ctx["cv_links"][0]["id"])))
        assert cv is not None
        cv.stage_id = stage.id
        await db.commit()
        # Refresh the relationship — the shared test session's identity map
        # keeps the instance whose ``stage`` was loaded as None before the
        # FK write (production requests use a fresh session).
        await db.refresh(cv, attribute_names=["stage"])

        result = await service.get_assessment_matrix(
            db, tenant.id, uuid.UUID(str(ctx["vacancy"]["id"]))
        )
        cand = result["candidates"][0]
        assert cand["stage_name"] == "Interview"
        assert cand["stage_id"] == stage.id
