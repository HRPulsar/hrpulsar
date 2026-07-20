"""CR15: Celery → WebSocket broadcast unit tests.

Drives `app.core.celery_signals` directly with synthetic sender/headers —
no live Redis, no live Celery worker. Verifies:
  - shape of `task.updated` events
  - prerun → STARTED, postrun(SUCCESS) → SUCCESS, failure → FAILURE
  - postrun(FAILURE) is a no-op (failure handler owns it, has the exception)
  - missing tenant_id/user_id headers → no publish (safety net for
    periodic tasks like write_celery_heartbeat)
  - publisher exceptions are swallowed (best-effort)
  - enqueue_task wires headers through Celery's apply_async
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _sender(headers: dict | None) -> SimpleNamespace:
    """Build a minimal Celery task instance with a request.headers attribute."""
    return SimpleNamespace(request=SimpleNamespace(headers=headers or {}))


def _capture_publish(monkeypatch):
    """Replace _get_publisher() with a MagicMock and return it."""
    from app.core import celery_signals

    fake = MagicMock()
    fake.publish = MagicMock()
    monkeypatch.setattr(celery_signals, "_get_publisher", lambda: fake)
    monkeypatch.setattr(celery_signals, "_PUBLISHER", fake, raising=False)
    return fake


def test_prerun_publishes_started_event(monkeypatch):
    from app.core import celery_signals

    fake = _capture_publish(monkeypatch)
    headers = {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "module": "ai",
        "action": "generate_competences",
    }
    celery_signals.on_task_prerun(sender=_sender(headers), task_id="task-abc")

    fake.publish.assert_called_once()
    channel, raw = fake.publish.call_args.args
    assert channel == "ws:tenant:tenant-1:user:user-1"
    payload = json.loads(raw)
    assert payload["type"] == "task.updated"
    assert payload["payload"] == {
        "task_id": "task-abc",
        "status": "STARTED",
        "module": "ai",
        "action": "generate_competences",
        "result": None,
        "error": None,
    }


def test_postrun_success_publishes_result(monkeypatch):
    from app.core import celery_signals

    fake = _capture_publish(monkeypatch)
    headers = {
        "tenant_id": "t1",
        "user_id": "u1",
        "module": "data_import",
        "action": "import_employees",
    }
    celery_signals.on_task_postrun(
        sender=_sender(headers),
        task_id="task-1",
        state="SUCCESS",
        retval={"processed": 42},
    )
    payload = json.loads(fake.publish.call_args.args[1])
    assert payload["payload"]["status"] == "SUCCESS"
    assert payload["payload"]["result"] == {"processed": 42}
    assert payload["payload"]["error"] is None


def test_postrun_failure_state_is_skipped(monkeypatch):
    from app.core import celery_signals

    fake = _capture_publish(monkeypatch)
    celery_signals.on_task_postrun(
        sender=_sender({"tenant_id": "t1", "user_id": "u1"}),
        task_id="task-1",
        state="FAILURE",
        retval=None,
    )
    fake.publish.assert_not_called()


def test_failure_publishes_error(monkeypatch):
    from app.core import celery_signals

    fake = _capture_publish(monkeypatch)
    headers = {"tenant_id": "t1", "user_id": "u1", "module": "ai", "action": "x"}
    exc = RuntimeError("LLM blew up")
    celery_signals.on_task_failure(
        sender=_sender(headers), task_id="task-1", exception=exc
    )
    payload = json.loads(fake.publish.call_args.args[1])
    assert payload["payload"]["status"] == "FAILURE"
    assert payload["payload"]["error"] == "LLM blew up"
    assert payload["payload"]["result"] is None


def test_missing_routing_headers_skips_publish(monkeypatch):
    from app.core import celery_signals

    fake = _capture_publish(monkeypatch)
    # Periodic tasks (write_celery_heartbeat, send_deadline_reminders) have no headers.
    celery_signals.on_task_prerun(sender=_sender({}), task_id="task-x")
    celery_signals.on_task_postrun(
        sender=_sender({}), task_id="task-x", state="SUCCESS", retval=None
    )
    fake.publish.assert_not_called()


def test_partial_headers_skip_publish(monkeypatch):
    from app.core import celery_signals

    fake = _capture_publish(monkeypatch)
    # tenant_id without user_id (and vice-versa) → no addressee.
    celery_signals.on_task_prerun(sender=_sender({"tenant_id": "t1"}), task_id="task-x")
    celery_signals.on_task_prerun(sender=_sender({"user_id": "u1"}), task_id="task-y")
    fake.publish.assert_not_called()


def test_publisher_exception_is_swallowed(monkeypatch):
    from app.core import celery_signals

    fake = MagicMock()
    fake.publish.side_effect = RuntimeError("redis down")
    monkeypatch.setattr(celery_signals, "_get_publisher", lambda: fake)

    headers = {"tenant_id": "t", "user_id": "u", "module": "m", "action": "a"}
    # Must not raise.
    celery_signals.on_task_prerun(sender=_sender(headers), task_id="task-1")


def test_non_json_result_falls_back_to_repr(monkeypatch):
    from app.core import celery_signals

    fake = _capture_publish(monkeypatch)

    class Weird:
        def __repr__(self) -> str:
            return "<Weird>"

    headers = {"tenant_id": "t", "user_id": "u", "module": "m", "action": "a"}
    celery_signals.on_task_postrun(
        sender=_sender(headers),
        task_id="task-1",
        state="SUCCESS",
        retval=Weird(),
    )
    payload = json.loads(fake.publish.call_args.args[1])
    assert payload["payload"]["result"] == "<Weird>"


def test_missing_task_id_is_noop(monkeypatch):
    from app.core import celery_signals

    fake = _capture_publish(monkeypatch)
    celery_signals.on_task_prerun(sender=_sender({}), task_id=None)
    celery_signals.on_task_postrun(
        sender=_sender({}), task_id=None, state="SUCCESS", retval=None
    )
    celery_signals.on_task_failure(
        sender=_sender({}), task_id=None, exception=RuntimeError()
    )
    fake.publish.assert_not_called()


# ---------------------------------------------------------------------------
# enqueue_task: verify headers/args wiring through apply_async
# ---------------------------------------------------------------------------


def test_enqueue_task_passes_headers_and_args():
    from app.core.task_enqueue import enqueue_task

    fake_task = MagicMock()
    enqueue_task(
        fake_task,
        "arg1",
        42,
        tenant_id="tenant-1",
        user_id="user-1",
        module="ai",
        action="generate_competences",
    )
    fake_task.apply_async.assert_called_once()
    kwargs = fake_task.apply_async.call_args.kwargs
    assert kwargs["args"] == ["arg1", 42]
    assert kwargs["headers"] == {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "module": "ai",
        "action": "generate_competences",
    }


def test_enqueue_task_stringifies_uuid_ids():
    import uuid as uuid_mod

    from app.core.task_enqueue import enqueue_task

    fake_task = MagicMock()
    tid, uid = uuid_mod.uuid4(), uuid_mod.uuid4()
    enqueue_task(
        fake_task,
        tenant_id=tid,
        user_id=uid,
        module="m",
        action="a",
    )
    headers = fake_task.apply_async.call_args.kwargs["headers"]
    assert headers["tenant_id"] == str(tid)
    assert headers["user_id"] == str(uid)


def test_enqueue_task_forwards_optional_apply_kwargs():
    from app.core.task_enqueue import enqueue_task

    fake_task = MagicMock()
    enqueue_task(
        fake_task,
        tenant_id="t",
        user_id="u",
        module="m",
        action="a",
        countdown=5,
        queue="ai_queue",
    )
    kwargs = fake_task.apply_async.call_args.kwargs
    assert kwargs["countdown"] == 5
    assert kwargs["queue"] == "ai_queue"


# ---------------------------------------------------------------------------
# Round-trip: enqueue_task → eager execution → broadcast verified
# ---------------------------------------------------------------------------


@pytest.fixture
def eager_celery():
    """Run Celery tasks synchronously inside the test so signals fire here."""
    from app.core.celery_app import celery

    prev_eager = celery.conf.task_always_eager
    prev_propagate = celery.conf.task_eager_propagates
    celery.conf.task_always_eager = True
    celery.conf.task_eager_propagates = False
    try:
        yield celery
    finally:
        celery.conf.task_always_eager = prev_eager
        celery.conf.task_eager_propagates = prev_propagate


def test_eager_task_emits_started_and_success_events(monkeypatch, eager_celery):
    """End-to-end: enqueue_task → eager run → STARTED then SUCCESS published."""
    from app.core import celery_signals
    from app.core.celery_app import celery
    from app.core.task_enqueue import enqueue_task

    fake = _capture_publish(monkeypatch)

    @celery.task(name="app.core.tests.cr15_eager_ok")
    def cr15_eager_ok(payload):
        return {"echo": payload}

    enqueue_task(
        cr15_eager_ok,
        "hello",
        tenant_id="t1",
        user_id="u1",
        module="test",
        action="cr15_eager_ok",
    )

    # Order is implementation-defined within a single eager run, but both
    # transitions must show up.
    payloads = [json.loads(c.args[1]) for c in fake.publish.call_args_list]
    statuses = [p["payload"]["status"] for p in payloads]
    assert "STARTED" in statuses
    assert "SUCCESS" in statuses
    success_payload = next(p for p in payloads if p["payload"]["status"] == "SUCCESS")
    assert success_payload["payload"]["result"] == {"echo": "hello"}
    assert success_payload["payload"]["module"] == "test"
    assert success_payload["payload"]["action"] == "cr15_eager_ok"

    # Suppress "unused import" — celery_signals is imported for its side
    # effect (registering the @task_*.connect handlers via celery_app).
    assert celery_signals is not None


def test_eager_task_failure_emits_failure_event(monkeypatch, eager_celery):
    from app.core.celery_app import celery
    from app.core.task_enqueue import enqueue_task

    fake = _capture_publish(monkeypatch)

    @celery.task(name="app.core.tests.cr15_eager_fail")
    def cr15_eager_fail():
        raise ValueError("nope")

    enqueue_task(
        cr15_eager_fail,
        tenant_id="t1",
        user_id="u1",
        module="test",
        action="cr15_eager_fail",
    )

    payloads = [json.loads(c.args[1]) for c in fake.publish.call_args_list]
    statuses = [p["payload"]["status"] for p in payloads]
    assert "STARTED" in statuses
    assert "FAILURE" in statuses
    failure = next(p for p in payloads if p["payload"]["status"] == "FAILURE")
    assert "nope" in failure["payload"]["error"]
