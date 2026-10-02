"""HRP-964: unbilled features name themselves in the call journal."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from app.core import ai_usage_hooks
from app.modules.ai import llm_client
from app.modules.analytics import service as analytics_service

pytestmark = pytest.mark.asyncio


async def test_dev_loop_summary_runs_in_a_named_context(monkeypatch, db, tenant):
    seen: list[ai_usage_hooks.CallContext | None] = []

    async def fake_generate(*args, **kwargs):
        seen.append(ai_usage_hooks.current())
        return "summary"

    monkeypatch.setattr(llm_client, "generate", fake_generate)
    user_id = uuid.uuid4()

    with ai_usage_hooks.call_context(tenant_id=tenant.id, user_id=user_id):
        await analytics_service.generate_dev_loop_summary(
            db, tenant.id, {"stages": [], "findings": []}
        )

    (ctx,) = seen
    assert ctx.action == "analytics.dev_loop_summary"
    assert ctx.tenant_id == tenant.id and ctx.user_id == user_id
    assert isinstance(ctx.work_unit_id, uuid.UUID)


async def test_batch_embed_task_reads_tenant_and_user_from_headers(monkeypatch):
    """R11: ``ai/router.py`` stamps tenant_id/user_id into the Celery message
    headers (task_enqueue.py); the task reads them back for the journal."""
    from app.modules.ai import tasks as ai_tasks
    from celery.app.task import Context

    seen: list[ai_usage_hooks.CallContext | None] = []

    async def fake_get_embedding(text):
        seen.append(ai_usage_hooks.current())
        return [0.0] * 1536

    monkeypatch.setattr(llm_client, "get_embedding", fake_get_embedding)

    tenant_id, user_id, entity_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    items = [
        {"entity_type": "candidate", "entity_id": str(entity_id), "text_content": "hi"}
    ]

    # request_stack is thread-local — asyncio.to_thread's worker thread
    # never sees a pushed request, but it does see _default_request (a
    # plain instance attribute), which is the property's fallback.
    # HRP-954: the tenant is the task's argument (the rows are written for
    # it); the header carries only the acting user.
    ai_tasks.batch_embed_task._default_request = Context(
        headers={"tenant_id": str(uuid.uuid4()), "user_id": str(user_id)}
    )
    try:
        await asyncio.to_thread(ai_tasks.batch_embed_task.run, items, str(tenant_id))
    finally:
        ai_tasks.batch_embed_task._default_request = None

    (ctx,) = seen
    assert ctx.tenant_id == tenant_id and ctx.user_id == user_id
    assert ctx.action == "ai.batch_embed"
    assert (ctx.entity_type, ctx.entity_id) == ("candidate", entity_id)


async def test_batch_embed_queued_before_the_tenant_argument_reads_the_header(monkeypatch):
    # Review 01.10: a message the previous release queued carries only the
    # items; the new required argument failed it with a TypeError and the
    # batch was lost. The tenant comes from the header enqueue_task stamps.
    from app.modules.ai import tasks as ai_tasks
    from celery.app.task import Context

    seen: list[ai_usage_hooks.CallContext | None] = []

    async def fake_get_embedding(text):
        seen.append(ai_usage_hooks.current())
        return [0.0] * 1536

    monkeypatch.setattr(llm_client, "get_embedding", fake_get_embedding)
    tenant_id = uuid.uuid4()
    items = [{"entity_type": "candidate", "entity_id": str(uuid.uuid4()), "text_content": "hi"}]
    ai_tasks.batch_embed_task._default_request = Context(headers={"tenant_id": str(tenant_id)})
    try:
        await asyncio.to_thread(ai_tasks.batch_embed_task.run, items)
    finally:
        ai_tasks.batch_embed_task._default_request = None
    (ctx,) = seen
    assert ctx.tenant_id == tenant_id


async def test_parse_resume_task_keeps_the_inherited_work_unit(db, tenant, monkeypatch):
    """R9-style gap: a resume parsed from inside a billed request must keep
    that request's work unit, not mint its own."""
    from app.modules.recruitment import ai_service
    from app.modules.recruitment.models import Candidate, CandidateFile
    from app.modules.recruitment.tasks import parsing as parsing_tasks

    candidate = Candidate(
        tenant_id=tenant.id,
        full_name="Cand X",
        email=f"c-{uuid.uuid4().hex[:8]}@example.com",
    )
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)

    resume = CandidateFile(
        tenant_id=tenant.id,
        candidate_id=candidate.id,
        file_type="resume",
        original_filename="cv.pdf",
        mime_type="application/pdf",
        file_size=100,
        raw_text="some resume text",
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    seen: list[ai_usage_hooks.CallContext | None] = []

    async def fake_parse(text, **kwargs):
        seen.append(ai_usage_hooks.current())
        return {"current_position": "Lead"}

    monkeypatch.setattr(ai_service, "parse_resume_text", fake_parse)

    work_unit = uuid.uuid4()
    with ai_usage_hooks.call_context(work_unit_id=work_unit):
        await asyncio.to_thread(
            parsing_tasks.parse_resume_task.run, str(resume.id), str(tenant.id)
        )

    (ctx,) = seen
    assert ctx.work_unit_id == work_unit
    assert ctx.action == "recruitment.upload_resume"
    assert (ctx.entity_type, ctx.entity_id) == ("candidate", candidate.id)
