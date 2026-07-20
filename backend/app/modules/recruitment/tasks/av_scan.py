"""Antivirus scan of uploaded interview media (EE scanner, community no-op).

Split from the former recruitment/tasks.py monolith (project-review #20).
Task names are pinned to the pre-split ``app.modules.recruitment.tasks.*``
namespace -- they are a public contract (beat schedule, queued messages,
the task_failure status map).
"""

import logging
from datetime import datetime, timezone

from app.core.celery_app import celery

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HRP-202: antivirus scan (pluggable, ClamAV-shaped stub by default)
# ---------------------------------------------------------------------------


def _av_scan_bytes(path: str) -> str:
    """Pluggable AV verdict — defaults to ``clean`` when no scanner runs.

    The stub keeps the pipeline functional in self-hosted / dev where
    ClamAV is not running. Tenants on the SaaS plan get a real scanner
    wired here; the verdict vocabulary is fixed (``clean`` / ``infected``
    / ``skipped`` / ``error``) so the rest of the code can treat any
    backend uniformly.
    """

    from app.config import settings

    if not getattr(settings, "antivirus_enabled", False):
        return "skipped"
    # Real ClamAV / S3-Object-Lambda integration lives in ``ee/`` per
    # tenant configuration. The Celery task imports lazily so the
    # community build doesn't pay the dependency cost.
    try:
        from ee.antivirus import scan_s3_object  # type: ignore[import-not-found]

        verdict = scan_s3_object(path)
        if verdict not in {"clean", "infected", "skipped", "error"}:
            return "error"
        return verdict
    except ImportError:
        return "skipped"
    except Exception:
        logger.exception("AV scan failed for %s", path)
        return "error"


@celery.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="app.modules.recruitment.tasks.scan_interview_media_task",
)
def scan_interview_media_task(self, interview_id: str, tenant_id: str) -> dict:
    """Run an antivirus pass on the uploaded interview media.

    Writes the verdict back via ``record_av_scan_result`` (sync wrapper)
    so an ``infected`` finding deletes the S3 object and flips the
    interview into ``upload_failed``.
    """

    import uuid

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.modules.recruitment.models import Interview

    iv_uuid = uuid.UUID(interview_id)
    tenant_uuid = uuid.UUID(tenant_id)
    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    try:
        with Session(engine) as db:
            interview = db.execute(
                select(Interview).where(
                    Interview.id == iv_uuid,
                    Interview.tenant_id == tenant_uuid,
                )
            ).scalar_one_or_none()
            if interview is None:
                return {"status": "missing"}
            if not interview.file_s3_key:
                interview.av_status = "skipped"
                interview.av_scanned_at = datetime.now(timezone.utc)
                db.commit()
                return {"status": "no_file"}

            verdict = _av_scan_bytes(interview.file_s3_key)
            interview.av_status = verdict
            interview.av_scanned_at = datetime.now(timezone.utc)
            if verdict == "infected":
                from app.core.s3 import delete_file

                try:
                    delete_file(interview.file_s3_key)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Could not delete infected file %s",
                        interview.file_s3_key,
                    )
                interview.audio_file_id = None
                interview.video_file_id = None
                interview.transcript_file_id = None
                interview.file_s3_key = None
                interview.status = "upload_failed"
            db.commit()

            # HRP-202 REDO: auto-processing starts HERE, not on upload
            # completion — the media must be scanned (or the scan
            # explicitly skipped) before it is handed to the external ASR
            # provider. On any refusal (e.g. 402 insufficient credits) the
            # flag is dropped so the UI falls back to the manual buttons.
            if (
                verdict in {"clean", "skipped"}
                and interview.auto_process
                and (interview.audio_file_id or interview.video_file_id)
            ):
                from app.modules.recruitment.tasks.analysis import (
                    auto_chain_step,
                )

                if not auto_chain_step(interview_id, tenant_id, "transcribe"):
                    interview.auto_process = False
                    db.commit()

            return {"status": "ok", "verdict": verdict}
    except Exception as exc:  # noqa: BLE001
        logger.exception("scan_interview_media_task failed")
        return {"status": "error", "error": str(exc)[:200]}
    finally:
        engine.dispose()
