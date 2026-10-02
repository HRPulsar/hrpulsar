"""Core AI usage seam (HRP-964): call context + no-op recorder."""

from __future__ import annotations

import asyncio
import contextvars
import uuid

import pytest
from app.core import ai_usage_hooks
from app.core.ai_usage_hooks import CallContext, CallRecord


def test_no_context_by_default():
    assert ai_usage_hooks.current() is None


def test_call_context_sets_and_resets():
    tenant_id = uuid.uuid4()
    with ai_usage_hooks.call_context(
        tenant_id=tenant_id, action="ai.generate_competences"
    ) as ctx:
        assert ctx.tenant_id == tenant_id
        assert ai_usage_hooks.current() == ctx
    assert ai_usage_hooks.current() is None


def test_nested_context_merges_and_keeps_outer_fields():
    tenant_id, work_unit_id, entity_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with ai_usage_hooks.call_context(
        tenant_id=tenant_id, action="a", work_unit_id=work_unit_id
    ):
        with ai_usage_hooks.call_context(
            entity_type="vacancy", entity_id=entity_id, action=None
        ) as inner:
            assert inner == CallContext(
                tenant_id=tenant_id,
                action="a",
                entity_type="vacancy",
                entity_id=entity_id,
                work_unit_id=work_unit_id,
            )
        assert ai_usage_hooks.current().entity_type is None


def test_bind_is_undone_by_its_token():
    token = ai_usage_hooks.bind(action="x")
    assert ai_usage_hooks.current().action == "x"
    ai_usage_hooks.unbind(token)
    assert ai_usage_hooks.current() is None


def test_unbind_tolerates_a_foreign_token():
    # celery_signals resets the prerun token from postrun. A token minted in
    # another Context (ValueError on reset) or one reset twice (RuntimeError)
    # must clear the var instead of raising.
    foreign = contextvars.copy_context().run(ai_usage_hooks.bind, action="elsewhere")
    ai_usage_hooks.bind(action="here")
    ai_usage_hooks.unbind(foreign)
    assert ai_usage_hooks.current() is None

    token = ai_usage_hooks.bind(action="x")
    ai_usage_hooks.unbind(token)
    ai_usage_hooks.unbind(token)  # already used — must not raise
    assert ai_usage_hooks.current() is None


def test_context_reaches_coroutines_run_by_asyncio_run():
    async def read() -> CallContext | None:
        return ai_usage_hooks.current()

    with ai_usage_hooks.call_context(action="recruitment.analyze_interview"):
        assert asyncio.run(read()).action == "recruitment.analyze_interview"


def test_work_unit_id_or_prefers_inherited():
    inherited, own = uuid.uuid4(), uuid.uuid4()
    assert ai_usage_hooks.work_unit_id_or(own) == own
    with ai_usage_hooks.call_context(work_unit_id=inherited):
        assert ai_usage_hooks.work_unit_id_or(own) == inherited


def test_celery_task_uuid_parses_or_generates():
    request_id = str(uuid.uuid4())
    assert ai_usage_hooks.celery_task_uuid(request_id) == uuid.UUID(request_id)
    assert isinstance(ai_usage_hooks.celery_task_uuid(None), uuid.UUID)
    assert isinstance(ai_usage_hooks.celery_task_uuid("not-a-uuid"), uuid.UUID)


@pytest.mark.asyncio
async def test_record_call_is_a_noop():
    record = CallRecord(
        kind="generate",
        provider="openai",
        model="gpt-4o",
        credential_source="platform",
        latency_ms=1,
        status="ok",
    )
    assert await ai_usage_hooks.record_call(record) is None
