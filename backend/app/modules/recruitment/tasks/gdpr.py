"""GDPR export worker task.

Split from the former recruitment/tasks.py monolith (project-review #20).
Task names are pinned to the pre-split ``app.modules.recruitment.tasks.*``
namespace -- they are a public contract (beat schedule, queued messages,
the task_failure status map).
"""

import logging
import uuid as _uuid

from app.core.celery_app import celery

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HRP-review #44 — GDPR export offloaded off the request thread
# ---------------------------------------------------------------------------


@celery.task(
    bind=True, max_retries=0, name="app.modules.recruitment.tasks.run_gdpr_export_task"
)
def run_gdpr_export_task(self, request_id: str) -> dict:
    """Gather + serialise + upload one GDPR export request.

    ``gdpr_service.gdpr_export`` persists the ``processing`` row and dispatches
    this task; the body runs the async gather logic on a short-lived worker
    engine and flips the row to ``completed``/``failed``.
    """

    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import settings
    from app.database import make_async_engine
    from app.modules.recruitment.gdpr_service import _perform_gdpr_export

    async def _inner() -> dict:
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
                return await _perform_gdpr_export(db, _uuid.UUID(request_id))
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_inner()) or {}
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_gdpr_export_task failed for %s", request_id)
        return {"status": "error", "error": str(exc)[:200]}
