"""Celery side of the competence → primitive mapping (HRP-750).

One task, no session row: acceptance is internal (§3.4), so there is no UI
to feed and nothing to reap. The task is enqueued by the internal endpoint
and, later, by the first coverage computation that finds unmapped or stale
competences (§3.3, W4).
"""

from __future__ import annotations

import json
import logging
import uuid

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.celery_app import celery
from app.modules.ai.tasks import _run_with_async_session
from app.modules.primitives import mapping_service

logger = logging.getLogger(__name__)


@celery.task(bind=True, max_retries=1, default_retry_delay=10)
def map_competences_task(
    self,
    tenant_id: str,
    competence_ids: list[str] | None = None,
    force: bool = False,
    include_origin: bool = False,
) -> dict[str, int]:
    # ``include_origin`` is opt-in: only coverage passes True, for the origin
    # competences its own grade matrices reference. Ids out of a request
    # body (the internal endpoint) must not aim a run at a row every tenant
    # reads.
    # Batches already committed carry PROMPT_VERSION and are kept on retry,
    # so only the remainder is re-sent — provided ``force`` is not repeated.
    force = force and self.request.retries == 0

    async def _run(session_factory: async_sessionmaker[AsyncSession]) -> dict:
        async with session_factory() as db:
            result = await mapping_service.map_competences(
                db,
                uuid.UUID(tenant_id),
                [uuid.UUID(c) for c in competence_ids] if competence_ids else None,
                force=force,
                include_origin=include_origin,
            )
        # The run is over: free the coverage slot now, so the screen's
        # "pending" ends here and not with the ten-minute window.
        try:
            await mapping_service.release_mapping_slot(tenant_id)
        except Exception:  # noqa: BLE001 - the key expires on its own
            logger.warning(
                "primitive mapping: coverage lock not released", exc_info=True
            )
        return result.as_dict()

    try:
        return _run_with_async_session(_run)
    except json.JSONDecodeError as exc:
        # Not a schema problem: the answer stopped mid-JSON. A provider that
        # reports the max_tokens stop reason raises LLMOutputTruncatedError,
        # one that does not lands here - both are worth the single retry,
        # which re-sends only the batches that never committed.
        logger.exception("primitive mapping: model output was not valid JSON")
        raise self.retry(exc=exc)
    except ValidationError:
        # Deterministic for a given prompt: a retry would pay for the same
        # answer. The schema is lenient, so this means the JSON shape itself
        # is off.
        logger.exception("primitive mapping: model output failed validation")
        raise
    except Exception as exc:  # noqa: BLE001 — provider/network errors retry once
        logger.exception("primitive mapping failed, retrying once")
        raise self.retry(exc=exc)
