"""HRP-492 (REDO): a full analysis is visible from the click, not from the verdict.

The AI Insights block derives its progress banner, its stage stepper and
its Cancel button from a ``pending``/``processing`` ``AIAnalysisRun``
row. The plain interview-analyze path only wrote that row once the task
finished (``_mirror_full_run`` inserted it already ``completed``), so
between pressing "Resume + Interview (40 cr)" and the verdict landing
the block kept rendering the previous analysis, banners and all — which
is exactly what QA filed: "the block looks the way it did before the
run was started".

The resume-only path always stamped its row up front; these pin that the
full path now does the same, and that the candidate card never answers
the button with a cached no-op.

Stamping the row up front also puts every terminal exit of
``analyze_interview_task`` on the hook for closing it — a row left in
flight after a dead run is worse than no row at all. That contract is
pinned at the bottom.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from app.models import Person
from app.modules.company.models import Tenant
from app.modules.recruitment import interview_service
from app.modules.recruitment.models import (
    AIAnalysisRun,
    Candidate,
    CandidateVacancy,
    Interview,
    Vacancy,
    VacancyProfile,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _setup(db: AsyncSession) -> tuple[Interview, Tenant, VacancyProfile]:
    suffix = uuid.uuid4().hex[:6]
    tenant = Tenant(name=f"Full {suffix}", slug=f"full-{suffix}", is_demo=False)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    vacancy = Vacancy(tenant_id=tenant.id, title="Backend Engineer", language="en")
    db.add(vacancy)
    await db.commit()
    await db.refresh(vacancy)

    profile = VacancyProfile(
        tenant_id=tenant.id,
        vacancy_id=vacancy.id,
        profile_data={"competences": []},
        version=3,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    person = Person(
        email=f"full.{suffix}@example.com", first_name="Full", last_name="Run"
    )
    db.add(person)
    await db.commit()
    await db.refresh(person)

    candidate = Candidate(
        tenant_id=tenant.id,
        person_id=person.id,
        full_name="Full Run",
        email=person.email,
    )
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)

    cv = CandidateVacancy(
        tenant_id=tenant.id, vacancy_id=vacancy.id, candidate_id=candidate.id
    )
    db.add(cv)
    await db.commit()
    await db.refresh(cv)

    interview = Interview(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv.id,
        transcript="Deterministic transcript for the progress-banner tests.",
        transcription_status="completed",
        analysis_status="pending",
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)
    return interview, tenant, profile


class _FakeAsync:
    id = "celery-task-hrp492"


@pytest.fixture
def dispatched(monkeypatch):
    """Swallow the Celery dispatch, count the calls."""
    calls: list[tuple] = []

    def _fake_delay(*args, **kwargs):
        calls.append(args)
        return _FakeAsync()

    monkeypatch.setattr(
        "app.modules.recruitment.tasks.analyze_interview_task.delay",
        _fake_delay,
    )
    return calls


async def _runs_for(db: AsyncSession, interview: Interview) -> list[AIAnalysisRun]:
    return list(
        (
            await db.execute(
                select(AIAnalysisRun).where(
                    AIAnalysisRun.candidate_vacancy_id == interview.candidate_vacancy_id
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_enqueue_analyze_stamps_a_pending_run(db: AsyncSession, dispatched):
    """The row exists while the analysis runs, not only after it."""
    interview, tenant, profile = await _setup(db)

    result = await interview_service.enqueue_analyze(db, tenant.id, interview.id)

    runs = await _runs_for(db, interview)
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "pending"
    assert run.mode == "full"
    assert run.interview_id == interview.id
    # The card's staleness check compares against the profile the run was
    # started on, so the snapshot has to be taken here and not at the end.
    assert run.vacancy_profile_id == profile.id
    assert run.vacancy_profile_version == 3
    # HRP-270: Cancel revokes through this id.
    assert run.celery_task_id == _FakeAsync.id
    assert result["run_id"] == str(run.id)
    assert result["status"] == "queued"


@pytest.mark.asyncio
async def test_card_full_mode_does_not_answer_with_a_cache_hit(
    db: AsyncSession, dispatched, monkeypatch
):
    """The candidate card's 40-cr button always starts a real run.

    A cache hit means "transcript, profile and resume all unchanged", so
    from this surface it returned the very analysis the block's banner
    had just called stale — instantly, with no run row and no way out of
    the outdated state.
    """
    from app.modules.recruitment.routers import interviews as router_mod

    interview, tenant, _ = await _setup(db)

    def _boom(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("candidate card must not go through the cache")

    monkeypatch.setattr(router_mod.service, "enqueue_analyze_or_cached", _boom)

    class _User:
        tenant_id = tenant.id
        id = uuid.uuid4()

    res = await router_mod.enqueue_ai_analysis(
        interview.candidate_vacancy_id,
        router_mod.AIAnalysisEnqueueRequest(mode="full", interview_id=interview.id),
        db=db,
        current_user=_User(),
    )

    assert res.status == "queued"
    assert res.run_id is not None
    runs = await _runs_for(db, interview)
    assert [r.status for r in runs] == ["pending"]


# ---------------------------------------------------------------------------
# HRP-492 review follow-up: a dead run must not stay in flight
# ---------------------------------------------------------------------------


async def _fail_run(db: AsyncSession, tenant, interview, message: str) -> None:
    """Drive the task's sync helper against the test transaction."""
    from app.modules.recruitment.tasks import analysis as analysis_mod

    await db.run_sync(
        lambda sync_db: analysis_mod._fail_inflight_full_run(
            sync_db, tenant.id, interview.id, message
        )
    )


