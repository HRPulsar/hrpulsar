"""HRP-964: AI tasks bind the call context from the row they load."""

from __future__ import annotations

import uuid

import pytest
from app.core import ai_usage_hooks
from app.modules.ai_competence_generation import tasks as compgen_tasks
from app.modules.work import tasks as work_tasks


def test_scope_entity_map_covers_every_target_scope():
    assert compgen_tasks._SCOPE_ENTITY == {
        "group": "competence_group",
        "competence_indicators": "competence",
        "specialization_matrix": "specialization",
    }


@pytest.mark.asyncio
async def test_compgen_bind_uses_session_row(monkeypatch):
    class Sess:
        id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        scope = "competence_indicators"
        target_id = uuid.uuid4()
        params = {"billing_action": "ai_competence_generation.start_competence_indicators"}

    compgen_tasks._bind_session_context(Sess())
    ctx = ai_usage_hooks.current()
    assert (ctx.tenant_id, ctx.user_id) == (Sess.tenant_id, Sess.user_id)
    assert ctx.action == "ai_competence_generation.start_competence_indicators"
    assert (ctx.entity_type, ctx.entity_id) == ("competence", Sess.target_id)
    assert ctx.work_unit_id == Sess.id


@pytest.mark.asyncio
async def test_compgen_bind_keeps_inherited_work_unit():
    inherited = uuid.uuid4()

    class Sess:
        id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        user_id = None
        scope = "whole_base"
        target_id = None
        params = {}

    with ai_usage_hooks.call_context(work_unit_id=inherited):
        compgen_tasks._bind_session_context(Sess())
        ctx = ai_usage_hooks.current()
        assert ctx.work_unit_id == inherited
        assert ctx.action == "ai_competence_generation.start_whole_base"
        assert ctx.entity_type is None


@pytest.mark.asyncio
async def test_work_decomposition_bind_points_at_the_container():
    class Sess:
        id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        container_id = uuid.uuid4()
        params = {}

    work_tasks._bind_session_context(Sess())
    ctx = ai_usage_hooks.current()
    assert ctx.action == "work_decomposition.start"
    assert (ctx.entity_type, ctx.entity_id) == ("work_container", Sess.container_id)
    assert ctx.work_unit_id == Sess.id


@pytest.mark.asyncio
async def test_question_set_task_binds_the_set_row(monkeypatch):
    """HRP-471 moved question-set generation into Celery, past the billing
    wrapper: the task binds the context itself, so the model calls and the
    charge inside the job share one work unit - the run's, not the set's
    id, which every regeneration of the set reuses (review 01.10)."""
    import asyncio

    from app.modules.recruitment import question_service
    from app.modules.recruitment.tasks.generation import generate_question_set_task

    seen: list[ai_usage_hooks.CallContext | None] = []

    async def fake_job(*args, **kwargs):
        seen.append(ai_usage_hooks.current())
        return {"status": "ready"}

    monkeypatch.setattr(question_service, "_run_generation_job", fake_job)
    set_id, tenant_id, cv_id, user_id = (uuid.uuid4() for _ in range(4))

    result = await asyncio.to_thread(
        generate_question_set_task.run,
        str(set_id), str(tenant_id), str(cv_id), {}, str(user_id), None,
    )

    assert result == {"status": "ready", "set_id": str(set_id)}
    (ctx,) = seen
    assert (ctx.tenant_id, ctx.user_id) == (tenant_id, user_id)
    assert ctx.action == "recruitment.generate_question_set"
    assert (ctx.entity_type, ctx.entity_id) == ("candidate_vacancy", cv_id)
    assert ctx.work_unit_id is not None and ctx.work_unit_id != set_id
