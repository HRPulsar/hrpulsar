"""HRP-1005: which outside AI processors may receive a tenant's data."""

from __future__ import annotations

import uuid

import pytest
from app.config import Settings, settings
from app.modules.ai import model_registry, processors, providers
from app.modules.ai.models import ModelCatalogEntry
from app.modules.ai_settings import service as ai_settings_service

pytestmark = pytest.mark.asyncio


def test_empty_instance_list_allows_every_processor(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_processors_default", "")
    assert processors.instance_default() == frozenset(processors.PROCESSORS)


def test_instance_list_ignores_case_and_spaces(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_processors_default", " Anthropic, jev ")
    assert processors.instance_default() == {"anthropic", "jev"}


def test_unknown_instance_processor_refuses_to_start() -> None:
    with pytest.raises(ValueError, match="unknown processors"):
        Settings(ai_processors_default="anthropic,antrhopic")


def test_overrides_add_and_remove_on_top_of_the_instance(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_processors_default", "anthropic,openai")
    assert processors.effective_processors(
        {"jev": True, "openai": False}, False
    ) == {"anthropic", "jev"}


def test_a_new_instance_processor_reaches_tenants_with_overrides(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_processors_default", "anthropic,openai,gemini")
    assert "gemini" in processors.effective_processors({"openai": False}, False)


def test_own_keys_only_ignores_instance_and_overrides(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_processors_default", "")
    assert processors.effective_processors({"jev": True}, True) == frozenset()


def test_unknown_override_key_is_ignored(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_processors_default", "anthropic")
    assert processors.effective_processors({"mistral": True}, False) == {"anthropic"}


async def test_allowed_processors_reads_the_tenant(db, tenant, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_processors_default", "anthropic,openai")
    tenant.ai_processor_overrides = {"openai": False, "jev": True}
    await db.commit()
    assert await processors.allowed_processors(db, tenant.id) == {"anthropic", "jev"}


async def test_missing_tenant_gets_the_instance_list(db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_processors_default", "yandex")
    assert await processors.allowed_processors(db, uuid.uuid4()) == {"yandex"}


async def test_sync_twin_reads_the_same_tenant(db, tenant, monkeypatch) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from tests.conftest import TEST_DB_URL

    monkeypatch.setattr(settings, "ai_processors_default", "anthropic,openai")
    tenant.ai_own_keys_only = True
    await db.commit()
    engine = create_engine(TEST_DB_URL.replace("+asyncpg", "+psycopg2"))
    try:
        with Session(engine) as sync_db:
            assert processors.allowed_processors_sync(sync_db, tenant.id) == frozenset()
    finally:
        engine.dispose()


async def test_require_processor_refuses_a_disallowed_one(db, tenant, monkeypatch) -> None:
    from app.core.errors import AppError

    monkeypatch.setattr(settings, "ai_processors_default", "anthropic")
    with pytest.raises(AppError) as exc:
        await processors.require_processor(db, tenant.id, "openai")
    assert exc.value.code == "ai_processor_not_allowed"
    await processors.require_processor(db, tenant.id, "anthropic")


def test_platform_key_configured_follows_the_env(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jev_api_key", "")
    assert not processors.platform_key_configured("jev")
    monkeypatch.setattr(settings, "jev_api_key", "k")
    assert processors.platform_key_configured("jev")
    monkeypatch.setattr(settings, "yandex_api_key", "")
    monkeypatch.setattr(settings, "yandex_speechkit_api_key", "sk")
    assert processors.platform_key_configured("yandex")


# --- Generation: substitution on a disallowed provider (HRP-1005) -----------


def _platform_keys(monkeypatch, **keys: str) -> None:
    for name in ("anthropic", "openai", "gemini", "yandex"):
        monkeypatch.setattr(settings, f"{name}_api_key", keys.get(name, ""))


def _row(provider: str, model_id: str, tier: str) -> ModelCatalogEntry:
    return ModelCatalogEntry(
        provider=provider,
        model_id=model_id,
        tier=tier,
        status="approved",
        enabled=True,
        source="seed",
        credit_multiplier=None,
    )


def test_permitted_model_is_kept(monkeypatch) -> None:
    _platform_keys(monkeypatch, anthropic="a", openai="o")
    assert processors.choose_model("gpt-4o", [], frozenset({"openai"}), {}) == (
        "gpt-4o",
        "openai",
    )


def test_disallowed_model_keeps_its_tier_on_the_default_provider(monkeypatch) -> None:
    _platform_keys(monkeypatch, anthropic="a", openai="o")
    monkeypatch.setattr(settings, "llm_provider", "claude")
    catalog = [
        _row("openai", "gpt-fast-x", "fast"),
        _row("anthropic", "claude-fast-x", "fast"),
    ]
    assert processors.choose_model(
        "gpt-fast-x", catalog, frozenset({"anthropic"}), {}
    ) == ("claude-fast-x", "anthropic")


def test_without_a_catalog_row_the_preset_model_of_the_tier_is_used(monkeypatch) -> None:
    _platform_keys(monkeypatch, anthropic="a", openai="o")
    monkeypatch.setattr(settings, "llm_provider", "claude")
    assert processors.choose_model("gpt-4o", [], frozenset({"anthropic"}), {}) == (
        model_registry.BALANCED_MODELS["anthropic"],
        "anthropic",
    )


def test_a_candidate_without_a_platform_key_is_skipped(monkeypatch) -> None:
    _platform_keys(monkeypatch, gemini="g")
    monkeypatch.setattr(settings, "llm_provider", "claude")
    chosen = processors.choose_model(
        "gpt-4o", [], frozenset({"anthropic", "gemini"}), {}
    )
    assert chosen == (model_registry.BALANCED_MODELS["gemini"], "gemini")


def test_own_keys_only_moves_to_the_tenants_byok_provider(monkeypatch) -> None:
    _platform_keys(monkeypatch, anthropic="a", openai="o")
    monkeypatch.setattr(settings, "llm_provider", "claude")
    chosen = processors.choose_model(
        model_registry.BALANCED_MODELS["anthropic"],
        [],
        frozenset(),
        {"openai": "gpt-4o-mini"},
    )
    assert chosen == ("gpt-4o-mini", "openai")


def test_own_keys_only_falls_back_to_the_tenants_compatible_server(monkeypatch) -> None:
    # Review 01.10: the search walked the four LLM providers only, so an
    # own-keys-only tenant whose one row is an OpenAI-compatible server
    # (Azure, GigaChat, a local one) got ai_no_allowed_processor on every
    # call driven by its AI settings.
    _platform_keys(monkeypatch, anthropic="a", openai="o")
    monkeypatch.setattr(settings, "llm_provider", "claude")
    chosen = processors.choose_model(
        model_registry.BALANCED_MODELS["anthropic"],
        [],
        frozenset(),
        {"openai_compatible": "qwen2.5-72b"},
    )
    assert chosen == ("qwen2.5-72b", "openai_compatible")


def test_nothing_usable_returns_none(monkeypatch) -> None:
    _platform_keys(monkeypatch, anthropic="a")
    assert processors.choose_model("gpt-4o", [], frozenset(), {}) is None


def test_a_local_model_is_not_governed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    assert processors.choose_model("qwen2.5-72b", [], frozenset(), {}) == (
        "qwen2.5-72b",
        "openai_compatible",
    )


async def test_resolver_forces_the_substitute(db, tenant, monkeypatch) -> None:
    _platform_keys(monkeypatch, anthropic="a", openai="o")
    monkeypatch.setattr(settings, "llm_provider", "claude")
    monkeypatch.setattr(settings, "ai_processors_default", "")
    tenant.ai_processor_overrides = {"openai": False}
    await db.commit()
    target = await providers.resolve_generation_target(db, tenant.id, "gpt-4o")
    assert target.provider == "anthropic"
    assert target.forced_model is True
    assert target.model and target.model.startswith("claude")


async def test_resolver_refuses_when_nothing_is_allowed(db, tenant, monkeypatch) -> None:
    from app.core.errors import AppError

    _platform_keys(monkeypatch, anthropic="a", openai="o")
    tenant.ai_own_keys_only = True
    await db.commit()
    with pytest.raises(AppError) as exc:
        await providers.resolve_generation_target(db, tenant.id, None)
    assert exc.value.code == "ai_no_allowed_processor"


async def test_resolver_sync_substitutes_a_disallowed_default_provider(
    db, tenant, monkeypatch
) -> None:
    """F3a: ``resolve_generation_target_sync`` — the sync twin Celery
    workers use — must force a substitute exactly like the async resolver
    when the tenant's own default provider (``model=None``) is disallowed."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from tests.conftest import TEST_DB_URL

    _platform_keys(monkeypatch, anthropic="a", openai="o")
    monkeypatch.setattr(settings, "llm_provider", "claude")
    monkeypatch.setattr(settings, "ai_processors_default", "")
    tenant.ai_processor_overrides = {"anthropic": False}
    await db.commit()

    engine = create_engine(TEST_DB_URL.replace("+asyncpg", "+psycopg2"))
    try:
        with Session(engine) as sync_db:
            target = providers.resolve_generation_target_sync(sync_db, tenant.id, None)
    finally:
        engine.dispose()

    assert target.provider == "openai"
    assert target.forced_model is True
    assert target.model == model_registry.BALANCED_MODELS["openai"]


async def test_default_tenant_resolves_as_before(db, tenant, monkeypatch) -> None:
    _platform_keys(monkeypatch, anthropic="a", openai="o")
    monkeypatch.setattr(settings, "ai_processors_default", "")
    target = await providers.resolve_generation_target(db, tenant.id, "gpt-4o")
    assert target == providers.GenerationTarget(provider="openai")


async def test_generate_dispatches_the_forced_model(monkeypatch) -> None:
    from app.modules.ai import llm_client

    seen: dict[str, str] = {}

    async def _fake_anthropic(prompt, system, model, temperature, max_tokens, *, api_key=None):
        seen["model"] = model
        return "ok", llm_client._Usage()

    monkeypatch.setattr(llm_client, "_generate_anthropic", _fake_anthropic)
    target = providers.GenerationTarget(
        provider="anthropic", model="claude-forced", forced_model=True
    )
    await llm_client.generate("hi", model="gpt-4o", credentials=target)
    assert seen["model"] == "claude-forced"


# --- Review round 1 fixes (HRP-1005: R4, R5) ---------------------------------


async def _add_azure_row(db, tenant_id) -> None:
    from app.core.crypto import encrypt_secret
    from app.modules.recruitment.models import LLMProviderConfig

    db.add(
        LLMProviderConfig(
            tenant_id=tenant_id,
            provider="azure",
            model="gpt-4o",
            api_key_encrypted=encrypt_secret("sk-azure"),
            is_active=True,
            settings={"base_url": "https://acme.openai.azure.example/v1"},
        )
    )
    await db.commit()


async def test_substitute_model_keeps_an_azure_rows_model(db, tenant, monkeypatch) -> None:
    # R4: the row dispatches gpt-4o regardless of the openai override — a
    # proxy BYOK row is keyed "openai_compatible" (its base_url), not by the
    # model name's provider, so it must not be second-guessed by the list.
    _platform_keys(monkeypatch, anthropic="a", openai="o")
    monkeypatch.setattr(settings, "ai_processors_default", "")
    tenant.ai_processor_overrides = {"openai": False}
    await db.commit()
    await _add_azure_row(db, tenant.id)
    assert await processors.substitute_model(db, tenant.id, "gpt-4o") == "gpt-4o"


async def test_substitute_model_keeps_an_azure_rows_model_under_own_keys_only(
    db, tenant, monkeypatch
) -> None:
    _platform_keys(monkeypatch, anthropic="a", openai="o")
    tenant.ai_own_keys_only = True
    await db.commit()
    await _add_azure_row(db, tenant.id)
    assert await processors.substitute_model(db, tenant.id, "gpt-4o") == "gpt-4o"


def test_enforce_target_borrows_byok_credentials_for_an_unclassifiable_model() -> None:
    # R5 reproduction: own-keys-only tenant, an OpenAI BYOK row keyed to a
    # different model, and a call for a model no prefix owns that the
    # approved catalog maps to "openai". The fallback target is always
    # keyless/global — it must not dispatch on the platform key just because
    # OpenAI is *also* BYOK-covered; the tenant's own row must carry the call.
    from app.core.crypto import encrypt_secret
    from app.modules.recruitment.models import LLMProviderConfig

    row = LLMProviderConfig(
        tenant_id=uuid.uuid4(),
        provider="openai",
        model="gpt-4o",
        api_key_encrypted=encrypt_secret("sk-tenant"),
        is_active=True,
    )
    catalog = [_row("openai", "zeta-omni-1", "balanced")]
    target = providers.GenerationTarget(provider="openai")

    result = processors.enforce_target(
        target, "zeta-omni-1", [row], frozenset(), catalog
    )
    assert result.model == "zeta-omni-1"
    assert result.source == "byok"
    assert result.api_key == "sk-tenant"
    assert result.forced_model is True


# --- Task 3: settings, billing and the /processors endpoint follow the list -


async def test_billing_and_dispatch_agree_on_the_substitute(db, tenant, monkeypatch) -> None:
    """The multiplier is read off the effective model — it must be the model
    that really goes out."""
    _platform_keys(monkeypatch, anthropic="a", openai="o")
    monkeypatch.setattr(settings, "llm_provider", "claude")
    tenant.ai_processor_overrides = {"openai": False}
    await db.commit()
    row = await ai_settings_service.get_or_default(db, tenant.id)
    row.llm_model = "gpt-4o"
    row.effort_level = "custom"
    effective = await ai_settings_service.get_effective_model_async(db, row)
    target = await providers.resolve_generation_target(db, tenant.id, "gpt-4o")
    assert effective == target.model
    assert effective.startswith("claude")


async def test_pinning_a_disallowed_providers_model_is_refused(db, tenant, monkeypatch) -> None:
    from app.core.errors import AppError
    from app.modules.ai_settings.schemas import AISettingsUpdate

    _platform_keys(monkeypatch, anthropic="a", openai="o")
    monkeypatch.setattr(settings, "ai_processors_default", "anthropic")
    with pytest.raises(AppError) as exc:
        await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(llm_model=model_registry.BALANCED_MODELS["openai"])
        )
    assert exc.value.code == "ai_model_processor_not_allowed"


async def test_provider_statuses_mark_a_blocked_platform_provider(db, tenant, monkeypatch) -> None:
    _platform_keys(monkeypatch, anthropic="a", openai="o")
    monkeypatch.setattr(settings, "ai_processors_default", "anthropic")
    statuses = {s["provider"]: s for s in await providers.configured_providers(db, tenant.id)}
    assert statuses["openai"]["blocked"] is True
    assert statuses["openai"]["configured"] is False
    assert statuses["anthropic"]["blocked"] is False
    assert statuses["gemini"]["blocked"] is False  # no platform key: hidden, not blocked


async def test_configured_providers_byok_outside_the_list_is_not_blocked(
    db, tenant, monkeypatch
) -> None:
    """F3c: BYOK is never restricted by the processor list (HRP-1005 R4) —
    a tenant's own key for a provider the instance list disallows must
    still show as configured/byok, not blocked."""
    from app.core.crypto import encrypt_secret
    from app.modules.recruitment.models import LLMProviderConfig

    monkeypatch.setattr(settings, "ai_processors_default", "anthropic")
    db.add(
        LLMProviderConfig(
            tenant_id=tenant.id,
            provider="openai",
            model="gpt-4o",
            api_key_encrypted=encrypt_secret("sk-tenant-openai"),
            is_active=True,
        )
    )
    await db.commit()

    statuses = {
        s["provider"]: s for s in await providers.configured_providers(db, tenant.id)
    }
    assert statuses["openai"]["configured"] is True
    assert statuses["openai"]["source"] == "byok"
    assert statuses["openai"]["blocked"] is False


async def test_processors_endpoint_lists_allowed_keyed_processors(
    auth_client, tenant, db, monkeypatch
) -> None:
    _platform_keys(monkeypatch, anthropic="a", openai="o")
    monkeypatch.setattr(settings, "jev_api_key", "j")
    monkeypatch.setattr(settings, "ai_processors_default", "anthropic,jev,gemini")
    resp = await auth_client.get("/api/admin/ai-settings/processors")
    assert resp.status_code == 200
    assert [p["name"] for p in resp.json()] == ["anthropic", "jev"]


# --- Task 4: transcription and Jev reach only the list ---------------------


async def test_wrapper_lets_ai_no_allowed_processor_through(
    db, tenant, monkeypatch
) -> None:
    """F2: the blanket ``except Exception`` around generation calls used to
    repackage ``AppError("ai_no_allowed_processor")`` as a 502
    ``llm_generation_failed`` — the caller needs the real 409 to react to,
    not a generic upstream-failure code."""
    from app.core.errors import AppError
    from app.modules.ai import llm_client
    from app.modules.ai import service as ai_service

    async def _boom(*args, **kwargs):
        raise AppError("ai_no_allowed_processor", 409)

    monkeypatch.setattr(llm_client, "generate_json", _boom)
    with pytest.raises(AppError) as exc:
        await ai_service.generate_competences(db, tenant.id, None, "Engineer")
    assert exc.value.code == "ai_no_allowed_processor"