@pytest.mark.asyncio
async def test_dead_run_is_closed_not_left_in_flight(db: AsyncSession, dispatched):
    """The row the enqueue stamped gets a terminal status when the run dies.

    Left ``processing`` it would keep the candidate card on the progress
    banner for good, hide the next successful analysis behind itself, and
    409 every later enqueue for the pair until the 30-minute sweeper.
    """
    interview, tenant, _ = await _setup(db)
    await interview_service.enqueue_analyze(db, tenant.id, interview.id)

    await _fail_run(db, tenant, interview, "boom")

    runs = await _runs_for(db, interview)
    assert [r.status for r in runs] == ["failed"]
    assert runs[0].error_message == "boom"
    # The stepper reads this; a dead run is not sitting on a stage.
    assert runs[0].current_stage is None


@pytest.mark.asyncio
async def test_pair_is_free_again_after_a_dead_run(db: AsyncSession, dispatched):
    """No lingering 409 ``analysis_already_in_progress`` for the pair."""
    from app.modules.recruitment import resume_analysis_service

    interview, tenant, _ = await _setup(db)
    await interview_service.enqueue_analyze(db, tenant.id, interview.id)

    assert (
        await resume_analysis_service._pending_run(
            db, tenant.id, interview.candidate_vacancy_id
        )
        is not None
    )

    await _fail_run(db, tenant, interview, "boom")

    assert (
        await resume_analysis_service._pending_run(
            db, tenant.id, interview.candidate_vacancy_id
        )
        is None
    )


@pytest.mark.asyncio
async def test_only_this_interviews_run_is_closed(db: AsyncSession, dispatched):
    """Keyed on the interview: a completed run for the same pair — the
    analysis the recruiter is currently reading — must survive."""
    interview, tenant, profile = await _setup(db)
    settled = AIAnalysisRun(
        tenant_id=tenant.id,
        candidate_vacancy_id=interview.candidate_vacancy_id,
        mode="full",
        status="completed",
        vacancy_profile_id=profile.id,
        analysis_data={},
    )
    db.add(settled)
    await db.commit()

    await interview_service.enqueue_analyze(db, tenant.id, interview.id)
    await _fail_run(db, tenant, interview, "boom")

    runs = {r.id: r.status for r in await _runs_for(db, interview)}
    assert runs[settled.id] == "completed"
    assert sorted(runs.values()) == ["completed", "failed"]


# ---------------------------------------------------------------------------
# Review follow-up: one in-flight run per pair, whichever surface starts it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_enqueue_is_refused_while_the_run_is_pending(
    db: AsyncSession, dispatched
):
    """A double POST. The second request read the interview before the
    first one committed, so the ``analysis_status`` check waves it
    through; the pending row is what has to stop it — otherwise two runs
    are in flight and two 40-credit charges land."""
    from app.core.errors import AppError

    interview, tenant, _ = await _setup(db)
    await interview_service.enqueue_analyze(db, tenant.id, interview.id)
    # What the second request sees: the row is pending, the interview is
    # not yet ``processing``.
    interview.analysis_status = "pending"
    await db.commit()

    with pytest.raises(AppError) as exc:
        await interview_service.enqueue_analyze(db, tenant.id, interview.id)

    assert exc.value.code == "analysis_already_in_progress"
    assert len(dispatched) == 1
    assert [r.status for r in await _runs_for(db, interview)] == ["pending"]


@pytest.mark.asyncio
async def test_full_enqueue_is_refused_while_a_resume_only_run_is_pending(
    db: AsyncSession, dispatched
):
    """Resume-only in flight + "Analyze full": two in-flight runs on one
    pair, and the second one to complete would violate
    ``uq_ai_analysis_runs_active_per_cv``."""
    from app.core.errors import AppError

    interview, tenant, profile = await _setup(db)
    db.add(
        AIAnalysisRun(
            tenant_id=tenant.id,
            candidate_vacancy_id=interview.candidate_vacancy_id,
            mode="resume_only",
            status="pending",
            vacancy_profile_id=profile.id,
            analysis_data={},
        )
    )
    await db.commit()

    with pytest.raises(AppError) as exc:
        await interview_service.enqueue_analyze(db, tenant.id, interview.id)

    assert exc.value.code == "analysis_already_in_progress"
    assert dispatched == []
    assert interview.analysis_status == "pending"
    assert [r.mode for r in await _runs_for(db, interview)] == ["resume_only"]


# ---------------------------------------------------------------------------
# Review follow-up: the worker owns exactly the row its interview stamped
# ---------------------------------------------------------------------------


