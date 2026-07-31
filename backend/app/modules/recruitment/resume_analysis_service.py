"""HRP-204: resume-only AI analysis + top-up + bulk + history.

Backs ``POST /api/recruitment/candidate-vacancies/{cv_id}/ai-analyses``
and the bulk/history sibling endpoints. The full-interview pipeline
remains in ``interview_service.enqueue_analyze`` — this module covers
the two new entry points (resume-only, top-up to full) and the
history/eligibility reads.

Pricing (see ``ee/credits.yaml``):

* ``recruitment.analyze_resume_only`` — 20 cr per run.
* ``recruitment.analyze_topup_to_full`` — 20 cr (the user already paid
  20 cr for the resume-only run; top-up pays the delta, not the full
  40 cr).
* Bulk = N × resume-only unit price; capped at the available balance
  by the partial-batch flow on the API surface.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.recruitment.models import (
    AIAnalysisRun,
    CandidateFile,
    CandidateVacancy,
    Interview,
    Vacancy,
    VacancyProfile,
)
from app.modules.recruitment.schemas import (
    AIAnalysisRunRead,
    ResumeExcerptRead,
)

logger = logging.getLogger(__name__)


# Top-up is blocked when the prior resume-only run is older than this
# threshold OR the vacancy profile has been re-edited since — keeps a
# stale baseline from contaminating the full re-analysis.
TOPUP_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_cv_or_404(
    db: AsyncSession, tenant_id: uuid.UUID, cv_id: uuid.UUID
) -> CandidateVacancy:
    cv = await db.scalar(
        select(CandidateVacancy).where(
            CandidateVacancy.id == cv_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
    )
    if cv is None:
        raise AppError(
            "candidate_vacancy_link_not_found", status.HTTP_404_NOT_FOUND
        )
    return cv


async def _latest_parsed_resume(
    db: AsyncSession, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> CandidateFile | None:
    # Review #1 (HRP-272): secondary ``id DESC`` tiebreaker — two
    # CandidateFile rows can land with identical ``created_at`` (bulk
    # import, seeded fixtures, clock truncation), and without a
    # deterministic tiebreaker Postgres returns whichever row VACUUM
    # left first. That flapped the current resume hash across requests
    # and made the outdated banner appear and disappear without any
    # user action.
    return await db.scalar(
        select(CandidateFile)
        .where(
            CandidateFile.tenant_id == tenant_id,
            CandidateFile.candidate_id == candidate_id,
            CandidateFile.file_type == "resume",
            CandidateFile.parse_status == "completed",
        )
        .order_by(CandidateFile.created_at.desc(), CandidateFile.id.desc())
        .limit(1)
    )


async def _vacancy_profile(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy_id: uuid.UUID
) -> VacancyProfile | None:
    return await db.scalar(
        select(VacancyProfile).where(
            VacancyProfile.vacancy_id == vacancy_id,
            VacancyProfile.tenant_id == tenant_id,
        )
    )


async def _active_run(
    db: AsyncSession, tenant_id: uuid.UUID, cv_id: uuid.UUID
) -> AIAnalysisRun | None:
    """Return the currently-active (non-archived, completed) run for a
    pair, or None when no run has finished yet."""
    return await db.scalar(
        select(AIAnalysisRun)
        .where(
            AIAnalysisRun.tenant_id == tenant_id,
            AIAnalysisRun.candidate_vacancy_id == cv_id,
            AIAnalysisRun.archived_at.is_(None),
            AIAnalysisRun.status == "completed",
        )
        .order_by(AIAnalysisRun.created_at.desc())
        .limit(1)
    )


async def _pending_run(
    db: AsyncSession, tenant_id: uuid.UUID, cv_id: uuid.UUID
) -> AIAnalysisRun | None:
    """Return any in-flight run (pending/processing) for a pair."""
    return await db.scalar(
        select(AIAnalysisRun)
        .where(
            AIAnalysisRun.tenant_id == tenant_id,
            AIAnalysisRun.candidate_vacancy_id == cv_id,
            AIAnalysisRun.status.in_(("pending", "processing")),
        )
        .order_by(AIAnalysisRun.created_at.desc())
        .limit(1)
    )


def _compute_resume_snapshot_hash(parsed_data: dict | None) -> str | None:
    """HRP-272 — deterministic SHA256 of a parsed-resume payload.

    ``sort_keys=True`` is recursive over nested dicts; lists keep their
    emitted order because list order in a parsed resume is
    semantically meaningful (experience timeline, skill priority).

    Review #4 (HRP-272): ``None`` parsed_data → ``None`` hash (no
    resume to compare against), but ``{}`` is treated as a *real*
    empty resume — its hash is the SHA256 of ``"{}"`` so a downgrade
    from a real parse to an empty re-parse still flips outdated. The
    previous behaviour collapsed ``{}`` to ``None`` and silently hid
    the banner when a candidate replaced their CV with one that
    parsed to nothing.

    Review #7 (HRP-272): no ``default=`` — non-JSON-serializable
    values must fail loud at insertion time rather than be silently
    stringified with an unstable repr that diverges between Python
    write and JSONB read paths.
    """
    if parsed_data is None:
        return None
    payload = json.dumps(parsed_data, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


async def current_resume_hash_for_candidate(
    db: AsyncSession, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> str | None:
    """HRP-272 — hash of the candidate's latest parsed resume.

    Returns ``None`` when no parsed resume exists yet. Read-only, safe
    to call from any GET handler.
    """
    latest = await _latest_parsed_resume(db, tenant_id, candidate_id)
    if latest is None:
        return None
    return _compute_resume_snapshot_hash(latest.parsed_data)


async def current_resume_hash_for_cv(
    db: AsyncSession, tenant_id: uuid.UUID, cv_id: uuid.UUID
) -> str | None:
    """HRP-272 — same as ``current_resume_hash_for_candidate`` but accepts
    a candidate-vacancy id (the unit the list endpoint operates on).
    """
    # Review #8 (HRP-272): ``db.scalar`` returns the *scalar* candidate
    # UUID (or None when the CV does not belong to the tenant), not a
    # CandidateVacancy ORM row. Name the bind accordingly so a future
    # refactor cannot accidentally do ``candidate_id.candidate_id``.
    candidate_id = await db.scalar(
        select(CandidateVacancy.candidate_id).where(
            CandidateVacancy.id == cv_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
    )
    if candidate_id is None:
        return None
    return await current_resume_hash_for_candidate(
        db, tenant_id, candidate_id
    )


async def _acquire_cv_lock(db: AsyncSession, cv_id: uuid.UUID) -> None:
    """Postgres transaction-scoped advisory lock per candidate_vacancy.

    Held for the duration of the request transaction (``commit`` /
    ``rollback`` releases it). Two concurrent ``enqueue_*`` calls for
    the same pair serialise here so the in-flight check + insert pair
    cannot interleave. The lock key is deterministic — ``hashtextextended``
    of ``'ai_analysis:' || cv_id`` — so it never collides with other
    advisory-lock callers in the codebase.
    """
    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended('ai_analysis:' || :cv_id, 0))"
        ).bindparams(cv_id=str(cv_id))
    )


# ---------------------------------------------------------------------------
# Resume-only
# ---------------------------------------------------------------------------


async def _enqueue_resume_only_unbilled(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_vacancy_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> dict:
    """Inner worker used by the BILLABLE single-row entry point AND by
    the bulk fan-out. Bulk pays once at the wrapper level
    (``recruitment.bulk_analyze_resume_only`` × N), so it must NOT call
    the wrapped public entry point — that would double-charge by going
    through ``ee/billing.py``'s monkey-patched ``enqueue_resume_only_analysis``
    a second time per row.
    """

    from app.modules.recruitment.tasks import analyze_resume_only_task

    cv = await _get_cv_or_404(db, tenant_id, candidate_vacancy_id)

    if await _pending_run(db, tenant_id, candidate_vacancy_id):
        raise AppError(
            "analysis_already_in_progress", status.HTTP_409_CONFLICT
        )

    resume = await _latest_parsed_resume(db, tenant_id, cv.candidate_id)
    if resume is None or not (resume.parsed_data or {}):
        raise AppError(
            "resume_parsing_required",
            status.HTTP_409_CONFLICT,
        )

    profile = await _vacancy_profile(db, tenant_id, cv.vacancy_id)
    if profile is None or not (profile.profile_data or {}).get("competences"):
        raise AppError(
            "vacancy_competency_profile_required",
            status.HTTP_409_CONFLICT,
        )

    # Per-CV advisory lock keeps two concurrent requests for the same
    # pair from both passing the in-flight check and inserting two
    # pending rows; the partial unique index only constrains
    # ``status='completed'`` so without the lock both runs would race
    # to commit and the loser would burn 20 cr on a doomed retry. The
    # lock is held for the duration of the request transaction.
    await _acquire_cv_lock(db, cv.id)

    # Re-check pending after acquiring the lock — a sibling request
    # may have inserted a row between our first check and the lock.
    if await _pending_run(db, tenant_id, candidate_vacancy_id):
        raise AppError(
            "analysis_already_in_progress", status.HTTP_409_CONFLICT
        )

    run = AIAnalysisRun(
        tenant_id=tenant_id,
        candidate_vacancy_id=cv.id,
        mode="resume_only",
        status="pending",
        candidate_file_id=resume.id,
        vacancy_profile_id=profile.id,
        vacancy_profile_version=profile.version,
        # HRP-272: stamp the parsed-resume snapshot at enqueue time so
        # the GET handler can flag the active run as outdated when the
        # candidate uploads a fresh resume between this run and the
        # banner render.
        resume_snapshot_hash=_compute_resume_snapshot_hash(resume.parsed_data),
        created_by_id=actor_user_id,
        analysis_data={},
    )
    db.add(run)
    # Mark the readiness mirror so the table caption knows a resume
    # is parsed; ``ai_verdict`` stays at its prior value (default
    # ``pending`` when none ran before) — letting it ride through the
    # Celery task without intermediate writes means a failed run does
    # not corrupt the mirror.
    cv.ai_readiness = "resume_only"
    await db.commit()

    # Dispatch AFTER commit so the Celery worker — running in its own
    # sync Session — can always read the just-inserted row. Dispatching
    # before commit is the classic Celery race that lands the task in a
    # 'Run not found' branch and orphans the pending row.
    task = analyze_resume_only_task.delay(str(run.id), str(tenant_id))

    # HRP-270: stash the Celery id so the cancel endpoint can call
    # ``celery.control.revoke(terminate=True)``. We do it post-commit
    # and ignore the (theoretical) tiny window before the second
    # commit lands — a cancel that lands in that window simply marks
    # the row cancelled, the worker sees it on pickup and exits.
    run.celery_task_id = task.id
    await db.commit()

    return {"task_id": task.id, "run_id": str(run.id), "status": "queued"}


async def enqueue_resume_only_analysis(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_vacancy_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> dict:
    """Validate inputs, create the pending ``AIAnalysisRun`` row and
    queue the resume-only Celery task.

    The pre-condition list is intentionally tight so the LLM call never
    runs on broken inputs (refunds are expensive):

    * candidate has a parsed resume,
    * vacancy has a competency profile,
    * no other in-flight run for the same pair (caller must wait or
      cancel manually).

    Public entry — wrapped by ``ee/billing.py`` at 20 cr per call.
    """
    return await _enqueue_resume_only_unbilled(
        db, tenant_id, candidate_vacancy_id, actor_user_id
    )


# ---------------------------------------------------------------------------
# Top-up to full (resume-only → full +20 cr)
# ---------------------------------------------------------------------------


async def evaluate_topup_eligibility(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_vacancy_id: uuid.UUID,
) -> dict:
    """Pure read: decide whether a top-up is currently allowed.

    Used by the UI to swap the ``Run full (40 cr)`` button for
    ``Upgrade to full (+20 cr)`` and tell the recruiter why a top-up
    has expired.
    """

    cv = await _get_cv_or_404(db, tenant_id, candidate_vacancy_id)

    # HRP-269: load the latest transcribed interview up front so we can
    # always surface ``transcribed_interview_id`` to the candidate-card
    # split-button. The other early-return branches below still gate
    # ``eligible`` / ``interview_id`` on the resume-only-baseline checks
    # — they only mean a *top-up* is blocked, not that the recruiter
    # can't kick off a full run from scratch.
    transcribed_interview = await db.scalar(
        select(Interview)
        .where(
            Interview.candidate_vacancy_id == cv.id,
            Interview.tenant_id == tenant_id,
            Interview.transcription_status == "completed",
            # HRP-269: do not surface archived interviews as
            # ``transcribed_interview_id`` — they're soft-deleted and the
            # candidate-card split-button must not enable a 40-cr run
            # against a row a recruiter explicitly retired.
            Interview.archived_at.is_(None),
        )
        # ``id`` secondary sort keeps the pick deterministic when two
        # interviews share ``created_at`` (bulk upload in one task).
        .order_by(Interview.created_at.desc(), Interview.id.desc())
        .limit(1)
    )
    transcribed_interview_id = (
        str(transcribed_interview.id) if transcribed_interview is not None else None
    )

    active = await _active_run(db, tenant_id, cv.id)
    if active is None or active.mode != "resume_only":
        return {
            "eligible": False,
            "reason": "no_active_resume_only_run",
            "active_run_id": str(active.id) if active else None,
            "transcribed_interview_id": transcribed_interview_id,
        }

    if transcribed_interview is None:
        return {
            "eligible": False,
            "reason": "no_transcribed_interview",
            "active_run_id": str(active.id),
            "transcribed_interview_id": None,
        }

    age = datetime.now(UTC) - (
        active.created_at.replace(tzinfo=UTC)
        if active.created_at.tzinfo is None
        else active.created_at
    )
    if age > timedelta(days=TOPUP_WINDOW_DAYS):
        return {
            "eligible": False,
            "reason": "resume_only_too_old",
            "active_run_id": str(active.id),
            "age_days": age.days,
            "window_days": TOPUP_WINDOW_DAYS,
            "transcribed_interview_id": transcribed_interview_id,
        }

    # Profile version must match — a recruiter edit to the competency
    # profile invalidates the resume-only baseline.
    profile = await _vacancy_profile(db, tenant_id, cv.vacancy_id)
    if profile is None:
        return {
            "eligible": False,
            "reason": "profile_missing",
            "active_run_id": str(active.id),
            "transcribed_interview_id": transcribed_interview_id,
        }
    if (
        active.vacancy_profile_version is not None
        and profile.version != active.vacancy_profile_version
    ):
        return {
            "eligible": False,
            "reason": "profile_changed",
            "active_run_id": str(active.id),
            "stored_version": active.vacancy_profile_version,
            "current_version": profile.version,
            "transcribed_interview_id": transcribed_interview_id,
        }

    return {
        "eligible": True,
        "active_run_id": str(active.id),
        "interview_id": transcribed_interview_id,
        "transcribed_interview_id": transcribed_interview_id,
    }


async def enqueue_topup_to_full(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_vacancy_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> dict:
    """Run the full analysis at the top-up price (20 cr) and archive the
    prior resume-only run on success.

    Implementation note: the heavy lifting (LLM call, AIAssessment
    writes, interview.analysis_data) is delegated to the existing
    ``analyze_interview_task``. This wrapper:

    * pre-validates eligibility,
    * creates the ``AIAnalysisRun`` (mode='full') row with
      ``supersedes_id`` pointing at the prior resume-only run,
    * marks the prior run archived AFTER the Celery task succeeds
      (see ``finalize_topup_after_full_analysis`` below — wired into
      the analyze task's success branch).

    The 20-cr precheck + consume is provided by the ``ee/billing.py``
    BILLABLE entry on this function (see ``recruitment.analyze_topup_to_full``).
    """

    from app.modules.recruitment.tasks import analyze_interview_task

    eligibility = await evaluate_topup_eligibility(
        db, tenant_id, candidate_vacancy_id
    )
    if not eligibility.get("eligible"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "reason": eligibility.get("reason", "ineligible"),
                "detail": eligibility,
            },
        )

    cv = await _get_cv_or_404(db, tenant_id, candidate_vacancy_id)

    await _acquire_cv_lock(db, cv.id)

    # Re-evaluate after lock: a sibling top-up may have committed in
    # between, or a concurrent resume-only may have flipped the active
    # run.
    if await _pending_run(db, tenant_id, candidate_vacancy_id):
        raise AppError(
            "analysis_already_in_progress", status.HTTP_409_CONFLICT
        )

    interview_id = uuid.UUID(eligibility["interview_id"])
    interview = await db.scalar(
        select(Interview).where(
            Interview.id == interview_id,
            Interview.tenant_id == tenant_id,
        )
    )
    if interview is None:
        raise AppError(
            "interview_vanished_between_checks", status.HTTP_409_CONFLICT
        )

    if interview.analysis_status == "processing":
        raise AppError(
            "analysis_already_in_progress", status.HTTP_409_CONFLICT
        )

    prior_run_id = uuid.UUID(eligibility["active_run_id"])
    profile = await _vacancy_profile(db, tenant_id, cv.vacancy_id)

    run = AIAnalysisRun(
        tenant_id=tenant_id,
        candidate_vacancy_id=cv.id,
        mode="full",
        status="pending",
        interview_id=interview.id,
        vacancy_profile_id=profile.id if profile else None,
        vacancy_profile_version=profile.version if profile else None,
        supersedes_id=prior_run_id,
        created_by_id=actor_user_id,
        analysis_data={},
    )
    db.add(run)
    interview.analysis_status = "processing"
    interview.analysis_error = None
    cv.ai_readiness = "resume_and_transcript"
    await db.commit()

    # Dispatch after commit (see ``enqueue_resume_only_analysis``).
    task = analyze_interview_task.delay(str(interview.id), str(tenant_id))

    # HRP-270: stash the Celery id on the run row so the cancel
    # endpoint can revoke this task (mirrors the resume-only path).
    run.celery_task_id = task.id
    await db.commit()

    return {
        "task_id": task.id,
        "run_id": str(run.id),
        "supersedes_id": str(prior_run_id),
        "status": "queued",
    }


# ---------------------------------------------------------------------------
# Cancel an in-flight analysis (HRP-270)
# ---------------------------------------------------------------------------


async def cancel_ai_analysis_run(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
) -> dict:
    """Mark a pending/processing AIAnalysisRun cancelled.

    Revokes the Celery task (best effort), refunds 100% of the
    credit cost iff the run never reached the first LLM-spending
    stage, and writes an ``ai.analyze_cancelled`` audit entry. 409s
    if the run is already in a terminal state.
    """
    from datetime import UTC, datetime

    from app.modules.recruitment.ai_analysis_stages import (
        is_pre_llm,
    )
    from app.modules.recruitment.models import (
        AIAnalysisRun,
        Interview,
    )

    run = await db.scalar(
        select(AIAnalysisRun)
        .where(
            AIAnalysisRun.id == run_id,
            AIAnalysisRun.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if run is None:
        raise AppError("analysis_run_not_found", status.HTTP_404_NOT_FOUND)
    if run.status not in ("pending", "processing"):
        raise AppError(
            "analysis_already_terminal",
            status.HTTP_409_CONFLICT,
            run_status=run.status,
        )

    # Best-effort Celery revoke — the worker also re-reads the row at
    # start of each stage and bails out if it sees ``status='cancelled'``,
    # so missing the revoke is not a correctness issue.
    if run.celery_task_id:
        try:
            from app.core.celery_app import celery

            celery.control.revoke(run.celery_task_id, terminate=True)
        except Exception:  # noqa: BLE001
            logger.exception(
                "cancel: celery revoke failed for run %s task %s",
                run.id,
                run.celery_task_id,
            )

    refund_eligible = is_pre_llm(run.current_stage)

    now = datetime.now(UTC)
    run.status = "cancelled"
    run.cancelled_at = now
    run.cancelled_by_id = actor_user_id

    # Resume-only writes ``cv.ai_readiness='resume_only'`` on enqueue;
    # top-up sets ``resume_and_transcript``. The cancel should not
    # leave that mirror advertising work that never landed — but it
    # also must not erase a prior completed run's readiness. Look up
    # the latest still-completed run for the same cv and roll the
    # readiness back to that snapshot (or ``pending`` if none).
    from app.modules.recruitment.models import AIAnalysisRun, CandidateVacancy

    cv = await db.get(CandidateVacancy, run.candidate_vacancy_id)
    if cv is not None and run.mode in ("resume_only", "full"):
        prior_active = await db.scalar(
            select(AIAnalysisRun)
            .where(
                AIAnalysisRun.tenant_id == tenant_id,
                AIAnalysisRun.candidate_vacancy_id == cv.id,
                AIAnalysisRun.id != run.id,
                AIAnalysisRun.status == "completed",
                AIAnalysisRun.archived_at.is_(None),
            )
            .order_by(AIAnalysisRun.created_at.desc())
            .limit(1)
        )
        if prior_active is None:
            cv.ai_readiness = "pending"
        elif prior_active.mode == "full":
            cv.ai_readiness = "resume_and_transcript"
        else:
            cv.ai_readiness = "resume_only"

    # Top-up case: the Interview row was flipped to
    # ``analysis_status='processing'`` at enqueue. Reset it so a
    # subsequent /analyze can re-enqueue without hitting the
    # in-flight guard.
    if run.interview_id is not None:
        interview = await db.get(Interview, run.interview_id)
        if interview is not None and interview.analysis_status == "processing":
            interview.analysis_status = "not_started"

    refund_amount = 0.0
    if refund_eligible:
        # Soft-import: community builds have no ``ee/`` and no credit
        # engine, so the cancel path simply skips the refund step.
        try:
            from ee.credits import refund_credits, resolve_cost
        except ImportError:
            refund_credits = None  # type: ignore[assignment]
            resolve_cost = None  # type: ignore[assignment]

        if refund_credits is not None and resolve_cost is not None:
            # Map this run to the billing *action* it consumed; the credit
            # amount itself is owned by ``ee/credits.yaml`` and resolved via
            # ``resolve_cost`` (multiplier-aware), never hardcoded in core.
            sub_kind = "topup" if run.supersedes_id is not None else None
            action_by_run = {
                ("resume_only", None): "recruitment.analyze_resume_only",
                ("full", "topup"): "recruitment.analyze_topup_to_full",
                ("full", None): "recruitment.analyze_interview",
            }
            action = action_by_run.get((run.mode, sub_kind))
            if action is not None:
                refund_amount = await resolve_cost(db, tenant_id, action)
                if refund_amount > 0:
                    await refund_credits(
                        db,
                        tenant_id,
                        actor_user_id,
                        action,
                        refund_amount,
                        entity_type="ai_analysis_run",
                        entity_id=run.id,
                    )

    await db.commit()
    return {
        "run_id": str(run.id),
        "status": "cancelled",
        "refunded": refund_amount,
        "refund_eligible": refund_eligible,
    }


# ---------------------------------------------------------------------------
# Bulk resume-only across a vacancy
# ---------------------------------------------------------------------------


async def enqueue_bulk_resume_only(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    candidate_vacancy_ids: list[uuid.UUID],
    actor_user_id: uuid.UUID | None = None,
) -> dict:
    """Fan-out resume-only analysis across a recruiter selection.

    Each pair goes through ``enqueue_resume_only_analysis`` so the
    eligibility checks (parsed resume present, profile present, no
    in-flight run) and the per-call ``AIAnalysisRun`` creation stay
    in one place. Per-row failures are collected and returned to the
    caller — partial batches are normal (e.g. one resume not yet
    parsed).

    The 20-cr per-item charge is enforced at the BILLABLE wrapper
    level via ``_bulk_cv_cost`` in ``ee/billing.py`` — the wrapper
    multiplies the unit price by ``len(candidate_vacancy_ids)`` and
    debits once before the fan-out. Per-row failures DO NOT refund
    individual items (would require a partial-commit credit ledger
    redesign); the recruiter sees ``failed`` rows in the response and
    can retry once the input is fixed.
    """

    # Validate the vacancy exists (guards against rogue ids across
    # tenants — the per-cv check below catches the rest).
    vacancy = await db.scalar(
        select(Vacancy).where(
            Vacancy.id == vacancy_id, Vacancy.tenant_id == tenant_id
        )
    )
    if vacancy is None:
        raise AppError("vacancy_not_found", status.HTTP_404_NOT_FOUND)

    if not candidate_vacancy_ids:
        raise AppError("no_candidates_selected", status.HTTP_400_BAD_REQUEST)

    queued: list[dict] = []
    failed: list[dict] = []
    for cv_id in candidate_vacancy_ids:
        try:
            # Call the unbilled inner worker — the bulk wrapper has
            # already debited N × 20 cr at the ``ee/billing.py`` layer.
            # Going through the wrapped public ``enqueue_resume_only_analysis``
            # here would double-charge every row.
            res = await _enqueue_resume_only_unbilled(
                db, tenant_id, cv_id, actor_user_id
            )
            queued.append({"candidate_vacancy_id": str(cv_id), **res})
        except HTTPException as exc:
            # F3: per-row eligibility failures are reported inside a 200
            # response body, not raised — the exception never reaches the
            # locale-aware handler in ``main.py``. AppError is caught here
            # too (it subclasses HTTPException) with ``detail`` pre-rendered
            # from the en catalog, keeping ``BulkAnalyzeFailedRow.error``
            # byte-identical to the pre-i18n behaviour.
            failed.append(
                {
                    "candidate_vacancy_id": str(cv_id),
                    "error": str(exc.detail),
                    "status_code": exc.status_code,
                }
            )
        except Exception as exc:  # noqa: BLE001
            # Broker / DB hiccup mid-loop — surface as a per-row
            # failure so the wrapper response stays well-formed
            # instead of bubbling a 500 that swallows the partial
            # progress on items 0..i-1.
            logger.exception("bulk row %s failed", cv_id)
            failed.append(
                {
                    "candidate_vacancy_id": str(cv_id),
                    "error": str(exc)[:200],
                    "status_code": 500,
                }
            )

    return {"queued": queued, "failed": failed}


# ---------------------------------------------------------------------------
# History + activation helpers
# ---------------------------------------------------------------------------


async def list_runs_for_cv(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_vacancy_id: uuid.UUID,
) -> list[AIAnalysisRun]:
    await _get_cv_or_404(db, tenant_id, candidate_vacancy_id)
    rows = await db.scalars(
        select(AIAnalysisRun)
        .where(
            AIAnalysisRun.tenant_id == tenant_id,
            AIAnalysisRun.candidate_vacancy_id == candidate_vacancy_id,
        )
        .order_by(AIAnalysisRun.created_at.desc())
    )
    return list(rows)


_RESUME_EXCERPT_SECTIONS = frozenset(
    {"experience", "education", "skills", "projects", "summary"}
)


def extract_resume_excerpts(run: AIAnalysisRun) -> list[dict[str, Any]]:
    """HRP-271 — pull verbatim resume citations off ``analysis_data``.

    Returns ``[]`` for full-mode runs or when the payload is missing /
    malformed. Each item is the raw ``ResumeExcerpt`` shape (section,
    excerpt_text, source_company, source_period). Unknown sections are
    dropped so a future prompt regression cannot widen the public union.
    """

    if run.mode != "resume_only":
        return []
    data = run.analysis_data
    if not isinstance(data, dict):
        return []
    out: list[dict[str, Any]] = []
    for assessment in data.get("competence_assessments") or []:
        if not isinstance(assessment, dict):
            continue
        for excerpt in assessment.get("resume_excerpts") or []:
            if not isinstance(excerpt, dict):
                continue
            section = excerpt.get("section")
            text = excerpt.get("excerpt_text")
            if section not in _RESUME_EXCERPT_SECTIONS or not isinstance(text, str):
                continue
            if not text.strip():
                continue
            out.append(
                {
                    "section": section,
                    "excerpt_text": text,
                    "source_company": excerpt.get("source_company"),
                    "source_period": excerpt.get("source_period"),
                }
            )
    return out


def serialize_run_for_read(
    run: AIAnalysisRun,
    current_resume_hash: str | None = None,
) -> AIAnalysisRunRead:
    """HRP-271 — ORM → ``AIAnalysisRunRead`` with extracted excerpts.

    Kept in the service so the router stays a thin pass-through and the
    raw ``analysis_data`` blob never reaches a response model.

    HRP-272 — when ``current_resume_hash`` is supplied AND the run has a
    stored ``resume_snapshot_hash`` AND they differ, ``resume_outdated``
    flips on so the UI can surface a "Resume updated — re-analyze"
    banner. Either hash being NULL (legacy run / no parsed resume) keeps
    outdated at ``False`` — we never claim outdated when we cannot prove
    it.
    """

    read = AIAnalysisRunRead.model_validate(run)
    raw_excerpts = extract_resume_excerpts(run)
    if raw_excerpts:
        read.resume_excerpts = [ResumeExcerptRead(**e) for e in raw_excerpts]
    # Review #6 (HRP-272): symmetric write so a future Pydantic
    # strict-mode flip or a future ORM column property carrying a
    # stale True cannot leak through — the serializer is the single
    # source of truth for this flag.
    stored = run.resume_snapshot_hash
    read.resume_outdated = (
        run.mode == "resume_only"
        and stored is not None
        and current_resume_hash is not None
        and stored != current_resume_hash
    )
    return read


def apply_resume_only_verdict_guard(
    verdict: str | None,
) -> tuple[str, bool]:
    """Resume-only mode MUST NOT return 'recommended'. The prompt forbids
    it explicitly but the LLM occasionally regresses — this validator
    rewrites the verdict and returns ``(final_verdict, was_overridden)``
    so the task can stamp an audit-log entry.
    """
    if verdict == "recommended":
        return "needs_check", True
    if verdict in {"needs_check", "not_recommended"}:
        return verdict, False
    return "needs_check", verdict is not None


async def finalize_topup_after_full_analysis(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
) -> None:
    """Mark the prior resume-only run archived after a full analysis
    that was kicked off via the top-up flow succeeded.

    Called from the success branch of ``analyze_interview_task``. The
    full run we created in ``enqueue_topup_to_full`` is identified by
    ``mode='full'`` + ``supersedes_id IS NOT NULL`` + matching
    interview_id; if no such row exists (regular full analysis from
    the interview page), this is a no-op.
    """

    full_run = await db.scalar(
        select(AIAnalysisRun)
        .where(
            AIAnalysisRun.tenant_id == tenant_id,
            AIAnalysisRun.interview_id == interview_id,
            AIAnalysisRun.mode == "full",
            AIAnalysisRun.supersedes_id.is_not(None),
            AIAnalysisRun.status == "pending",
        )
        .order_by(AIAnalysisRun.created_at.desc())
        .limit(1)
    )
    if full_run is None:
        return

    prior = await db.scalar(
        select(AIAnalysisRun).where(
            AIAnalysisRun.id == full_run.supersedes_id,
            AIAnalysisRun.tenant_id == tenant_id,
        )
    )
    if prior is not None and prior.archived_at is None:
        prior.archived_at = datetime.now(UTC)
        prior.replaced_by_id = full_run.id
    await db.flush()


__all__ = [
    "TOPUP_WINDOW_DAYS",
    "apply_resume_only_verdict_guard",
    "cancel_ai_analysis_run",
    "current_resume_hash_for_candidate",
    "current_resume_hash_for_cv",
    "enqueue_bulk_resume_only",
    "enqueue_resume_only_analysis",
    "enqueue_topup_to_full",
    "evaluate_topup_eligibility",
    "extract_resume_excerpts",
    "finalize_topup_after_full_analysis",
    "list_runs_for_cv",
    "serialize_run_for_read",
]
