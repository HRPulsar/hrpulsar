"""Celery side of the public check (HRP-922): claim the check, run the
existing decomposition worker on its sandbox run, then freeze the result.
Nothing of the breakdown itself lives here - ``work.tasks.execute_session``
does the model calls, the cache and the error handling exactly as for a
tenant; its run's ``params`` keep it free of charge."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.celery_app import celery
from app.modules.ai.tasks import _run_with_async_session
from app.modules.public_check import service

logger = logging.getLogger(__name__)


async def execute_check(
    session_factory: async_sessionmaker[AsyncSession], check_id: uuid.UUID
) -> dict[str, Any]:
    """Drive one check pending -> ready/error. Separate from the Celery task
    so tests call it with their own session factory."""
    from app.modules.work import tasks as work_tasks

    async with session_factory() as db:
        session_id = await service.claim_check(db, check_id)
    if session_id is not None:
        # Never raises: a failure lands on the run's row as an error code.
        await work_tasks.execute_session(session_factory, session_id)
    # Without the claim this is a redelivery (``acks_late``) of a check a
    # worker took before: the run is not started again, but one that has
    # ended is settled here - else a worker that died after the run would
    # leave the check ``running`` for good. A live run is left alone.
    try:
        async with session_factory() as db:
            status = await service.finish_check(db, check_id)
    except Exception:  # noqa: BLE001 - the check must not stay running
        logger.exception("public check %s: could not freeze the result", check_id)
        async with session_factory() as db:
            await service.fail_check(db, check_id, "service_error")
        status = "error"
    return {"status": status, "check_id": str(check_id)}


@celery.task(bind=True, max_retries=0, name="public_check.run")
def run_check(self, check_id_str: str) -> dict[str, Any]:
    check_id = uuid.UUID(check_id_str)
    return _run_with_async_session(lambda sf: execute_check(sf, check_id))


@celery.task(name="public_check.purge_expired")
def purge_expired() -> dict[str, int]:
    """Daily beat job (HRP-923): expired checks and their sandbox trees."""

    async def _purge(session_factory: async_sessionmaker[AsyncSession]):
        async with session_factory() as db:
            return await service.purge_expired(db)

    result = _run_with_async_session(_purge)
    logger.info("public check purge: %s", result)
    return result
