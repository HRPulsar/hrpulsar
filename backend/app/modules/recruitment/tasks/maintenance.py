"""Periodic cleanup sweepers and the task_failure signal handler.

Split from the former recruitment/tasks.py monolith (project-review #20).
Task names are pinned to the pre-split ``app.modules.recruitment.tasks.*``
namespace -- they are a public contract (beat schedule, queued messages,
the task_failure status map).
"""

import logging
from datetime import datetime, timedelta, timezone

from celery.signals import task_failure

from app.core.celery_app import celery

logger = logging.getLogger(__name__)


# Recruitment Celery task names → (model_class, status_field, error_field).
# task_failure handler walks this mapping to reset stuck rows when a task
# raises; cleanup_stuck_recruitment_tasks_task does the same for kill-9
# style failures where signals never fired (R3b H-3).
_RECRUITMENT_STATUS_MAP: dict[str, tuple[str, str, str | None]] = {
    "app.modules.recruitment.tasks.transcribe_interview_task": (
        "Interview",
        "transcription_status",
        "transcription_error",
    ),
    "app.modules.recruitment.tasks.analyze_interview_task": (
        "Interview",
        "analysis_status",
        "analysis_error",
    ),
    "app.modules.recruitment.tasks.analyze_resume_only_task": (
        "AIAnalysisRun",
        "status",
        "error_message",
    ),
    "app.modules.recruitment.tasks.generate_report_task": (
        "ConsolidatedReport",
        "status",
        "error",
    ),
    "app.modules.recruitment.tasks.parse_resume_task": (
        "CandidateFile",
        "parse_status",
        None,
    ),
}


# Stuck-row threshold for the periodic sweeper. The current recruitment
# tasks finish well under this:
#   - transcribe: capped at httpx 600s (Whisper) plus PII redaction
#   - analyze:    one LLM call, ~30–90 s
#   - parse_resume / generate_report: seconds
# The sweeper compares against ``updated_at``, which only bumps at the
# task's start commit (status=processing) and final commit (status=
# completed/failed) — none of the tasks write intermediate progress —
# so a row that's genuinely "still running" stays inside the window
# until it finishes. 30 min keeps a generous safety margin over the
# 10-min Whisper ceiling so a near-boundary success isn't killed by
# this sweeper before its own commit lands.
_STUCK_AGE_MINUTES = 30


# ---------------------------------------------------------------------------
# H-3 — stuck `processing` recovery (R3b leftover)
# ---------------------------------------------------------------------------


@celery.task(
    bind=True,
    max_retries=0,
    name="app.modules.recruitment.tasks.cleanup_stuck_recruitment_tasks_task",
)
def cleanup_stuck_recruitment_tasks_task(self) -> dict:
    """Reset recruitment rows stuck in ``processing`` past the threshold.

    Covers the kill -9 / OOM path where the task crashes without a
    chance to update its row. The task_failure signal handler covers
    the regular exception path; this beat job is the safety net.
    """

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.modules.recruitment.models import (
        AIAnalysisRun,
        CandidateFile,
        ConsolidatedReport,
        Interview,
    )

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_STUCK_AGE_MINUTES)
    reset = {
        "interviews_transcription": 0,
        "interviews_analysis": 0,
        "reports": 0,
        "resumes": 0,
        "ai_analysis_runs": 0,
    }

    try:
        with Session(engine) as db:
            iv_rows = (
                db.execute(
                    select(Interview).where(
                        Interview.transcription_status == "processing",
                        Interview.updated_at < cutoff,
                    )
                )
                .scalars()
                .all()
            )
            for row in iv_rows:
                row.transcription_status = "failed"
                row.transcription_error = (
                    "Transcription worker did not finish within "
                    f"{_STUCK_AGE_MINUTES} minutes; resetting to failed"
                )
                reset["interviews_transcription"] += 1

            iv_rows = (
                db.execute(
                    select(Interview).where(
                        Interview.analysis_status == "processing",
                        Interview.updated_at < cutoff,
                    )
                )
                .scalars()
                .all()
            )
            for row in iv_rows:
                row.analysis_status = "failed"
                row.analysis_error = (
                    "Analysis worker did not finish within "
                    f"{_STUCK_AGE_MINUTES} minutes; resetting to failed"
                )
                reset["interviews_analysis"] += 1

            rep_rows = (
                db.execute(
                    select(ConsolidatedReport).where(
                        ConsolidatedReport.status == "processing",
                        ConsolidatedReport.updated_at < cutoff,
                    )
                )
                .scalars()
                .all()
            )
            for rep_row in rep_rows:
                rep_row.status = "failed"
                rep_row.error = (
                    "Report worker did not finish within "
                    f"{_STUCK_AGE_MINUTES} minutes; resetting to failed"
                )
                reset["reports"] += 1

            res_rows = (
                db.execute(
                    select(CandidateFile).where(
                        CandidateFile.parse_status == "processing",
                        CandidateFile.updated_at < cutoff,
                    )
                )
                .scalars()
                .all()
            )
            for res_row in res_rows:
                res_row.parse_status = "failed"
                reset["resumes"] += 1

            # HRP-204: sweep stuck resume-only AI analysis runs.
            # ``analyze_resume_only_task`` flips status to ``failed``
            # in its own except block; this sweeper is the kill-9
            # safety net.
            ai_rows = (
                db.execute(
                    select(AIAnalysisRun).where(
                        AIAnalysisRun.status.in_(("pending", "processing")),
                        AIAnalysisRun.updated_at < cutoff,
                    )
                )
                .scalars()
                .all()
            )
            for ai_row in ai_rows:
                ai_row.status = "failed"
                ai_row.error_message = (
                    "Worker did not finish within "
                    f"{_STUCK_AGE_MINUTES} minutes; resetting to failed"
                )
                reset["ai_analysis_runs"] += 1

            db.commit()
        return {"status": "ok", **reset}
    except Exception as exc:  # noqa: BLE001
        logger.exception("cleanup_stuck_recruitment_tasks_task failed")
        return {"status": "error", "error": str(exc)[:200]}
    finally:
        engine.dispose()


