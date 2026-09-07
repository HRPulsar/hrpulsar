"""Celery tasks for the talent market module."""

import logging
import uuid

from app.core.celery_app import celery
from app.modules.ai.tasks import _run_with_async_session

logger = logging.getLogger(__name__)


@celery.task
def recompute_card_candidates_task(tenant_id_str: str, card_id_str: str) -> None:
    """HRP-705: rebuild a card's auto-pool outside the HTTP request.

    Named ``_task`` on purpose: ``requirement_service.recompute_card_candidates``
    is a different callable doing the in-request version of this job, and
    ``ee/billing.py`` prices that one. Two bare same-named callables one
    import away from each other is a mix-up waiting to happen.

    The matcher walks the whole roster, so running it inline made a Save
    in the vacancy competence editor wait on a full-roster scan. The
    recompute is post-commit work either way -- the card's requirements
    are already durable when this is queued -- so the request returns and
    the pool catches up. The Internal Candidates block reads the new pool
    on its next fetch (eventual consistency, by design).

    A card deleted between enqueue and run is a no-op: the matcher's own
    tenant check returns early.
    """
    from app.modules.talent_market.matching import _auto_populate_candidates

    tenant_id = uuid.UUID(tenant_id_str)
    card_id = uuid.UUID(card_id_str)

    async def _run(session_factory) -> None:
        async with session_factory() as db:
            # ``_auto_populate_candidates`` commits on its own.
            await _auto_populate_candidates(db, tenant_id, card_id)

    _run_with_async_session(_run)
