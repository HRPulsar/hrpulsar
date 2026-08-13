"""Split-billing hooks for async (Celery-task-driven) billable actions.

Sync mutations are billed by `ee/billing.py::_wrap_with_billing`, which
monkey-patches service functions at startup with a precheck → call → consume
wrapper. That model assumes the entire billable unit runs inside one HTTP
handler.

AI generation breaks that assumption: the LLM call is enqueued to Celery, so
the precheck has to run in the handler (return 402 *before* enqueue, never
charge for a task that never started) and the consume has to run in the
worker (atomic with the row's `status=ready` commit, so a crashed task is
free).

The seam also covers *synchronous* billable units the wrapper cannot see:
when the charge point is not a top-level service call — a token flow that
resolves the tenant mid-function (`recruitment/assessment_service.py`), or a
state flip buried inside a hot autosave endpoint (assessment survey
completion, HRP-322 in `assessment/service.py::record_answer`). Callers
mirror the wrapper's contract: `resolve_cost` once, pass the pinned amount
to both `precheck_action` and `consume_action`.

Rather than letting core modules `from ee.credits import …` on a hot request
path, we define no-op functions here. This is the sanctioned "core no-op seam"
extension mechanism of the open-core architecture: core owns the
no-op contract, and in SaaS `ee.billing.register_billing()` re-binds these to
the real `ee.credits.precheck_credits` / `ee.credits.consume_credits` —
mirroring the same monkey-patch trick used for sync billable functions.

Callers MUST import the **module** (`from app.core import billing_hooks`)
and reference attributes through it — `billing_hooks.precheck_action(...)`.
Importing the names directly (`from app.core.billing_hooks import
precheck_action`) captures a reference to the no-op function at import
time and won't see the later EE rebinding.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import AsyncSession


async def precheck_action(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    action: str,
    *,
    amount_override: float | None = None,
    reserved_entity: tuple[str, uuid.UUID] | None = None,
) -> None:
    """No-op precheck. Overridden by `ee.billing.register_billing()` in SaaS.

    ``reserved_entity`` names the work whose soft reserve this charge is
    settling, so the check does not count the hold that was taken for it
    (HRP-547).
    """
    return None


async def consume_action(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    *,
    amount_override: float | None = None,
) -> None:
    """No-op consume. Overridden by `ee.billing.register_billing()` in SaaS."""
    return None


async def reserve_action(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    ttl: timedelta,
    amount_override: float | None = None,
) -> None:
    """No-op soft reserve. Overridden by `ee.billing.register_billing()`.

    HRP-547: work that takes minutes to finish and is charged at the end
    (a 500 MB interview upload) earmarks its cost when it starts, so the
    tenant is turned away before the transfer rather than after it, and
    the credits it is counting on cannot be spent elsewhere meanwhile.

    Raises the same 402/429 as `precheck_action` when the tenant cannot
    afford the action, so callers keep one failure mode. The hold joins
    the caller's transaction — a start that rolls back leaves none.
    """
    return None


async def release_action(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str | None = None,
) -> int:
    """No-op release. Overridden by `ee.billing.register_billing()` in SaaS.

    Idempotent: every exit path of the reserved work (abort, cleanup) may
    call it without knowing which one got there first. ``action`` narrows
    the release to one kind of hold; without it every hold on the entity
    goes, which is what abandoning the whole thing means.
    """
    return 0


async def release_expired_actions(db: AsyncSession) -> int:
    """No-op expired-hold sweep. Overridden in SaaS.

    Reads already ignore an expired hold, so this frees no balance — it
    stops dead rows from accumulating. Called from the same janitor that
    sweeps the work the holds were taken for.
    """
    return 0


async def resolve_cost(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    action: str,
    *,
    amount_override: float | None = None,
) -> float:
    """Compute the final credit cost (multiplier applied) without charging.

    Used by request handlers that enqueue an async billable task: the
    handler resolves the cost once, passes it to `precheck_action` and to
    the Celery task arguments, and the task forwards it to `consume_action`
    so a tenant flipping AI settings mid-request can't change the price.

    Community-edition no-op returns 0 (handlers still pass it through to
    consume — both sides resolve to the same no-op).
    """
    return amount_override if amount_override is not None else 0.0
