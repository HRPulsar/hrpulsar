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
