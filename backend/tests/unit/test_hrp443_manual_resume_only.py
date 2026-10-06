"""HRP-443: a parsed resume entered by hand starts AI Insights → Resume only.

The candidate has no resume file; the parsed resume lives on the card
(``Candidate.parsed_resume_jsonb``). Enqueue reads it through the HRP-704
loader and the worker builds its prompt from it. Consent (HRP-979) still
comes first.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from app.core.errors import AppError
from app.modules.recruitment import resume_analysis_service, service
from app.modules.recruitment.models import AIAnalysisRun, Candidate
from app.modules.recruitment.schemas import CandidateManualCreate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._consent import sign_consent
from tests.unit.test_recruitment_resume_only_analysis import (  # noqa: F401 — fixtures
    _stub_celery,
    vacancy_with_profile,
)


async def _manual_cv(db, tenant, user, vacancy, *, consented: bool) -> dict:
    marker = f"Led the {uuid.uuid4().hex[:8]} migration"
    created = await service.add_candidate_to_vacancy_manual(
        db,
        tenant.id,
        user.id,
        vacancy["id"],
        CandidateManualCreate(
            full_name="Hand Entered", email=f"hand-{uuid.uuid4().hex[:6]}@example.com"
        ),
    )
    candidate = await db.get(Candidate, uuid.UUID(str(created["id"])))
    candidate.parsed_resume_jsonb = {
        "summary": marker,
        "experience": [{"company": "Acme", "position": "Lead"}],
    }
    await db.commit()
    if consented:
        await sign_consent(db, tenant.id, candidate.id)
    return {
        "candidate_id": candidate.id,
        "cv_id": uuid.UUID(str(created["candidate_vacancy_id"])),
        "marker": marker,
    }


class TestManualParsedResume:
    async def test_resume_only_starts_on_a_hand_entered_resume(
        self,
        db: AsyncSession,
        tenant,
        user,
        vacancy_with_profile,  # noqa: F811
    ) -> None:
        vacancy, _ = vacancy_with_profile
        p = await _manual_cv(db, tenant, user, vacancy, consented=True)

        res = await resume_analysis_service.enqueue_resume_only_analysis(
            db, tenant.id, p["cv_id"], user.id
        )

        assert res["status"] == "queued"
        run = await db.get(AIAnalysisRun, uuid.UUID(res["run_id"]))
        assert run.candidate_file_id is None
        assert run.resume_snapshot_hash is not None

    async def test_the_worker_reads_the_hand_entered_resume(
        self,
        db: AsyncSession,
        tenant,
        user,
        vacancy_with_profile,  # noqa: F811
        monkeypatch,
    ) -> None:
        import app.modules.ai.llm_client as llm_client
        from app.config import settings as app_settings
        from app.modules.recruitment.prompts_interview import (
            ResumeOnlyAnalysisResult,
            ResumeOnlyCompetenceAssessment,
        )
        from app.modules.recruitment.tasks import analyze_resume_only_task

        vacancy, _ = vacancy_with_profile
        p = await _manual_cv(db, tenant, user, vacancy, consented=True)
        res = await resume_analysis_service.enqueue_resume_only_analysis(
            db, tenant.id, p["cv_id"], user.id
        )
        prompts: list[str] = []

        async def _fake_generate_json(*args, **kwargs):
            prompts.append(kwargs["prompt"])
            return ResumeOnlyAnalysisResult(
                data_completeness="partial",
                competence_assessments=[
                    ResumeOnlyCompetenceAssessment(
                        competence_id="python", score=0.7, status="assessed"
                    )
                ],
                verdict="needs_check",
                verdict_summary="Hand-entered resume read.",
            )

        monkeypatch.setattr(llm_client, "generate_json", _fake_generate_json)
        test_db_url = app_settings.database_url.rsplit("/", 1)[0] + "/hrpulsar_test"
        monkeypatch.setattr(app_settings, "database_url", test_db_url)

        outcome = await asyncio.to_thread(
            analyze_resume_only_task.apply, args=(res["run_id"], str(tenant.id))
        )

        assert outcome.get()["status"] == "completed"
        assert len(prompts) == 1 and p["marker"] in prompts[0]

    async def test_editing_a_hand_entered_resume_flags_the_run_outdated(
        self,
        db: AsyncSession,
        tenant,
        user,
        vacancy_with_profile,  # noqa: F811
    ) -> None:
        """Re-review 04.10: the current resume hash reads the same loader."""
        from app.modules.recruitment.models import CandidateVacancy

        vacancy, _ = vacancy_with_profile
        p = await _manual_cv(db, tenant, user, vacancy, consented=True)
        res = await resume_analysis_service.enqueue_resume_only_analysis(
            db, tenant.id, p["cv_id"], user.id
        )
        run = await db.get(AIAnalysisRun, uuid.UUID(res["run_id"]))
        run.status = "completed"
        await db.commit()
        cv = await db.get(CandidateVacancy, p["cv_id"])

        fresh = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, None
        )
        assert fresh["resume_outdated"] is False

        candidate = await db.get(Candidate, p["candidate_id"])
        candidate.parsed_resume_jsonb = {"summary": "Rewritten by hand"}
        await db.commit()
        stale = await resume_analysis_service.evaluate_analysis_staleness(
            db, tenant.id, cv, run, None
        )
        assert stale["resume_outdated"] is True

    async def test_still_needs_consent(
        self,
        db: AsyncSession,
        tenant,
        user,
        vacancy_with_profile,  # noqa: F811
    ) -> None:
        vacancy, _ = vacancy_with_profile
        p = await _manual_cv(db, tenant, user, vacancy, consented=False)

        with pytest.raises(AppError) as exc:
            await resume_analysis_service.enqueue_resume_only_analysis(
                db, tenant.id, p["cv_id"], user.id
            )

        assert exc.value.code == "consent_required"
        assert (
            await db.scalar(
                select(AIAnalysisRun).where(
                    AIAnalysisRun.candidate_vacancy_id == p["cv_id"]
                )
            )
        ) is None
