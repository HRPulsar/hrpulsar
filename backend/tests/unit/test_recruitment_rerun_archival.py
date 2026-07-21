"""HRP-423: re-analysis must archive prior active runs BEFORE completing.

``uq_ai_analysis_runs_active_per_cv`` is a non-deferrable partial unique
index (``candidate_vacancy_id WHERE archived_at IS NULL AND
status='completed'``) checked per statement. The full-mode finalizer used
to mark/insert the new run as ``completed`` before the archive UPDATE for
the prior active run reached the DB (via autoflush ordering), which blew
up every re-analysis over an existing completed run with a
UniqueViolation on production. These tests drive
``_finalize_full_analysis_run`` through a real sync Session — the same
shape as the Celery worker — with a pre-existing completed active run in
place. The resume-only twin lives in
``test_recruitment_resume_only_analysis.py``.
"""

from __future__ import annotations

import pytest
from app.modules.recruitment.models import AIAnalysisRun, CandidateVacancy, Interview
from app.modules.recruitment.tasks.analysis import _finalize_full_analysis_run
from sqlalchemy.orm import Session

from tests.unit.test_hrp274_normalized_ai_score import (
    _make_analysis,
    _seed_cv_with_interview,
    _sync_engine,
)


def _make_prior_completed_run(sync_db: Session, tenant, cv_id) -> AIAnalysisRun:
    prior = AIAnalysisRun(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv_id,
        mode="resume_only",
        status="completed",
        verdict="needs_check",
        analysis_data={"mode": "resume_only"},
    )
    sync_db.add(prior)
    sync_db.commit()
    return prior


def _active_completed_runs(sync_db: Session, cv_id) -> list[AIAnalysisRun]:
    return (
        sync_db.query(AIAnalysisRun)
        .filter(
            AIAnalysisRun.candidate_vacancy_id == cv_id,
            AIAnalysisRun.archived_at.is_(None),
            AIAnalysisRun.status == "completed",
        )
        .all()
    )


class TestFullModeReRunArchivesPriorActiveRun:
    async def test_plain_analyze_over_existing_completed_run(self, db, tenant, user):
        seeded = await _seed_cv_with_interview(db, tenant, user)

        engine = _sync_engine()
        try:
            with Session(engine) as sync_db:
                prior = _make_prior_completed_run(sync_db, tenant, seeded["cv_id"])

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

                active = _active_completed_runs(sync_db, cv.id)
                assert len(active) == 1
                run = active[0]
                assert run.mode == "full"
                assert run.id != prior.id

                sync_db.refresh(prior)
                assert prior.archived_at is not None
                assert prior.replaced_by_id == run.id
        finally:
            engine.dispose()

    async def test_topup_completes_pending_and_archives_supersedes_target(
        self, db, tenant, user
    ):
        seeded = await _seed_cv_with_interview(db, tenant, user)

        engine = _sync_engine()
        try:
            with Session(engine) as sync_db:
                prior = _make_prior_completed_run(sync_db, tenant, seeded["cv_id"])

                pending = AIAnalysisRun(
                    tenant_id=tenant.id,
                    candidate_vacancy_id=seeded["cv_id"],
                    mode="full",
                    status="pending",
                    interview_id=seeded["interview_id"],
                    supersedes_id=prior.id,
                    analysis_data={},
                )
                sync_db.add(pending)
                sync_db.commit()

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

                active = _active_completed_runs(sync_db, cv.id)
                assert len(active) == 1
                assert active[0].id == pending.id
                assert active[0].ai_score == pytest.approx(0.9)

                sync_db.refresh(prior)
                assert prior.archived_at is not None
                assert prior.replaced_by_id == pending.id
        finally:
            engine.dispose()
