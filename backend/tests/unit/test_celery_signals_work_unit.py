# backend/tests/unit/test_celery_signals_work_unit.py
"""HRP-964: the work unit of a billed request travels to the task it enqueues."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core import ai_usage_hooks, celery_signals
from celery.signals import before_task_publish


def test_publish_adds_header_only_inside_a_work_unit():
    headers: dict = {"tenant_id": "t"}
    celery_signals.on_before_task_publish(headers=headers)
    assert ai_usage_hooks.WORK_UNIT_HEADER not in headers

    work_unit_id = uuid.uuid4()
    with ai_usage_hooks.call_context(work_unit_id=work_unit_id):
        celery_signals.on_before_task_publish(headers=headers)
    assert headers[ai_usage_hooks.WORK_UNIT_HEADER] == str(work_unit_id)


def test_prerun_binds_header_and_postrun_resets():
    work_unit_id = uuid.uuid4()
    celery_signals._bind_work_unit("task-1", {ai_usage_hooks.WORK_UNIT_HEADER: str(work_unit_id)})
    assert ai_usage_hooks.current().work_unit_id == work_unit_id
    celery_signals._unbind_work_unit("task-1")
    assert ai_usage_hooks.current() is None


def test_postrun_resets_everything_bound_during_the_task():
    celery_signals._bind_work_unit("task-2", {})
    ai_usage_hooks.bind(tenant_id=uuid.uuid4(), action="ai.generate_competences")
    celery_signals._unbind_work_unit("task-2")
    assert ai_usage_hooks.current() is None


def test_invalid_header_binds_nothing_without_raising():
    celery_signals._bind_work_unit("task-3", {ai_usage_hooks.WORK_UNIT_HEADER: "garbage"})
    assert ai_usage_hooks.current().work_unit_id is None
    celery_signals._unbind_work_unit("task-3")


def test_before_task_publish_signal_dispatches_to_the_real_receiver():
    """Exercises the actual `before_task_publish.send(...)` wiring, not just
    a direct call to `on_before_task_publish` — the `@before_task_publish.
    connect` decoration is what actually has to work in a worker process."""
    headers: dict = {}
    work_unit_id = uuid.uuid4()
    with ai_usage_hooks.call_context(work_unit_id=work_unit_id):
        before_task_publish.send(
            sender="app.modules.ai.tasks.some_task",
            body={},
            exchange="",
            routing_key="",
            headers=headers,
            properties={},
            declare=[],
            retry_policy={},
        )
    assert headers[ai_usage_hooks.WORK_UNIT_HEADER] == str(work_unit_id)


def test_postrun_resets_context_even_when_the_task_failed():
    """Regression for the unbind placement: it must run before the
    `state != "SUCCESS"` early return in `on_task_postrun`, or a failed
    task's bound work unit leaks into the next task on the same prefork
    worker. Headers carry no tenant_id/user_id so `_publish` short-circuits
    before touching Redis — no publisher stub needed."""
    work_unit_id = uuid.uuid4()
    sender = SimpleNamespace(
        request=SimpleNamespace(headers={ai_usage_hooks.WORK_UNIT_HEADER: str(work_unit_id)})
    )
    celery_signals.on_task_prerun(sender=sender, task_id="t-fail")
    assert ai_usage_hooks.current().work_unit_id == work_unit_id

    celery_signals.on_task_postrun(sender=sender, task_id="t-fail", state="FAILURE", retval=None)
    assert ai_usage_hooks.current() is None
