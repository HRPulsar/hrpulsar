"""Celery → WebSocket bridge.

CR15 unification: every task transition (`STARTED` / `SUCCESS` / `FAILURE`)
fans out a `task.updated` event on `ws:tenant:{t}:user:{u}` so the frontend
hook `useTaskStatus(taskId)` updates without polling `GET /api/tasks/{id}`.

Routing metadata (`tenant_id`, `user_id`, `module`, `action`) lives in
Celery message headers — see `task_enqueue.enqueue_task`. Signals run
inside the worker process (no event loop), so we publish through the
synchronous `redis` client; this matches the pattern in
`app/core/tasks.py::write_celery_heartbeat` and avoids spinning a fresh
asyncio loop per signal call.

Broadcast is best-effort: a Redis hiccup must never break a task or its
result-backend write. Failures are logged and swallowed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis
from celery.signals import task_failure, task_postrun, task_prerun

from app.config import settings

logger = logging.getLogger(__name__)


_PUBLISHER: redis.Redis | None = None


def _get_publisher() -> redis.Redis:
    global _PUBLISHER
    if _PUBLISHER is None:
        _PUBLISHER = redis.Redis.from_url(settings.redis_url)
    return _PUBLISHER


def _user_channel(tenant_id: str, user_id: str) -> str:
    # Mirrors app.core.websocket.user_channel; redefined here so this module
    # stays import-cheap (no FastAPI/SQLAlchemy via app.core.websocket).
    return f"ws:tenant:{tenant_id}:user:{user_id}"


def _read_headers(sender: Any, task_id: str) -> dict[str, Any]:
    """Pull routing metadata from the task message headers.

    Celery exposes headers in two places:
    - `sender.request.headers` inside prerun/postrun (task instance bound).
    - `failure` signal also passes `sender` but `request` is the same.

    Returns an empty dict if headers are missing — the broadcast then short-
    circuits (nothing to address).
    """
    try:
        request = getattr(sender, "request", None)
        if request is None:
            return {}
        headers = getattr(request, "headers", None) or {}
        if isinstance(headers, dict):
            return headers
    except Exception:
        logger.exception("celery_signals: failed reading headers for %s", task_id)
    return {}


def _publish(payload: dict[str, Any], headers: dict[str, Any]) -> None:
    tenant_id = headers.get("tenant_id")
    user_id = headers.get("user_id")
    if not tenant_id or not user_id:
        # Tasks enqueued without enqueue_task() (e.g. internal periodic tasks
        # like write_celery_heartbeat) have no addressee — silently skip.
        return
    try:
        client = _get_publisher()
        client.publish(_user_channel(str(tenant_id), str(user_id)), json.dumps(payload))
    except Exception as exc:  # noqa: BLE001
        logger.warning("celery_signals publish failed: %s", exc)


def _build_payload(
    task_id: str,
    status: str,
    headers: dict[str, Any],
    *,
    result: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "task_id": task_id,
        "status": status,
        "module": headers.get("module"),
        "action": headers.get("action"),
        "result": result,
        "error": error,
    }
    return {"type": "task.updated", "payload": body}


def _safe_result(value: Any) -> Any:
    """Coerce a task return value into something JSON-serialisable.

    Most of our Celery tasks already return dict/list/scalar (Celery
    result_serializer is `json`), so this is mostly a guard for accidental
    objects. Falls back to `repr()`.
    """
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


@task_prerun.connect
def on_task_prerun(
    sender: Any = None,
    task_id: str | None = None,
    **_: Any,
) -> None:
    if not task_id:
        return
    headers = _read_headers(sender, task_id)
    payload = _build_payload(task_id, "STARTED", headers)
    _publish(payload, headers)


@task_postrun.connect
def on_task_postrun(
    sender: Any = None,
    task_id: str | None = None,
    state: str | None = None,
    retval: Any = None,
    **_: Any,
) -> None:
    if not task_id:
        return
    # `task_postrun` fires for both SUCCESS and FAILURE. We only emit the
    # SUCCESS variant here; FAILURE is handled by `task_failure` because it
    # has the exception object attached.
    if state != "SUCCESS":
        return
    headers = _read_headers(sender, task_id)
    payload = _build_payload(task_id, "SUCCESS", headers, result=_safe_result(retval))
    _publish(payload, headers)


@task_failure.connect
def on_task_failure(
    sender: Any = None,
    task_id: str | None = None,
    exception: BaseException | None = None,
    **_: Any,
) -> None:
    if not task_id:
        return
    headers = _read_headers(sender, task_id)
    error = str(exception) if exception is not None else "task failed"
    payload = _build_payload(task_id, "FAILURE", headers, error=error)
    _publish(payload, headers)
