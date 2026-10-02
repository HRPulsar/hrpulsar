"""AI usage seam: the call context and a no-op call recorder (HRP-964).

Core keeps no journal of model calls; the enterprise edition writes one
row per provider call into ``ai_call_log``. Core owns two things here:

* the *call context* — who is calling the model, for which action and
  object, and which unit of work the call belongs to. A contextvar set by
  the billing wrapper (sync billable actions), by the Celery tasks that
  finish AI work (from the row they load) and by ``celery_signals`` (the
  ``work_unit_id`` a task inherits from the request that enqueued it).
  See docs/plans/AI_USAGE_ACCOUNTING_SPEC.md §4.4.
* ``record_call`` — a no-op that ``ee.ai_usage.register()`` rebinds to
  the real writer. This is the sanctioned "core no-op seam" of the
  open-core architecture (docs/guides/OPEN_CORE.md, mechanism 2).

Callers MUST go through the module::

    from app.core import ai_usage_hooks
    await ai_usage_hooks.record_call(record)

Importing the name directly captures the no-op before the rebind.

Lifetime of a binding: ``call_context`` resets on exit. ``bind`` does
not — it is for Celery task bodies, where ``celery_signals`` binds in
``task_prerun`` and resets that token in ``task_postrun``; a reset to
the prerun token also undoes every ``bind`` the task body made on top.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from typing import Any

UNATTRIBUTED = "unattributed"
WORK_UNIT_HEADER = "ai_work_unit_id"


@dataclass(frozen=True)
class CallContext:
    tenant_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    action: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    work_unit_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CallRecord:
    """What ``llm_client`` knows about one provider call."""

    kind: str  # generate | embedding
    provider: str  # openai | anthropic | gemini | yandex | openai_compatible
    model: str
    credential_source: str  # platform | byok | local
    latency_ms: int
    status: str  # ok | error | truncated
    error_code: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None


_context: ContextVar[CallContext | None] = ContextVar("ai_call_context", default=None)


def current() -> CallContext | None:
    return _context.get()


def bind(**fields: Any) -> Token[CallContext | None]:
    """Merge ``fields`` over the current context; ``None`` never overwrites."""
    base = _context.get() or CallContext()
    merged = replace(base, **{k: v for k, v in fields.items() if v is not None})
    return _context.set(merged)


def unbind(token: Token[CallContext | None]) -> None:
    try:
        _context.reset(token)
    except (ValueError, RuntimeError):
        # Token from another context or already reset — clear instead.
        _context.set(None)


@contextlib.contextmanager
def call_context(**fields: Any) -> Iterator[CallContext]:
    token = bind(**fields)
    try:
        ctx = _context.get()
        assert ctx is not None
        yield ctx
    finally:
        unbind(token)


def work_unit_id_or(default: uuid.UUID) -> uuid.UUID:
    """The inherited work unit (Celery header) if any, else ``default``."""
    ctx = _context.get()
    if ctx is not None and ctx.work_unit_id is not None:
        return ctx.work_unit_id
    return default


def celery_task_uuid(request_id: str | None) -> uuid.UUID:
    """A task's own id as a work unit; eager/direct calls have none."""
    try:
        return uuid.UUID(str(request_id))
    except (TypeError, ValueError):
        return uuid.uuid4()


async def record_call(record: CallRecord) -> None:
    """No-op. Rebound by ``ee.ai_usage.register()`` in the enterprise edition."""
    return None
