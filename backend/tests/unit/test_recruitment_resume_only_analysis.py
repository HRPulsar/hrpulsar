"""HRP-204: resume-only AI analysis, top-up and bulk.

The Celery task is monkey-patched out — these tests exercise the
service layer's preconditions, eligibility logic and bookkeeping
(``AIAnalysisRun`` row creation, CV mirror columns, archival on
success). The actual LLM call is covered separately by an integration
test that we will add when ``ai-resume-analysis.spec.ts`` E2E lands.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from app.modules.recruitment import resume_analysis_service, service
from app.modules.recruitment.models import (
    AIAnalysisRun,
    CandidateFile,
    CandidateVacancy,
    Interview,
    VacancyProfile,
)
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    VacancyCreate,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def vacancy_with_profile(db: AsyncSession, tenant, user):
    v = await service.create_vacancy(
        db,
        tenant.id,
        user.id,
        VacancyCreate(title=f"Senior Backend {uuid.uuid4().hex[:4]}"),
    )
    profile = VacancyProfile(
        tenant_id=tenant.id,
        vacancy_id=v["id"],
        profile_data={
            "competences": [
                {"id": "python", "name": "Python", "criticality": "critical"},
                {"id": "sql", "name": "SQL", "criticality": "important"},
            ]
        },
        version=3,
        language="en",
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return v, profile


@pytest_asyncio.fixture
async def candidate_with_resume(db: AsyncSession, tenant, user):
    cand = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name="Anna",
            last_name="Smirnova",
            email=f"anna-{uuid.uuid4().hex[:6]}@x.test",
        ),
    )
    resume = CandidateFile(
        tenant_id=tenant.id,
        candidate_id=cand["id"],
        file_type="resume",
        original_filename="cv.pdf",
        mime_type="application/pdf",
        file_size=12345,
        parsed_data={"experience": [{"company": "Acme", "position": "Senior"}]},
        raw_text="Long resume text...",
        parse_status="completed",
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)
    return cand, resume


@pytest_asyncio.fixture
async def cv_pair(
    db: AsyncSession,
    tenant,
    user,
    vacancy_with_profile,
    candidate_with_resume,
):
    v, profile = vacancy_with_profile
    cand, resume = candidate_with_resume
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(candidate_id=cand["id"], vacancy_id=v["id"]),
    )
    return {"cv_id": cv["id"], "profile": profile, "resume": resume}


# Mock the Celery delay so the LLM is never actually invoked.
@pytest.fixture(autouse=True)
def _stub_celery(monkeypatch):
    class _StubTask:
        def __init__(self, name: str):
            self.id = f"stub-{name}-{uuid.uuid4().hex[:6]}"

    def _fake_delay(self, *args, **kwargs):
        return _StubTask(self.name)

    from app.modules.recruitment.tasks import (
        analyze_interview_task,
        analyze_resume_only_task,
    )

    monkeypatch.setattr(
        analyze_resume_only_task, "delay", _fake_delay.__get__(analyze_resume_only_task)
    )
    monkeypatch.setattr(
        analyze_interview_task, "delay", _fake_delay.__get__(analyze_interview_task)
    )


# ---------------------------------------------------------------------------
# Validator (pure function)
# ---------------------------------------------------------------------------


class TestResumeOnlyVerdictGuard:
    def test_recommended_rewritten_to_needs_check(self):
        verdict, overridden = resume_analysis_service.apply_resume_only_verdict_guard(
            "recommended"
        )
        assert verdict == "needs_check"
        assert overridden is True

    def test_needs_check_left_alone(self):
        verdict, overridden = resume_analysis_service.apply_resume_only_verdict_guard(
            "needs_check"
        )
        assert verdict == "needs_check"
        assert overridden is False

    def test_not_recommended_left_alone(self):
        verdict, overridden = resume_analysis_service.apply_resume_only_verdict_guard(
            "not_recommended"
        )
        assert verdict == "not_recommended"
        assert overridden is False

    def test_unknown_defaults_to_needs_check_overridden(self):
        verdict, overridden = resume_analysis_service.apply_resume_only_verdict_guard(
            "weird"
        )
        assert verdict == "needs_check"
        assert overridden is True

    def test_none_default_is_needs_check_not_overridden(self):
        verdict, overridden = resume_analysis_service.apply_resume_only_verdict_guard(
            None
        )
        assert verdict == "needs_check"
        assert overridden is False


# ---------------------------------------------------------------------------
# Resume-only enqueue
# ---------------------------------------------------------------------------


class TestEnqueueResumeOnly:
    async def test_happy_path_creates_pending_run(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        res = await resume_analysis_service.enqueue_resume_only_analysis(
            db, tenant.id, cv_pair["cv_id"], user.id
        )
        assert res["status"] == "queued"
        run_id = uuid.UUID(res["run_id"])
        row = await db.get(AIAnalysisRun, run_id)
        assert row.mode == "resume_only"
        assert row.status == "pending"
        assert row.vacancy_profile_version == cv_pair["profile"].version
        assert row.candidate_file_id == cv_pair["resume"].id
        assert row.created_by_id == user.id

        cv_row = await db.get(CandidateVacancy, cv_pair["cv_id"])
        assert cv_row.ai_readiness == "resume_only"
        assert cv_row.ai_verdict == "pending"

    async def test_409_when_no_parsed_resume(
        self, db: AsyncSession, tenant, user, vacancy_with_profile
    ):
        v, _ = vacancy_with_profile
        cand = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(
                first_name="Bob",
                last_name="X",
                email=f"bob-{uuid.uuid4().hex[:6]}@x.test",
            ),
        )
        cv = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(candidate_id=cand["id"], vacancy_id=v["id"]),
        )
        with pytest.raises(HTTPException) as exc:
            await resume_analysis_service.enqueue_resume_only_analysis(
                db, tenant.id, cv["id"], user.id
            )
        assert exc.value.status_code == 409
        assert "Resume parsing" in str(exc.value.detail)

    async def test_409_when_no_profile(
        self, db: AsyncSession, tenant, user, candidate_with_resume
    ):
        cand, _ = candidate_with_resume
        v = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="No profile vacancy")
        )
        cv = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(candidate_id=cand["id"], vacancy_id=v["id"]),
        )
        with pytest.raises(HTTPException) as exc:
            await resume_analysis_service.enqueue_resume_only_analysis(
                db, tenant.id, cv["id"], user.id
            )
        assert exc.value.status_code == 409

    async def test_409_when_run_already_in_flight(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        await resume_analysis_service.enqueue_resume_only_analysis(
            db, tenant.id, cv_pair["cv_id"], user.id
        )
        with pytest.raises(HTTPException) as exc:
            await resume_analysis_service.enqueue_resume_only_analysis(
                db, tenant.id, cv_pair["cv_id"], user.id
            )
        assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Top-up eligibility
# ---------------------------------------------------------------------------


async def _make_completed_resume_only_run(
    db: AsyncSession, tenant, user, cv_pair, age_days: int = 1
) -> AIAnalysisRun:
    # HRP-423: ``uq_ai_analysis_runs_active_per_cv`` allows at most one
    # completed-active row per pair — archive any prior one first, the
    # same way the worker does.
    prior_active = (
        (
            await db.execute(
                select(AIAnalysisRun).where(
                    AIAnalysisRun.candidate_vacancy_id == cv_pair["cv_id"],
                    AIAnalysisRun.archived_at.is_(None),
                    AIAnalysisRun.status == "completed",
                )
            )
        )
        .scalars()
        .all()
    )
    for p in prior_active:
        p.archived_at = datetime.now(UTC)
    await db.flush()

    run = AIAnalysisRun(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv_pair["cv_id"],
        mode="resume_only",
        status="completed",
        data_completeness="partial",
        candidate_file_id=cv_pair["resume"].id,
        vacancy_profile_id=cv_pair["profile"].id,
        vacancy_profile_version=cv_pair["profile"].version,
        verdict="needs_check",
        verdict_summary="Strong on paper",
        ai_score=0.72,
        analysis_data={"mode": "resume_only"},
        created_by_id=user.id,
    )
    db.add(run)
    await db.flush()
    # Backdate so the eligibility check uses a known anchor.
    run.created_at = datetime.now(UTC) - timedelta(days=age_days)
    cv = await db.get(CandidateVacancy, cv_pair["cv_id"])
    cv.ai_analysis_mode = "resume_only"
    cv.ai_readiness = "resume_only"
    cv.ai_verdict = "needs_check"
    await db.commit()
    await db.refresh(run)
    return run


class TestTopupEligibility:
    async def test_no_active_resume_only_run(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        result = await resume_analysis_service.evaluate_topup_eligibility(
            db, tenant.id, cv_pair["cv_id"]
        )
        assert result["eligible"] is False
        assert result["reason"] == "no_active_resume_only_run"

    async def test_no_transcribed_interview(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        await _make_completed_resume_only_run(db, tenant, user, cv_pair)
        result = await resume_analysis_service.evaluate_topup_eligibility(
            db, tenant.id, cv_pair["cv_id"]
        )
        assert result["eligible"] is False
        assert result["reason"] == "no_transcribed_interview"

    async def test_eligible_when_recent_run_and_transcript(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        await _make_completed_resume_only_run(db, tenant, user, cv_pair, age_days=2)
        # Attach a transcribed interview.
        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=cv_pair["cv_id"],
            interviewer_id=user.id,
            transcription_status="completed",
            analysis_status="not_started",
            transcript="ipsum",
        )
        db.add(interview)
        await db.commit()
        await db.refresh(interview)

        result = await resume_analysis_service.evaluate_topup_eligibility(
            db, tenant.id, cv_pair["cv_id"]
        )
        assert result["eligible"] is True
        assert result["interview_id"] == str(interview.id)
        # HRP-269: ``transcribed_interview_id`` mirrors ``interview_id``
        # on the eligible branch so the candidate-card split-button has
        # a single field to read regardless of eligibility.
        assert result["transcribed_interview_id"] == str(interview.id)

    async def test_transcribed_interview_id_surfaced_without_resume_only_run(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        """HRP-269: split-button must offer ``Resume + interview`` even
        before a resume-only baseline exists. Eligibility stays False
        (``no_active_resume_only_run``) but ``transcribed_interview_id``
        is filled so the dropdown can be enabled."""
        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=cv_pair["cv_id"],
            interviewer_id=user.id,
            transcription_status="completed",
            analysis_status="not_started",
            transcript="ipsum",
        )
        db.add(interview)
        await db.commit()
        await db.refresh(interview)

        result = await resume_analysis_service.evaluate_topup_eligibility(
            db, tenant.id, cv_pair["cv_id"]
        )
        assert result["eligible"] is False
        assert result["reason"] == "no_active_resume_only_run"
        assert result["transcribed_interview_id"] == str(interview.id)

    async def test_transcribed_interview_id_null_when_no_transcript(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        """HRP-269: no transcribed interview → dropdown stays disabled.

        Pin ``reason`` too so a refactor that reorders the early-returns
        (e.g. checks transcript before active-run) cannot silently flip
        the user-visible message in ``TopupCallout.reasonMap``.
        """
        result = await resume_analysis_service.evaluate_topup_eligibility(
            db, tenant.id, cv_pair["cv_id"]
        )
        assert result["eligible"] is False
        assert result["reason"] == "no_active_resume_only_run"
        assert result["transcribed_interview_id"] is None

    async def test_archived_interview_not_surfaced(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        """HRP-269: archived interviews must not enable the
        ``Resume + interview`` dropdown — they're soft-deleted and a
        40-cr run against a retired row is not what the recruiter
        meant."""
        from datetime import datetime, timezone

        interview = Interview(
            tenant_id=tenant.id,
            candidate_vacancy_id=cv_pair["cv_id"],
            interviewer_id=user.id,
            transcription_status="completed",
            analysis_status="not_started",
            transcript="ipsum",
            archived_at=datetime.now(timezone.utc),
        )
        db.add(interview)
        await db.commit()

        result = await resume_analysis_service.evaluate_topup_eligibility(
            db, tenant.id, cv_pair["cv_id"]
        )
        assert result["transcribed_interview_id"] is None

    async def test_too_old(self, db: AsyncSession, tenant, user, cv_pair):
        await _make_completed_resume_only_run(db, tenant, user, cv_pair, age_days=45)
        db.add(
            Interview(
                tenant_id=tenant.id,
                candidate_vacancy_id=cv_pair["cv_id"],
                interviewer_id=user.id,
                transcription_status="completed",
                analysis_status="not_started",
                transcript="ipsum",
            )
        )
        await db.commit()
        result = await resume_analysis_service.evaluate_topup_eligibility(
            db, tenant.id, cv_pair["cv_id"]
        )
        assert result["eligible"] is False
        assert result["reason"] == "resume_only_too_old"
        assert result["age_days"] >= 30

    async def test_profile_changed(self, db: AsyncSession, tenant, user, cv_pair):
        await _make_completed_resume_only_run(db, tenant, user, cv_pair)
        db.add(
            Interview(
                tenant_id=tenant.id,
                candidate_vacancy_id=cv_pair["cv_id"],
                interviewer_id=user.id,
                transcription_status="completed",
                analysis_status="not_started",
                transcript="ipsum",
            )
        )
        # Bump the profile version — should invalidate top-up.
        cv_pair["profile"].version = cv_pair["profile"].version + 1
        await db.commit()
        result = await resume_analysis_service.evaluate_topup_eligibility(
            db, tenant.id, cv_pair["cv_id"]
        )
        assert result["eligible"] is False
        assert result["reason"] == "profile_changed"
        assert result["stored_version"] != result["current_version"]


# ---------------------------------------------------------------------------
# Top-up enqueue
# ---------------------------------------------------------------------------


class TestEnqueueTopup:
    async def test_creates_full_run_supersedes_prior(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        prior = await _make_completed_resume_only_run(
            db, tenant, user, cv_pair, age_days=1
        )
        db.add(
            Interview(
                tenant_id=tenant.id,
                candidate_vacancy_id=cv_pair["cv_id"],
                interviewer_id=user.id,
                transcription_status="completed",
                analysis_status="not_started",
                transcript="ipsum",
            )
        )
        await db.commit()

        res = await resume_analysis_service.enqueue_topup_to_full(
            db, tenant.id, cv_pair["cv_id"], user.id
        )
        assert res["status"] == "queued"
        assert res["supersedes_id"] == str(prior.id)

        new_run = await db.get(AIAnalysisRun, uuid.UUID(res["run_id"]))
        assert new_run.mode == "full"
        assert new_run.supersedes_id == prior.id
        assert new_run.status == "pending"

        cv_row = await db.get(CandidateVacancy, cv_pair["cv_id"])
        assert cv_row.ai_readiness == "resume_and_transcript"

    async def test_409_when_ineligible(self, db: AsyncSession, tenant, user, cv_pair):
        with pytest.raises(HTTPException) as exc:
            await resume_analysis_service.enqueue_topup_to_full(
                db, tenant.id, cv_pair["cv_id"], user.id
            )
        assert exc.value.status_code == 409


# Cancel-with-refund tests for HRP-270 live in
# backend/tests/unit/ee/test_recruitment_cancel_refund.py — the refund
# path imports ee.credits, which is absent from the public/community build.


# ---------------------------------------------------------------------------
# Stage helpers (HRP-270)
# ---------------------------------------------------------------------------


class TestStageHelpers:
    def test_resume_only_skips_two_stages(self):
        from app.modules.recruitment.ai_analysis_stages import (
            ALL_STAGES,
            stages_for_mode,
        )

        stages = stages_for_mode("resume_only")
        assert [s["key"] for s in stages] == list(ALL_STAGES)
        skipped = [s["key"] for s in stages if s["skipped"]]
        assert set(skipped) == {"process_findings", "citations"}

    def test_full_mode_skips_nothing(self):
        from app.modules.recruitment.ai_analysis_stages import stages_for_mode

        stages = stages_for_mode("full")
        assert all(not s["skipped"] for s in stages)

    def test_pre_llm_boundary(self):
        from app.modules.recruitment.ai_analysis_stages import is_pre_llm

        assert is_pre_llm(None) is True
        assert is_pre_llm("pre_check") is True
        assert is_pre_llm("competences") is False
        assert is_pre_llm("blind_spots") is False
        assert is_pre_llm("verdict") is False

    def test_pre_llm_unknown_stage_fails_safe(self):
        """HRP-270 review: an unknown stage label (deploy mismatch,
        manual SQL fix-up, future pipeline step) must not raise — it
        must fail safe to ``False`` so the cancel-endpoint never
        refunds money against a stage it cannot reason about."""
        from app.modules.recruitment.ai_analysis_stages import is_pre_llm

        assert is_pre_llm("risk_review") is False
        assert is_pre_llm("") is False


# ---------------------------------------------------------------------------
# Bulk
# ---------------------------------------------------------------------------


class TestBulkResumeOnly:
    async def test_partial_success(
        self, db: AsyncSession, tenant, user, cv_pair, candidate_with_resume
    ):
        # cv_pair is ready; build a second pair with no resume so we
        # can prove that mixed batches return per-row outcomes.
        v_other = await service.create_vacancy(
            db, tenant.id, user.id, VacancyCreate(title="Other")
        )
        cand2_email = f"x-{uuid.uuid4().hex[:6]}@x.test"
        cand2 = await service.create_candidate(
            db,
            tenant.id,
            user.id,
            CandidateCreate(first_name="C", last_name="D", email=cand2_email),
        )
        cv2 = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(candidate_id=cand2["id"], vacancy_id=v_other["id"]),
        )
        v_row = (
            await db.execute(
                select(VacancyProfile).where(
                    VacancyProfile.vacancy_id == cv_pair["profile"].vacancy_id
                )
            )
        ).scalar_one()
        res = await resume_analysis_service.enqueue_bulk_resume_only(
            db,
            tenant.id,
            v_row.vacancy_id,
            [uuid.UUID(str(cv_pair["cv_id"])), uuid.UUID(str(cv2["id"]))],
            user.id,
        )
        # cv_pair OK (has profile + resume); cv2 fails (no profile for
        # vacancy v_other AND wrong vacancy in any case — service
        # rejects per-row).
        assert len(res["queued"]) >= 1
        assert any(
            str(row["candidate_vacancy_id"]) == str(cv_pair["cv_id"])
            for row in res["queued"]
        )

    async def test_400_when_empty(
        self, db: AsyncSession, tenant, user, vacancy_with_profile
    ):
        v, _ = vacancy_with_profile
        with pytest.raises(HTTPException) as exc:
            await resume_analysis_service.enqueue_bulk_resume_only(
                db, tenant.id, v["id"], [], user.id
            )
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class TestListRuns:
    async def test_returns_runs_newest_first(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        # Two completed runs with different timestamps.
        await _make_completed_resume_only_run(db, tenant, user, cv_pair, age_days=10)
        await _make_completed_resume_only_run(db, tenant, user, cv_pair, age_days=1)
        rows = await resume_analysis_service.list_runs_for_cv(
            db, tenant.id, cv_pair["cv_id"]
        )
        assert len(rows) == 2
        assert rows[0].created_at >= rows[1].created_at

    async def test_resume_excerpts_extracted_for_resume_only_run(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        """HRP-271 — resume_only runs surface ``resume_excerpts`` on the
        public schema; the raw ``analysis_data`` blob (which carries
        role-filtered fields like ``red_flags``) stays server-side."""

        from app.modules.recruitment.schemas import AIAnalysisRunRead

        payload = {
            "competence_assessments": [
                {
                    "competence_id": "comp-1",
                    "resume_excerpts": [
                        {
                            "section": "experience",
                            "excerpt_text": "Led a team of five engineers.",
                            "source_company": "Acme",
                            "source_period": "2022 — 2024",
                        }
                    ],
                },
                {
                    "competence_id": "comp-2",
                    "resume_excerpts": [
                        {
                            "section": "skills",
                            "excerpt_text": "PostgreSQL, Redis",
                            "source_company": None,
                            "source_period": None,
                        },
                        {"section": "experience", "excerpt_text": "  "},
                        {"section": "bogus", "excerpt_text": "ignored"},
                    ],
                },
            ],
            "red_flags": [{"description": "secret server-side note"}],
        }
        run = await _make_completed_resume_only_run(db, tenant, user, cv_pair)
        run.analysis_data = payload
        await db.commit()
        await db.refresh(run)

        [serialized] = [
            resume_analysis_service.serialize_run_for_read(r)
            for r in await resume_analysis_service.list_runs_for_cv(
                db, tenant.id, cv_pair["cv_id"]
            )
        ]
        assert isinstance(serialized, AIAnalysisRunRead)
        # Public payload: two valid excerpts, ordered by competence.
        assert serialized.resume_excerpts is not None
        assert len(serialized.resume_excerpts) == 2
        assert serialized.resume_excerpts[0].section == "experience"
        assert serialized.resume_excerpts[0].source_company == "Acme"
        assert serialized.resume_excerpts[1].section == "skills"
        # red_flags must not leak through any field on the response.
        dumped = serialized.model_dump()
        assert "red_flags" not in dumped
        assert "analysis_data" not in dumped

    async def test_resume_excerpts_none_for_full_mode_run(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        """HRP-271 — full-mode runs never expose ``resume_excerpts``
        regardless of payload (resume_excerpts is a resume-only concept)."""

        run = await _make_completed_resume_only_run(db, tenant, user, cv_pair)
        run.mode = "full"
        run.analysis_data = {
            "competence_assessments": [
                {
                    "resume_excerpts": [
                        {"section": "experience", "excerpt_text": "leak attempt"}
                    ]
                }
            ]
        }
        await db.commit()
        await db.refresh(run)

        serialized = resume_analysis_service.serialize_run_for_read(run)
        assert serialized.resume_excerpts is None


# ---------------------------------------------------------------------------
# Code-review follow-ups
# ---------------------------------------------------------------------------


class TestEnqueueLeavesNoStalePendingMirror:
    """Code-review #3 / #13 — neither enqueue path stamps cv.ai_verdict
    to 'pending'; the mirror only flips when a run actually completes,
    so a failed run does not corrupt the candidates table."""

    async def test_resume_only_does_not_set_cv_ai_verdict_pending(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        cv = await db.get(CandidateVacancy, cv_pair["cv_id"])
        cv.ai_verdict = "needs_check"  # simulate a previous run
        await db.commit()

        await resume_analysis_service.enqueue_resume_only_analysis(
            db, tenant.id, cv_pair["cv_id"], user.id
        )
        await db.refresh(cv)
        # The mirror should NOT be reset to ``pending`` just because a
        # new run is in flight — the verdict from the last completed
        # run keeps showing in the candidates table.
        assert cv.ai_verdict == "needs_check"
        assert cv.ai_readiness == "resume_only"

    async def test_topup_does_not_set_cv_ai_verdict_pending(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        await _make_completed_resume_only_run(db, tenant, user, cv_pair, age_days=1)
        cv = await db.get(CandidateVacancy, cv_pair["cv_id"])
        cv.ai_verdict = "needs_check"
        await db.commit()

        db.add(
            Interview(
                tenant_id=tenant.id,
                candidate_vacancy_id=cv_pair["cv_id"],
                interviewer_id=user.id,
                transcription_status="completed",
                analysis_status="not_started",
                transcript="ipsum",
            )
        )
        await db.commit()

        await resume_analysis_service.enqueue_topup_to_full(
            db, tenant.id, cv_pair["cv_id"], user.id
        )
        await db.refresh(cv)
        assert cv.ai_verdict == "needs_check"
        assert cv.ai_readiness == "resume_and_transcript"


class TestResumeOnlySchemaAcceptsRecommended:
    """Code-review #5 — the schema must accept ``verdict='recommended'``
    so the guard can downgrade it (Pydantic rejecting the value would
    fail the whole run instead)."""

    def test_schema_accepts_recommended_for_guard_to_rewrite(self):
        from app.modules.recruitment.prompts_interview import (
            ResumeOnlyAnalysisResult,
        )

        # Pydantic should NOT raise on 'recommended' — the guard
        # downgrades it after validation.
        result = ResumeOnlyAnalysisResult(
            verdict="recommended",
            verdict_summary="Strong on paper",
        )
        assert result.verdict == "recommended"
        # Guard rewrites it.
        final, overridden = resume_analysis_service.apply_resume_only_verdict_guard(
            result.verdict
        )
        assert final == "needs_check"
        assert overridden is True


class TestAdvisoryLockSerialisesConcurrentEnqueues:
    """Code-review #6 / partial-unique-index race — two simultaneous
    enqueue calls for the same CV must not both succeed (the second
    must 409 once the first holds the advisory lock).

    Async DB session, single Postgres connection — the second call
    is serialised behind the first. We simulate by making two calls
    back-to-back; the second hits the pending guard."""

    async def test_second_concurrent_call_409s(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        from fastapi import HTTPException

        await resume_analysis_service.enqueue_resume_only_analysis(
            db, tenant.id, cv_pair["cv_id"], user.id
        )
        with pytest.raises(HTTPException) as exc:
            await resume_analysis_service.enqueue_resume_only_analysis(
                db, tenant.id, cv_pair["cv_id"], user.id
            )
        assert exc.value.status_code == 409


class TestResumeSnapshotHashAndOutdatedDetection:
    """HRP-272 — the snapshot hash is stamped at enqueue time and the
    serializer flips ``resume_outdated`` on when the candidate uploads
    a fresh resume after the run finished.

    The banner drives a re-analyze button that re-runs the existing
    resume-only billable; this test set pins the contract so a future
    refactor cannot quietly drop the snapshot or the comparison."""

    async def test_enqueue_stamps_snapshot_hash(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        res = await resume_analysis_service.enqueue_resume_only_analysis(
            db, tenant.id, cv_pair["cv_id"], user.id
        )
        run = await db.get(AIAnalysisRun, uuid.UUID(res["run_id"]))
        assert run.resume_snapshot_hash is not None
        current = await resume_analysis_service.current_resume_hash_for_cv(
            db, tenant.id, cv_pair["cv_id"]
        )
        assert run.resume_snapshot_hash == current

    async def test_serialize_flags_outdated_when_resume_changed(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        run = await _make_completed_resume_only_run(db, tenant, user, cv_pair)
        cf = cv_pair["resume"]
        await db.refresh(cf)
        run.resume_snapshot_hash = (
            resume_analysis_service._compute_resume_snapshot_hash(cf.parsed_data)
        )
        await db.commit()
        await db.refresh(run)
        new_file = CandidateFile(
            tenant_id=tenant.id,
            candidate_id=cf.candidate_id,
            file_type="resume",
            original_filename="cv_v2.pdf",
            mime_type="application/pdf",
            file_size=23456,
            parsed_data={"experience": [{"company": "Globex", "position": "Lead"}]},
            raw_text="Updated text",
            parse_status="completed",
        )
        db.add(new_file)
        await db.commit()
        current = await resume_analysis_service.current_resume_hash_for_cv(
            db, tenant.id, cv_pair["cv_id"]
        )
        assert current is not None
        assert current != run.resume_snapshot_hash
        serialized = resume_analysis_service.serialize_run_for_read(run, current)
        assert serialized.resume_outdated is True

    async def test_serialize_not_outdated_when_hash_matches(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        run = await _make_completed_resume_only_run(db, tenant, user, cv_pair)
        cf = cv_pair["resume"]
        await db.refresh(cf)
        run.resume_snapshot_hash = (
            resume_analysis_service._compute_resume_snapshot_hash(cf.parsed_data)
        )
        await db.commit()
        await db.refresh(run)
        current = await resume_analysis_service.current_resume_hash_for_cv(
            db, tenant.id, cv_pair["cv_id"]
        )
        serialized = resume_analysis_service.serialize_run_for_read(run, current)
        assert serialized.resume_outdated is False

    async def test_serialize_not_outdated_for_legacy_run_without_hash(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        # Legacy rows created before HRP-272 stay ``resume_outdated=False``
        # — we never claim outdated when we cannot prove it.
        run = await _make_completed_resume_only_run(db, tenant, user, cv_pair)
        assert run.resume_snapshot_hash is None
        current = await resume_analysis_service.current_resume_hash_for_cv(
            db, tenant.id, cv_pair["cv_id"]
        )
        serialized = resume_analysis_service.serialize_run_for_read(run, current)
        assert serialized.resume_outdated is False

    async def test_serialize_not_outdated_for_full_mode_run(
        self, db: AsyncSession, tenant, user, cv_pair
    ):
        # Full-mode runs never carry a snapshot — even if a stale hash
        # somehow ends up on the row, the serializer leaves
        # ``resume_outdated=False`` because the banner is a
        # resume-only-only UI affordance.
        run = await _make_completed_resume_only_run(db, tenant, user, cv_pair)
        run.mode = "full"
        run.resume_snapshot_hash = "deadbeef" * 8
        await db.commit()
        await db.refresh(run)
        serialized = resume_analysis_service.serialize_run_for_read(run, "f" * 64)
        assert serialized.resume_outdated is False


# ---------------------------------------------------------------------------
# HRP-274 — the resume-only worker finalizer writes raw (0..1) + normalized
# (tenant scale) scores and mirrors the (guarded) verdict onto the CV row.
# The Celery task runs eagerly in a worker thread against the test DB with
# the LLM call stubbed out.
# ---------------------------------------------------------------------------


class TestResumeOnlyFinalizerWritesNormalizedScore:
    async def _run_task_with_stubbed_llm(
        self, db, tenant, user, cv_pair, monkeypatch
    ) -> None:
        import asyncio

        import app.modules.ai.llm_client as llm_client
        from app.config import settings as app_settings
        from app.modules.recruitment.prompts_interview import (
            ResumeOnlyAnalysisResult,
            ResumeOnlyCompetenceAssessment,
        )
        from app.modules.recruitment.tasks import analyze_resume_only_task

        res = await resume_analysis_service.enqueue_resume_only_analysis(
            db, tenant.id, cv_pair["cv_id"], user.id
        )
        run_id = res["run_id"]
        await db.commit()

        result = ResumeOnlyAnalysisResult(
            data_completeness="partial",
            competence_assessments=[
                # 1.4 is clamped to 1.0 at ingestion → mean(0.8, 1.0) = 0.9.
                ResumeOnlyCompetenceAssessment(
                    competence_id="python", score=0.8, status="assessed"
                ),
                ResumeOnlyCompetenceAssessment(
                    competence_id="sql", score=1.4, status="assessed"
                ),
            ],
            # The resume-only guard downgrades ``recommended`` to
            # ``needs_check`` — the CV mirror must carry the final word.
            verdict="recommended",
            verdict_summary="Strong resume.",
        )

        async def _fake_generate_json(*args, **kwargs):
            return result

        monkeypatch.setattr(llm_client, "generate_json", _fake_generate_json)
        # The worker builds its own sync engine off settings.database_url;
        # point it at the test DB for the duration of the task.
        test_db_url = app_settings.database_url.rsplit("/", 1)[0] + "/hrpulsar_test"
        monkeypatch.setattr(app_settings, "database_url", test_db_url)

        # ``asyncio.run`` inside the task needs a thread without a running
        # event loop; ``apply`` executes the task eagerly in that thread.
        outcome = await asyncio.to_thread(
            analyze_resume_only_task.apply,
            args=(run_id, str(tenant.id)),
        )
        assert outcome.get()["status"] == "completed"

    async def _reload_cv(self, db, cv_id) -> CandidateVacancy:
        result = await db.execute(
            select(CandidateVacancy)
            .where(CandidateVacancy.id == cv_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one()

    async def test_writes_raw_and_normalized_with_active_scale(
        self, db: AsyncSession, tenant, user, cv_pair, monkeypatch
    ):
        from app.modules.recruitment.models import ScaleConfig

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

        await self._run_task_with_stubbed_llm(db, tenant, user, cv_pair, monkeypatch)

        cv = await self._reload_cv(db, cv_pair["cv_id"])
        assert cv.ai_score == pytest.approx(0.9)
        assert cv.ai_score_normalized == pytest.approx(4.5)
        assert cv.ai_verdict == "needs_check"
        assert cv.ai_analysis_mode == "resume_only"
        assert cv.ai_readiness == "resume_only"

    async def test_normalized_falls_back_to_raw_without_active_scale(
        self, db: AsyncSession, tenant, user, cv_pair, monkeypatch
    ):
        await self._run_task_with_stubbed_llm(db, tenant, user, cv_pair, monkeypatch)

        cv = await self._reload_cv(db, cv_pair["cv_id"])
        # Identity fallback (HRP-274 review) — the raw/normalized toggle
        # must never be inert for tenants without a ScaleConfig.
        assert cv.ai_score == pytest.approx(0.9)
        assert cv.ai_score_normalized == pytest.approx(0.9)
        assert cv.ai_verdict == "needs_check"


# ---------------------------------------------------------------------------
# HRP-423: re-analysis archives the prior active run BEFORE completing
# ---------------------------------------------------------------------------


class TestReRunArchivesPriorActiveRun:
    """``uq_ai_analysis_runs_active_per_cv`` is a non-deferrable partial
    unique index checked per statement. The worker used to flip the new
    run to ``completed`` (via autoflush on the archive lookup) before the
    prior active run's archive UPDATE reached the DB — every resume-only
    re-analysis over an existing completed run died with a
    UniqueViolation on production. The full-mode twin lives in
    ``test_recruitment_rerun_archival.py``."""

    async def test_second_resume_only_run_archives_first(
        self, db: AsyncSession, tenant, user, cv_pair, monkeypatch
    ):
        import asyncio

        import app.modules.ai.llm_client as llm_client
        from app.config import settings as app_settings
        from app.modules.recruitment.prompts_interview import (
            ResumeOnlyAnalysisResult,
            ResumeOnlyCompetenceAssessment,
        )
        from app.modules.recruitment.tasks import analyze_resume_only_task

        prior = await _make_completed_resume_only_run(db, tenant, user, cv_pair)

        res = await resume_analysis_service.enqueue_resume_only_analysis(
            db, tenant.id, cv_pair["cv_id"], user.id
        )
        run_id = res["run_id"]
        await db.commit()

        result = ResumeOnlyAnalysisResult(
            data_completeness="partial",
            competence_assessments=[
                ResumeOnlyCompetenceAssessment(
                    competence_id="python", score=0.8, status="assessed"
                ),
            ],
            verdict="needs_check",
            verdict_summary="Second pass.",
        )

        async def _fake_generate_json(*args, **kwargs):
            return result

        monkeypatch.setattr(llm_client, "generate_json", _fake_generate_json)
        test_db_url = app_settings.database_url.rsplit("/", 1)[0] + "/hrpulsar_test"
        monkeypatch.setattr(app_settings, "database_url", test_db_url)

        outcome = await asyncio.to_thread(
            analyze_resume_only_task.apply,
            args=(run_id, str(tenant.id)),
        )
        assert outcome.get()["status"] == "completed"

        active = (
            (
                await db.execute(
                    select(AIAnalysisRun)
                    .where(
                        AIAnalysisRun.candidate_vacancy_id == cv_pair["cv_id"],
                        AIAnalysisRun.archived_at.is_(None),
                        AIAnalysisRun.status == "completed",
                    )
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        assert len(active) == 1
        assert str(active[0].id) == run_id

        archived = (
            await db.execute(
                select(AIAnalysisRun)
                .where(AIAnalysisRun.id == prior.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert archived.archived_at is not None
        assert str(archived.replaced_by_id) == run_id