@celery.task(
    bind=True,
    max_retries=0,
    name="app.modules.recruitment.tasks.cleanup_orphan_upload_sessions_task",
)
def cleanup_orphan_upload_sessions_task(self) -> dict:
    """HRP-202: abort upload sessions older than 24h.

    Walks ``upload_sessions`` for status='active' rows past their
    ``expires_at``, aborts the S3 multipart and marks the row
    ``expired``. Intended to run hourly from celery beat.
    """

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.modules.recruitment.models import UploadSession

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    aborted = 0
    try:
        with Session(engine) as db:
            cutoff = datetime.now(timezone.utc)
            rows = (
                db.execute(
                    select(UploadSession).where(
                        UploadSession.status == "active",
                        UploadSession.expires_at <= cutoff,
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                from app.core.s3 import abort_multipart_upload

                try:
                    abort_multipart_upload(row.s3_key, row.s3_upload_id)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Could not abort orphan multipart upload %s", row.id
                    )
                row.status = "expired"
                aborted += 1
            if aborted:
                db.commit()
        return {"status": "ok", "aborted": aborted}
    except Exception as exc:  # noqa: BLE001
        logger.exception("cleanup_orphan_upload_sessions_task failed")
        return {"status": "error", "error": str(exc)[:200]}
    finally:
        engine.dispose()


@celery.task(
    bind=True,
    max_retries=0,
    name="app.modules.recruitment.tasks.purge_archived_interviews_task",
)
def purge_archived_interviews_task(self) -> dict:
    """HRP-418: drop the media of interviews archived past the 90-day window.

    Metadata survives for audit — only the object-storage blob and the
    file pointers go, which is also what makes the interview permanently
    unrestorable. Intended to run daily from celery beat.
    """

    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import settings
    from app.database import make_async_engine
    from app.modules.recruitment.interview_service import (
        purge_expired_archived_interviews,
    )

    async def _inner() -> int:
        engine = make_async_engine(
            settings.database_url,
            pool_size=2,
            max_overflow=2,
            pool_recycle=300,
            pool_pre_ping=True,
        )
        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            async with session_factory() as db:
                return await purge_expired_archived_interviews(db)
        finally:
            await engine.dispose()

    try:
        return {"status": "ok", "purged": asyncio.run(_inner())}
    except Exception as exc:  # noqa: BLE001
        logger.exception("purge_archived_interviews_task failed")
        return {"status": "error", "error": str(exc)[:200]}


# ---------------------------------------------------------------------------
# HRP-181 REDO Stage 3 — detached resume retention
# ---------------------------------------------------------------------------


# Detached CandidateFile rows are bulk-upload byproducts the user never
# finalised. 7 days is a generous window — long enough for a recruiter
# to come back after the weekend, short enough to keep the parser
# pipeline from accumulating orphaned S3 objects.
_DETACHED_RESUME_RETENTION_DAYS = 7


@celery.task(
    bind=True,
    max_retries=0,
    name="app.modules.recruitment.tasks.cleanup_detached_resume_files_task",
)
def cleanup_detached_resume_files_task(self) -> dict:
    """Sweep detached resume CandidateFile rows older than the retention
    window. Deletes the S3 object first (best-effort), then drops the row.
    """

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.core.s3 import delete_file
    from app.modules.recruitment.models import CandidateFile
    from app.modules.storage.models import File

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=_DETACHED_RESUME_RETENTION_DAYS
    )
    removed = 0

    try:
        with Session(engine) as db:
            rows = (
                db.execute(
                    select(CandidateFile).where(
                        CandidateFile.candidate_id.is_(None),
                        CandidateFile.file_type == "resume",
                        CandidateFile.created_at < cutoff,
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                if row.file_id is not None:
                    file_record = db.get(File, row.file_id)
                    if file_record is not None:
                        try:
                            delete_file(file_record.path)
                        except Exception:  # noqa: BLE001
                            logger.exception(
                                "Could not delete S3 object for detached "
                                "CandidateFile %s",
                                row.id,
                            )
                        db.delete(file_record)
                db.delete(row)
                removed += 1
            if removed:
                db.commit()
        return {"status": "ok", "removed": removed}
    except Exception as exc:  # noqa: BLE001
        logger.exception("cleanup_detached_resume_files_task failed")
        return {"status": "error", "error": str(exc)[:200]}
    finally:
        engine.dispose()


@task_failure.connect
def _on_recruitment_task_failure(
    sender=None,
    task_id=None,
    exception=None,
    **_,
) -> None:
    """Reset the row a failing recruitment task was working on.

    Without this, a worker exception leaves the row stuck in
    ``processing`` and the `409 already in progress` guard prevents
    the user from retrying. We hop into a fresh sync session — the
    task's own session is gone by the time this signal fires.
    """

    if sender is None:
        return
    name = getattr(sender, "name", None)
    if name not in _RECRUITMENT_STATUS_MAP:
        return

    request = getattr(sender, "request", None)
    args = getattr(request, "args", None) or ()
    if not args:
        return
    raw_id = args[0]
    try:
        import uuid

        row_id = uuid.UUID(str(raw_id))
    except (TypeError, ValueError):
        return

    model_name, status_field, error_field = _RECRUITMENT_STATUS_MAP[name]

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.modules.recruitment.models import (
        AIAnalysisRun,
        CandidateFile,
        ConsolidatedReport,
        Interview,
    )

    model_lookup = {
        "Interview": Interview,
        "ConsolidatedReport": ConsolidatedReport,
        "CandidateFile": CandidateFile,
        # HRP-204: resume-only runs land here when ``analyze_resume_only_task``
        # raises past max_retries. Without the mapping, model_cls is
        # None and the stuck ``processing`` row would block any
        # subsequent enqueue with a 409.
        "AIAnalysisRun": AIAnalysisRun,
    }
    model_cls = model_lookup.get(model_name)
    if model_cls is None:
        return

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    try:
        with Session(engine) as db:
            row = db.get(model_cls, row_id)
            if row is None:
                return
            current = getattr(row, status_field, None)

            # Reset stuck row only if it's still in ``processing`` —
            # transcribe / analyze tasks already flip to ``failed`` in
            # their own except block before ``self.retry``. By the time
            # this signal fires (retries exhausted) the row is usually
            # ``failed`` already.
            if current == "processing":
                setattr(row, status_field, "failed")
                if error_field:
                    setattr(
                        row,
                        error_field,
                        str(exception)[:1000] if exception else "task failed",
                    )
                db.commit()

            # R4c N-AI: notify tenant admins on final task failure. Runs
            # regardless of row state — ``task_failure`` only fires after
            # retries are exhausted, so this is exactly the moment the
            # user should learn the pipeline gave up.
            tenant_uuid = getattr(row, "tenant_id", None)
            if tenant_uuid is not None:
                try:
                    from app.modules.recruitment.notifications import notify_sync

                    notify_sync(
                        db,
                        event="recruitment.ai.task_failed",
                        tenant_id=tenant_uuid,
                        recipient_ids=[],
                        fallback_admins=True,
                        context={
                            "task_type": name.rsplit(".", 1)[-1],
                            "entity_id": str(row_id),
                            "error": (
                                str(exception)[:200] if exception else "task failed"
                            ),
                        },
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "ai_task_failed notification failed for %s", row_id
                    )
    except Exception:  # noqa: BLE001
        logger.exception(
            "task_failure handler could not reset %s for task %s", name, task_id
        )
    finally:
        engine.dispose()
