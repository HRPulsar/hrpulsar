"""Universal Celery enqueue helper that stamps WS-routing metadata into headers.

CR15 Celery → WS unification needs `tenant_id` / `user_id` / `module` / `action`
on every task so `celery_signals` can `PUBLISH` `task.updated` to the right
per-user channel. Dropping them into Celery message headers (instead of as
positional args) keeps task signatures untouched and lets signals read them
via `task.request.headers`.

Use this for every `apply_async` / `delay` we want surfaced in the UI.
"""

from __future__ import annotations

import uuid
from typing import Any

from celery import Task
from celery.result import AsyncResult


def _str_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def enqueue_task(
    task: Task,
    *args: Any,
    tenant_id: Any,
    user_id: Any,
    module: str,
    action: str,
    countdown: float | None = None,
    eta: Any | None = None,
    queue: str | None = None,
    **kwargs: Any,
) -> AsyncResult:
    """Schedule `task` with WS-routing metadata pinned in message headers.

    `tenant_id` / `user_id` are required so `celery_signals` can publish
    `task.updated` to `ws:tenant:{t}:user:{u}`. `module` and `action` are
    free-form strings used by the frontend to dispatch on event type
    (e.g. `module="ai"`, `action="generate_competences"`).
    """
    headers = {
        "tenant_id": _str_id(tenant_id),
        "user_id": _str_id(user_id),
        "module": module,
        "action": action,
    }
    apply_kwargs: dict[str, Any] = {
        "args": list(args),
        "kwargs": kwargs,
        "headers": headers,
    }
    if countdown is not None:
        apply_kwargs["countdown"] = countdown
    if eta is not None:
        apply_kwargs["eta"] = eta
    if queue is not None:
        apply_kwargs["queue"] = queue
    return task.apply_async(**apply_kwargs)
