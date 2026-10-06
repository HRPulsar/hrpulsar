"""HRP-987: a model the catalog disabled with no replacement is refused with
``ai_model_unavailable`` - never dispatched - whether the tenant pinned it
or an effort preset resolved to it. Read projections keep working."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.config import settings
from app.core.errors import AppError
from app.modules.ai import llm_client, model_catalog_service
from app.modules.ai import service as ai_service
from app.modules.ai.models import ModelCatalogEntry
from app.modules.ai_settings import service as ai_settings_service
from sqlalchemy import delete

from tests.unit.test_hrp492_full_run_progress import _runs_for, _setup
from tests.unit.test_hrp492_full_run_progress import dispatched as _dispatched

dispatched = _dispatched


@pytest.fixture
async def disabled_model(db):
    """A disabled catalog row alone in its tier: there is no replacement.

    Catalog rows are platform-wide (no tenant) - removed in ``finally``.
    """
    suffix = uuid.uuid4().hex[:6]
    model_id = f"gpt-off-{suffix}"
    db.add(
        ModelCatalogEntry(
            provider="openai",
            model_id=model_id,
            label=model_id,
            tier=f"tier-{suffix}",
            status="approved",
            enabled=False,
            credit_multiplier=1.0,
            source="discovered",
        )
    )
    await db.commit()
    try:
        yield model_id
    finally:
        await db.execute(
            delete(ModelCatalogEntry).where(ModelCatalogEntry.model_id == model_id)
        )
        await db.commit()


async def _pin(db, tenant, model_id):
    row = await ai_settings_service.get_or_default(db, tenant.id)
    row.llm_model = model_id
    row.effort_level = "custom"
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _provider_mocks():
    return [
        patch.object(llm_client, name, new_callable=AsyncMock)
        for name in ("_generate_openai", "_generate_anthropic", "_generate_gemini")
    ]


async def test_a_pinned_disabled_model_is_never_called(db, tenant, disabled_model):
    await _pin(db, tenant, disabled_model)
    mocks = _provider_mocks()
    started = [m.start() for m in mocks]
    try:
        with pytest.raises(AppError) as exc:
            await ai_service.generate_competences(db, tenant.id, None, "Engineer")
    finally:
        for m in mocks:
            m.stop()

    assert exc.value.code == "ai_model_unavailable"
    assert exc.value.status_code == 409
    assert exc.value.params == {"model": disabled_model}
    for mock in started:
        mock.assert_not_awaited()


async def test_a_preset_resolving_to_a_disabled_model_is_refused(
    db, tenant, disabled_model
):
    row = await ai_settings_service.get_or_default(db, tenant.id)
    row.llm_model = None
    row.effort_level = "balanced"
    preset_models = ai_settings_service.EFFORT_PRESETS["balanced"]["models"]
    with (
        patch.object(settings, "llm_provider", "openai"),
        patch.dict(preset_models, {"openai": disabled_model}),
        pytest.raises(AppError) as exc,
    ):
        await ai_settings_service.get_effective_model_async(db, row)
    assert exc.value.code == "ai_model_unavailable"


async def test_the_processor_list_may_still_swap_the_model(
    db, tenant, disabled_model, monkeypatch
):
    # HRP-1005 first: a model whose provider the workspace may not use is
    # swapped for an allowed one - only a model nothing replaces is refused.
    from app.modules.ai import processors

    row = await _pin(db, tenant, disabled_model)

    async def _swap(_db, _tenant_id, model):
        return "claude-allowed" if model == disabled_model else model

    monkeypatch.setattr(processors, "substitute_model", _swap)
    resolved = await ai_settings_service.get_effective_model_async(db, row)
    assert resolved == "claude-allowed"


async def test_read_projections_still_show_the_model(db, tenant, disabled_model):
    row = await _pin(db, tenant, disabled_model)

    projected = await ai_settings_service.to_read_dict_async(db, row)
    assert projected["effective_model"] == disabled_model
    multiplier = await ai_settings_service.get_effective_credit_multiplier_async(
        db, row
    )
    assert multiplier == pytest.approx(1.0)


async def test_the_sync_worker_path_refuses_too(db, disabled_model):
    with pytest.raises(AppError) as exc:
        await db.run_sync(
            lambda s: model_catalog_service.resolve_dispatch_model_sync(
                s, disabled_model
            )
        )
    assert exc.value.code == "ai_model_unavailable"


async def test_the_interview_analysis_fails_before_the_paid_stage(
    db, dispatched, monkeypatch
):
    """The full recruitment analysis refuses before the first LLM-spending
    stage (cancel still refunds there) and does not retry the refusal."""
    import asyncio

    from app.modules.recruitment import interview_service
    from app.modules.recruitment.models import AIAnalysisRun
    from app.modules.recruitment.tasks import analyze_interview_task
    from sqlalchemy import select

    interview, tenant, _ = await _setup(db)
    await interview_service.enqueue_analyze(db, tenant.id, interview.id)
    stages_at_refusal: list[str | None] = []

    def _refuse(sync_db, model):
        stages_at_refusal.append(
            sync_db.execute(
                select(AIAnalysisRun.current_stage).where(
                    AIAnalysisRun.interview_id == interview.id
                )
            ).scalar_one()
        )
        raise AppError("ai_model_unavailable", 409, model="gpt-gone")

    async def _never(*args, **kwargs):
        raise AssertionError("a refused model must not be called")

    monkeypatch.setattr(model_catalog_service, "resolve_dispatch_model_sync", _refuse)
    monkeypatch.setattr(llm_client, "generate_json", _never)
    test_db_url = settings.database_url.rsplit("/", 1)[0] + "/hrpulsar_test"
    monkeypatch.setattr(settings, "database_url", test_db_url)

    outcome = await asyncio.to_thread(
        analyze_interview_task.apply, args=(str(interview.id), str(tenant.id))
    )

    assert outcome.failed()
    assert len(stages_at_refusal) == 1  # not retried
    assert stages_at_refusal[0] != "competences"
    assert [r.status for r in await _runs_for(db, interview)] == ["failed"]
