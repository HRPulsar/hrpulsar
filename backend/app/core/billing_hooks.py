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
    from sqlalchemy.ext.asyncio import AsyncSession


async def precheck_action(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    action: str,
    *,
    amount_override: float | None = None,
) -> None:
    """No-op precheck. Overridden by `ee.billing.register_billing()` in SaaS."""
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