@pytest.fixture
def worker_db(monkeypatch):
    """Point the task's own sync engine at the test database."""
    from app.config import settings as app_settings

    from tests.conftest import TEST_DB_URL

    monkeypatch.setattr(app_settings, "database_url", TEST_DB_URL)
    monkeypatch.setattr(app_settings, "demo_ai_killswitch", False)


async def _fresh_runs(
    db: AsyncSession, cv_id: uuid.UUID
) -> dict[uuid.UUID, AIAnalysisRun]:
    """Re-read the rows — the task writes through its own sync engine."""
    rows = (
        (
            await db.execute(
                select(AIAnalysisRun)
                .where(AIAnalysisRun.candidate_vacancy_id == cv_id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    return {r.id: r for r in rows}


async def _pending_row(
    db: AsyncSession, tenant, interview: Interview, profile
) -> AIAnalysisRun:
    run = AIAnalysisRun(
        tenant_id=tenant.id,
        candidate_vacancy_id=interview.candidate_vacancy_id,
        mode="full",
        status="pending",
        interview_id=interview.id,
        vacancy_profile_id=profile.id,
        analysis_data={},
    )
    db.add(run)
    # Own transaction: ``created_at`` is the transaction's ``now()``, and
    # the worker orders by it.
    await db.commit()
    return run


@pytest.mark.asyncio
async def test_worker_adopts_the_run_of_its_own_interview(
    db: AsyncSession, worker_db, monkeypatch
):
    """Two transcribed interviews on one pair, each with its stamped row.
    The worker for A must flip A's row, not the newest row on the pair."""
    from app.modules.recruitment.tasks import analyze_interview_task

    interview_a, tenant, profile = await _setup(db)
    interview_b = Interview(
        tenant_id=tenant.id,
        candidate_vacancy_id=interview_a.candidate_vacancy_id,
        transcript="Second interview on the same pair.",
        transcription_status="completed",
        analysis_status="pending",
    )
    db.add(interview_b)
    await db.commit()
    run_a = await _pending_row(db, tenant, interview_a, profile)
    run_b = await _pending_row(db, tenant, interview_b, profile)

    def _stop(*args, **kwargs):
        raise RuntimeError("stop before the LLM — adoption is what is under test")

    monkeypatch.setattr("app.modules.ai.llm_client.generate_json", _stop)

    with pytest.raises(RuntimeError):
        analyze_interview_task.run(str(interview_a.id), str(tenant.id))

    runs = await _fresh_runs(db, interview_a.candidate_vacancy_id)
    assert runs[run_a.id].status == "processing"
    assert runs[run_b.id].status == "pending"


@pytest.mark.asyncio
async def test_mirror_failure_keeps_the_analysis_and_closes_the_run(
    db: AsyncSession, dispatched, worker_db, monkeypatch
):
    """The mirror trips ``uq_ai_analysis_runs_active_per_cv``. The verdict
    the recruiter paid for still lands on the interview, and the run row
    is closed as failed instead of staying in flight behind a session
    that can no longer be used."""
    from app.modules.recruitment.prompts_interview import InterviewAnalysisResult
    from app.modules.recruitment.tasks import analysis as analysis_mod
    from app.modules.recruitment.tasks import analyze_interview_task

    interview, tenant, profile = await _setup(db)
    settled = AIAnalysisRun(
        tenant_id=tenant.id,
        candidate_vacancy_id=interview.candidate_vacancy_id,
        mode="full",
        status="completed",
        vacancy_profile_id=profile.id,
        analysis_data={},
    )
    db.add(settled)
    await db.commit()
    result = await interview_service.enqueue_analyze(db, tenant.id, interview.id)
    run_id = uuid.UUID(result["run_id"])

    async def _verdict(*args, **kwargs):
        return InterviewAnalysisResult(
            data_completeness="partial", verdict_summary="Fine."
        )

    monkeypatch.setattr("app.modules.ai.llm_client.generate_json", _verdict)

    def _second_active_row(db_sync, *, tenant_id, interview, cv, **_):
        # The statement the finding describes, raised by Postgres itself so
        # the session really is in the failed state afterwards.
        db_sync.add(
            AIAnalysisRun(
                tenant_id=tenant_id,
                candidate_vacancy_id=cv.id,
                mode="full",
                status="completed",
                interview_id=interview.id,
                analysis_data={},
            )
        )
        db_sync.flush()

    monkeypatch.setattr(analysis_mod, "_finalize_full_analysis_run", _second_active_row)

    # The task calls ``asyncio.run`` itself, so it cannot run on the
    # test's loop.
    out = await asyncio.to_thread(
        analyze_interview_task.run, str(interview.id), str(tenant.id)
    )

    assert out["status"] == "completed"
    runs = await _fresh_runs(db, interview.candidate_vacancy_id)
    assert runs[run_id].status == "failed"
    assert runs[run_id].error_message == (
        "analysis completed but the run record could not be written"
    )
    assert runs[settled.id].status == "completed"
    refreshed = (
        await db.execute(
            select(Interview)
            .where(Interview.id == interview.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed.analysis_status == "completed"
    assert refreshed.analysis_data["verdict_summary"] == "Fine."
