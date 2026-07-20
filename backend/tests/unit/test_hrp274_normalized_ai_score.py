"""HRP-274 — the canonical raw AI score scale is 0..1.

``clamp_unit_score`` pins the ingestion contract (LLM scores are clamped
to ``[0..1]``, never rejected); ``compute_normalized_ai_score`` rebases
the raw value onto the tenant's active scale (``raw × scale_max``) with
an identity fallback when no scale is configured, so the raw/normalized
toggle is never inert. ``compute_score_divergence`` compares the
tenant-scale normalized value with ``manager_score`` — like with like.

The DB-backed tests drive ``_finalize_full_analysis_run`` through a real
(sync) session — mirroring the Celery worker — and assert the
``candidate_vacancies`` mirror actually receives ``ai_score`` /
``ai_score_normalized`` / ``ai_verdict``.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.recruitment.candidate_service import compute_score_divergence
from app.modules.recruitment.prompts_interview import (
    CompetenceAssessment,
    InterviewAnalysisResult,
    ResumeOnlyCompetenceAssessment,
)
from app.modules.recruitment.score_normalization import (
    clamp_unit_score,
    compute_normalized_ai_score,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestClampUnitScore:
    def test_none_propagates(self) -> None:
        assert clamp_unit_score(None) is None

    def test_in_range_untouched(self) -> None:
        assert clamp_unit_score(0.85) == 0.85

    def test_clamps_above_one(self) -> None:
        # The prompt pins 0..1, but the LLM occasionally overshoots or
        # answers on another scale — clamp, never crash the run.
        assert clamp_unit_score(1.2) == 1.0
        assert clamp_unit_score(4.0) == 1.0

    def test_clamps_below_zero(self) -> None:
        assert clamp_unit_score(-0.3) == 0.0

    def test_bounds_are_identity(self) -> None:
        assert clamp_unit_score(0.0) == 0.0
        assert clamp_unit_score(1.0) == 1.0


class TestComputeNormalizedAiScore:
    def test_rebases_onto_scale_ten(self) -> None:
        # raw 0.5 on a 1..10 tenant scale renders as 5.0.
        assert compute_normalized_ai_score(0.5, 10.0) == 5.0

    def test_rebases_onto_scale_five(self) -> None:
        # raw 0.8 on a 0..5 tenant scale renders as 4.0 — NOT 0.16
        # (the pre-decision division bug).
        assert compute_normalized_ai_score(0.8, 5.0) == pytest.approx(4.0)

    def test_propagates_none_raw(self) -> None:
        assert compute_normalized_ai_score(None, 10.0) is None

    def test_identity_fallback_when_scale_missing(self) -> None:
        # No active ScaleConfig — fall back to the identity scale (1.0)
        # so the normalized column is never inert ("—" for every tenant
        # that never created a scale).
        assert compute_normalized_ai_score(0.8, None) == pytest.approx(0.8)

    def test_identity_fallback_for_zero_or_negative_scale(self) -> None:
        # A misconfigured scale must not flatten every candidate to 0 or
        # explode the analysis worker with a ZeroDivisionError.
        assert compute_normalized_ai_score(0.4, 0.0) == pytest.approx(0.4)
        assert compute_normalized_ai_score(0.4, -1.0) == pytest.approx(0.4)

    def test_clamps_raw_above_one_before_rebasing(self) -> None:
        assert compute_normalized_ai_score(1.4, 5.0) == 5.0

    def test_clamps_raw_below_zero_before_rebasing(self) -> None:
        assert compute_normalized_ai_score(-0.5, 5.0) == 0.0

    @pytest.mark.parametrize(
        "raw, scale_max, expected",
        [
            (0.0, 10.0, 0.0),
            (1.0, 10.0, 10.0),
            (0.25, 4.0, 1.0),
            (0.75, 4.0, 3.0),
        ],
    )
    def test_linear_mapping(
        self, raw: float, scale_max: float, expected: float
    ) -> None:
        assert compute_normalized_ai_score(raw, scale_max) == pytest.approx(
            expected
        )


# ---------------------------------------------------------------------------
# Ingestion clamp on the LLM contract schemas
# ---------------------------------------------------------------------------


class TestSchemaScoreClamp:
    def test_full_mode_assessment_clamps_score(self) -> None:
        a = CompetenceAssessment(competence_id="python", score=1.4, status="assessed")
        assert a.score == 1.0
        b = CompetenceAssessment(competence_id="sql", score=-0.2, status="assessed")
        assert b.score == 0.0

    def test_full_mode_assessment_keeps_valid_score(self) -> None:
        a = CompetenceAssessment(competence_id="python", score=0.7, status="assessed")
        assert a.score == 0.7

    def test_full_mode_assessment_none_score(self) -> None:
        a = CompetenceAssessment(
            competence_id="python", score=None, status="not_covered"
        )
        assert a.score is None

    def test_resume_only_assessment_clamps_score(self) -> None:
        a = ResumeOnlyCompetenceAssessment(
            competence_id="python", score=3.5, status="assessed"
        )
        assert a.score == 1.0
        b = ResumeOnlyCompetenceAssessment(
            competence_id="sql", score=0.6, status="assessed"
        )
        assert b.score == 0.6


# ---------------------------------------------------------------------------
# Divergence — compares tenant-scale normalized AI score vs manager score
# ---------------------------------------------------------------------------


class TestScoreDivergenceUsesNormalized:
    def test_diverges_on_tenant_scale(self) -> None:
        # manager 4.0 vs normalized 2.5 on a 0..5 scale — 1.5 ≥ 1.0.
        assert compute_score_divergence(4.0, 2.5) is True

    def test_agreement_within_threshold(self) -> None:
        # raw 0.8 on a 0..5 scale → normalized 4.0; manager 4.5 agrees.
        normalized = compute_normalized_ai_score(0.8, 5.0)
        assert compute_score_divergence(4.5, normalized) is False

    def test_no_divergence_when_ai_side_missing(self) -> None:
        assert compute_score_divergence(4.0, None) is False

    def test_no_divergence_when_manager_side_missing(self) -> None:
        assert compute_score_divergence(None, 2.0) is False

    def test_raw_score_would_have_false_flagged(self) -> None:
        # Regression guard for the original bug: manager 4.0 vs raw 0.8
        # differs by 3.2 — but the normalized value (4.0 on a 0..5
        # scale) agrees perfectly. The production caller passes
        # ``cv.ai_score_normalized``, never raw ``cv.ai_score``.
        raw = 0.8
        normalized = compute_normalized_ai_score(raw, 5.0)
        assert compute_score_divergence(4.0, normalized) is False


# ---------------------------------------------------------------------------
# Full-mode finalizer writes the mirror columns (real DB, sync session —
# same shape as the Celery worker)
# ---------------------------------------------------------------------------


def _make_analysis() -> InterviewAnalysisResult:
    return InterviewAnalysisResult(
        data_completeness="full",
        competence_assessments=[
            # 1.4 is clamped to 1.0 at ingestion → mean(0.8, 1.0) = 0.9.
            CompetenceAssessment(
                competence_id="python", score=0.8, status="assessed"
            ),
            CompetenceAssessment(competence_id="sql", score=1.4, status="assessed"),
        ],
        verdict="recommended",
        verdict_summary="Strong across the profile.",
        key_strength="Python depth",
        key_risk="No SQL production stories",
    )


async def _seed_cv_with_interview(db, tenant, user) -> dict:
    from app.modules.recruitment import service
    from app.modules.recruitment.models import Interview
    from app.modules.recruitment.schemas import (
        CandidateCreate,
        CandidateVacancyCreate,
        VacancyCreate,
    )

    vacancy = await service.create_vacancy(
        db,
        tenant.id,
        user.id,
        VacancyCreate(title=f"HRP-274 finalizer {uuid.uuid4().hex[:4]}"),
    )
    cand = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="Norm",
            last_name="Alized",
            email=f"norm-{uuid.uuid4().hex[:6]}@x.test",
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(candidate_id=cand["id"], vacancy_id=vacancy["id"]),
    )
    interview = Interview(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv["id"],
        type="undecided",
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)
    return {"cv_id": cv["id"], "interview_id": interview.id}


def _sync_engine():
    from app.config import settings
    from sqlalchemy import create_engine

    test_db_url = settings.database_url.rsplit("/", 1)[0] + "/hrpulsar_test"
    return create_engine(test_db_url.replace("+asyncpg", "+psycopg2"))


class TestFullModeFinalizerMirrorsScores:
    async def test_writes_raw_normalized_and_verdict_with_active_scale(
        self, db, tenant, user
    ):
        from app.modules.recruitment.models import (
            AIAnalysisRun,
            CandidateVacancy,
            Interview,
            ScaleConfig,
        )
        from app.modules.recruitment.tasks.analysis import (
            _finalize_full_analysis_run,
        )
        from sqlalchemy.orm import Session

        db.add(
            ScaleConfig(
                tenant_id=tenant.id,
                name="Default 0..5",
                min_value=0.0,
                max_value=5.0,
                is_active=True,
            )
        )
        await db.commit()
        seeded = await _seed_cv_with_interview(db, tenant, user)

        engine = _sync_engine()
        try:
            with Session(engine) as sync_db:
                cv = sync_db.get(CandidateVacancy, seeded["cv_id"])
                interview = sync_db.get(Interview, seeded["interview_id"])
                _finalize_full_analysis_run(
                    sync_db,
                    tenant_id=tenant.id,
                    interview=interview,
                    cv=cv,
                    candidate_name="Norm Alized",
                    analysis=_make_analysis(),
                )
                sync_db.commit()

                sync_db.refresh(cv)
                assert cv.ai_score == pytest.approx(0.9)
                assert cv.ai_score_normalized == pytest.approx(4.5)
                assert cv.ai_verdict == "recommended"
                assert cv.ai_analysis_mode == "full"
                assert cv.ai_readiness == "resume_and_transcript"

                run = (
                    sync_db.query(AIAnalysisRun)
                    .filter(
                        AIAnalysisRun.candidate_vacancy_id == cv.id,
                        AIAnalysisRun.mode == "full",
                        AIAnalysisRun.status == "completed",
                    )
                    .one()
                )
                assert run.ai_score == pytest.approx(0.9)
                assert run.verdict == "recommended"
                assert run.analysis_data["verdict"] == "recommended"
        finally:
            engine.dispose()

    async def test_normalized_falls_back_to_raw_without_active_scale(
        self, db, tenant, user
    ):
        from app.modules.recruitment.models import CandidateVacancy, Interview
        from app.modules.recruitment.tasks.analysis import (
            _finalize_full_analysis_run,
        )
        from sqlalchemy.orm import Session

        seeded = await _seed_cv_with_interview(db, tenant, user)

        engine = _sync_engine()
        try:
            with Session(engine) as sync_db:
                cv = sync_db.get(CandidateVacancy, seeded["cv_id"])
                interview = sync_db.get(Interview, seeded["interview_id"])
                _finalize_full_analysis_run(
                    sync_db,
                    tenant_id=tenant.id,
                    interview=interview,
                    cv=cv,
                    candidate_name="Norm Alized",
                    analysis=_make_analysis(),
                )
                sync_db.commit()

                sync_db.refresh(cv)
                # Identity fallback — the toggle must never be inert.
                assert cv.ai_score == pytest.approx(0.9)
                assert cv.ai_score_normalized == pytest.approx(0.9)
        finally:
            engine.dispose()
