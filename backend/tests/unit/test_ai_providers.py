"""HRP-465 — LLM provider registry, key-based gating, BYOK/local resolution."""

import asyncio
import uuid
from unittest.mock import patch

import pytest
from app.config import settings
from app.core.crypto import encrypt_secret
from app.core.errors import AppError
from app.modules.ai import model_registry, providers
from app.modules.ai.models import ModelCatalogEntry
from app.modules.recruitment.models import LLMProviderConfig
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _add_config(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    provider: str,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    is_active: bool = True,
) -> LLMProviderConfig:
    row = LLMProviderConfig(
        tenant_id=tenant_id,
        provider=provider,
        model=model,
        api_key_encrypted=encrypt_secret(api_key) if api_key else None,
        is_active=is_active,
        settings={"base_url": base_url} if base_url else None,
    )
    db.add(row)
    await db.commit()
    return row


def _no_global_keys():
    return patch.multiple(
        settings,
        anthropic_api_key="",
        openai_api_key="",
        gemini_api_key="",
        yandex_api_key="",
    )


# ---------------------------------------------------------------------------
# Registry / enum bridge
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_canonical_names_resolve_to_themselves(self) -> None:
        for name in providers.PROVIDERS:
            assert providers.resolve_provider_name(name) == name

    def test_recruitment_byok_names_all_resolve(self) -> None:
        # Bridge: every provider recruitment BYOK configs may store must map
        # onto a canonical spec — the resolver silently skips unknown rows.
        from typing import get_args

        from app.modules.recruitment.settings_schemas import LLMProviderName

        for name in get_args(LLMProviderName):
            assert providers.resolve_provider_name(name) is not None, name

    def test_ai_settings_provider_names_all_resolve(self) -> None:
        from typing import get_args

        from app.modules.ai_settings.schemas import LLMProvider

        for name in get_args(LLMProvider):
            assert providers.resolve_provider_name(name) is not None, name

    def test_classify_model(self) -> None:
        assert providers.classify_model("claude-sonnet-5") == "anthropic"
        assert providers.classify_model("gpt-4o") == "openai"
        assert providers.classify_model("gemini-2.5-pro") == "gemini"
        assert providers.classify_model("qwen2.5-72b") is None
        assert providers.classify_model(None) is None


# ---------------------------------------------------------------------------
# configured_providers matrix
# ---------------------------------------------------------------------------


class TestConfiguredProviders:
    async def test_nothing_configured(self, db: AsyncSession, tenant) -> None:
        with _no_global_keys():
            rows = await providers.configured_providers(db, tenant.id)
        assert all(not r["configured"] for r in rows)
        assert {r["provider"] for r in rows} == set(providers.PROVIDERS)

    async def test_global_key_only(self, db: AsyncSession, tenant) -> None:
        with (
            _no_global_keys(),
            patch.object(settings, "anthropic_api_key", "sk-ant-global"),
        ):
            rows = {
                r["provider"]: r
                for r in await providers.configured_providers(db, tenant.id)
            }
        assert rows["anthropic"]["configured"] is True
        assert rows["anthropic"]["source"] == "global"
        assert rows["openai"]["configured"] is False
        assert rows["gemini"]["configured"] is False
        assert rows["openai_compatible"]["configured"] is False

    async def test_byok_key_beats_global_source(self, db: AsyncSession, tenant) -> None:
        await _add_config(
            db, tenant.id, provider="openai", model="gpt-4o", api_key="sk-tenant"
        )
        with (
            _no_global_keys(),
            patch.object(settings, "openai_api_key", "sk-global"),
        ):
            rows = {
                r["provider"]: r
                for r in await providers.configured_providers(db, tenant.id)
            }
        assert rows["openai"]["configured"] is True
        assert rows["openai"]["source"] == "byok"

    async def test_local_base_url(self, db: AsyncSession, tenant) -> None:
        await _add_config(
            db,
            tenant.id,
            provider="openai_compatible",
            model="qwen2.5-72b",
            base_url="http://ollama.internal:11434/v1",
        )
        with _no_global_keys():
            rows = {
                r["provider"]: r
                for r in await providers.configured_providers(db, tenant.id)
            }
        assert rows["openai_compatible"]["configured"] is True
        assert rows["openai_compatible"]["source"] == "local"
        assert rows["openai_compatible"]["supports_local"] is True

    async def test_unreadable_key_is_not_reported_as_byok(
        self, db: AsyncSession, tenant
    ) -> None:
        """HRP-514: configured-ness was derived from a non-empty ciphertext.
        A key that no longer decrypts silently falls back to the platform
        key at generation time, so the UI must not show BYOK."""
        row = LLMProviderConfig(
            tenant_id=tenant.id,
            provider="anthropic",
            model="claude-sonnet-5",
            api_key_encrypted="not-a-valid-ciphertext",
            is_active=True,
        )
        db.add(row)
        await db.commit()

        with _no_global_keys():
            rows = {
                r["provider"]: r
                for r in await providers.configured_providers(db, tenant.id)
            }
        assert rows["anthropic"]["configured"] is False
        assert rows["anthropic"]["source"] is None
        assert rows["anthropic"]["key_status"] == "decrypt_failed"

        # With a platform key the tenant keeps generating — through the
        # global credential, which is what the UI must show.
        with (
            _no_global_keys(),
            patch.object(settings, "anthropic_api_key", "sk-ant-global"),
        ):
            rows = {
                r["provider"]: r
                for r in await providers.configured_providers(db, tenant.id)
            }
        assert rows["anthropic"]["source"] == "global"
        assert rows["anthropic"]["key_status"] == "decrypt_failed"

    async def test_readable_key_reports_ok_status(
        self, db: AsyncSession, tenant
    ) -> None:
        await _add_config(
            db, tenant.id, provider="gemini", model="gemini-2.5-pro", api_key="sk-gem"
        )
        with _no_global_keys():
            rows = {
                r["provider"]: r
                for r in await providers.configured_providers(db, tenant.id)
            }
        assert rows["gemini"]["source"] == "byok"
        assert rows["gemini"]["key_status"] == "ok"
        assert rows["openai"]["key_status"] is None

    async def test_key_status_does_not_leak_onto_a_local_row(
        self, db: AsyncSession, tenant
    ) -> None:
        """HRP-514 review: ``key_status`` was computed across the whole
        provider's row list, so a stale ciphertext on one row was still
        reported after the loop broke out on an unrelated local row — which
        needs no key at all."""
        from datetime import datetime, timezone

        broken = LLMProviderConfig(
            tenant_id=tenant.id,
            provider="openai_compatible",
            model="qwen2.5-72b",
            api_key_encrypted="not-a-valid-ciphertext",
            is_active=True,
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        local = LLMProviderConfig(
            tenant_id=tenant.id,
            provider="openai_compatible",
            model="qwen2.5-72b",
            is_active=True,
            settings={"base_url": "http://ollama.internal:11434/v1"},
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        db.add_all([broken, local])
        await db.commit()

        with _no_global_keys():
            rows = {
                r["provider"]: r
                for r in await providers.configured_providers(db, tenant.id)
            }
        assert rows["openai_compatible"]["source"] == "local"
        assert rows["openai_compatible"]["key_status"] is None

    async def test_inactive_rows_are_ignored(self, db: AsyncSession, tenant) -> None:
        await _add_config(
            db,
            tenant.id,
            provider="anthropic",
            model="claude-sonnet-5",
            api_key="sk-old",
            is_active=False,
        )
        with _no_global_keys():
            rows = {
                r["provider"]: r
                for r in await providers.configured_providers(db, tenant.id)
            }
        assert rows["anthropic"]["configured"] is False


# ---------------------------------------------------------------------------
# resolve_generation_target
# ---------------------------------------------------------------------------


class TestResolveGenerationTarget:
    async def test_byok_key_wins_over_global(self, db: AsyncSession, tenant) -> None:
        await _add_config(
            db,
            tenant.id,
            provider="anthropic",
            model="claude-sonnet-5",
            api_key="sk-tenant-key",
        )
        with patch.object(settings, "anthropic_api_key", "sk-global"):
            target = await providers.resolve_generation_target(
                db, tenant.id, "claude-sonnet-5"
            )
        assert target.provider == "anthropic"
        assert target.api_key == "sk-tenant-key"
        assert target.source == "byok"

    async def test_provider_match_without_exact_model(
        self, db: AsyncSession, tenant
    ) -> None:
        # Tenant stored a key for Anthropic under one model; any Claude
        # model borrows the key, but never the row's model.
        await _add_config(
            db,
            tenant.id,
            provider="anthropic",
            model="claude-opus-4-8",
            api_key="sk-tenant-key",
        )
        target = await providers.resolve_generation_target(
            db, tenant.id, "claude-sonnet-5"
        )
        assert target.provider == "anthropic"
        assert target.api_key == "sk-tenant-key"

    async def test_no_rows_falls_back_to_global(self, db: AsyncSession, tenant) -> None:
        target = await providers.resolve_generation_target(
            db, tenant.id, "claude-sonnet-5"
        )
        assert target.provider == "anthropic"
        assert target.api_key is None  # None → global env key at client build
        assert target.source == "global"

    async def test_local_model_matches_by_exact_name(
        self, db: AsyncSession, tenant
    ) -> None:
        await _add_config(
            db,
            tenant.id,
            provider="openai_compatible",
            model="qwen2.5-72b",
            base_url="http://vllm.internal:8000/v1",
        )
        target = await providers.resolve_generation_target(db, tenant.id, "qwen2.5-72b")
        assert target.provider == "openai_compatible"
        assert target.base_url == "http://vllm.internal:8000/v1"
        assert target.source == "local"

    async def test_no_model_picks_tenant_config_with_model(
        self, db: AsyncSession, tenant
    ) -> None:
        # Recruitment pipeline passes no model — the tenant's configured
        # provider supplies both the credentials and the model.
        await _add_config(
            db,
            tenant.id,
            provider="gemini",
            model="gemini-2.5-pro",
            api_key="sk-gem",
        )
        target = await providers.resolve_generation_target(db, tenant.id, None)
        assert target.provider == "gemini"
        assert target.api_key == "sk-gem"
        assert target.model == "gemini-2.5-pro"

    async def test_azure_alias_needs_base_url(self, db: AsyncSession, tenant) -> None:
        # Azure is treated as OpenAI-compatible; without a base_url the row
        # cannot be dispatched and the platform default applies.
        await _add_config(
            db, tenant.id, provider="azure", model="gpt-4o", api_key="sk-azure"
        )
        target = await providers.resolve_generation_target(db, tenant.id, "gpt-4o")
        assert target.source == "global"

        await _add_config(
            db,
            tenant.id,
            provider="azure",
            model="gpt-4o",
            api_key="sk-azure",
            base_url="https://acme.openai.azure.example/v1",
        )
        target = await providers.resolve_generation_target(db, tenant.id, "gpt-4o")
        assert target.provider == "openai_compatible"
        assert target.base_url == "https://acme.openai.azure.example/v1"
        assert target.api_key == "sk-azure"

    async def test_mismatched_row_is_not_dispatched_without_a_model(
        self, db: AsyncSession, tenant
    ) -> None:
        """HRP-498: a legacy {provider: openai, model: claude-…} row must
        not become the recruitment pipeline's dispatch target — OpenAI
        would 404 on a Claude model."""
        await _add_config(
            db,
            tenant.id,
            provider="openai",
            model="claude-sonnet-5",
            api_key="sk-tenant",
        )
        target = await providers.resolve_generation_target(db, tenant.id, None)
        assert target.source == "global"
        assert target.model is None

    async def test_consistent_row_still_dispatches_without_a_model(
        self, db: AsyncSession, tenant
    ) -> None:
        await _add_config(
            db,
            tenant.id,
            provider="openai",
            model="gpt-4o",
            api_key="sk-tenant",
        )
        target = await providers.resolve_generation_target(db, tenant.id, None)
        assert target.source == "byok"
        assert target.model == "gpt-4o"

    async def test_local_row_without_classifiable_model_still_dispatches(
        self, db: AsyncSession, tenant
    ) -> None:
        await _add_config(
            db,
            tenant.id,
            provider="openai_compatible",
            model="qwen2.5-72b",
            base_url="http://vllm.internal:8000/v1",
        )
        target = await providers.resolve_generation_target(db, tenant.id, None)
        assert target.source == "local"
        assert target.model == "qwen2.5-72b"

    async def test_mismatched_row_is_not_dispatched_for_its_exact_model(
        self, db: AsyncSession, tenant
    ) -> None:
        """HRP-498 review: the consistency guard only ran in the *no model
        requested* branch, so asking for gpt-4o still picked an
        {anthropic, gpt-4o} row and sent gpt-4o to Anthropic."""
        await _add_config(
            db,
            tenant.id,
            provider="anthropic",
            model="gpt-4o",
            api_key="sk-tenant",
        )
        target = await providers.resolve_generation_target(db, tenant.id, "gpt-4o")
        assert target.source == "global"
        assert target.provider == "openai"

    async def test_proxy_row_is_consistent_with_an_upstream_model(
        self, db: AsyncSession, tenant
    ) -> None:
        # openai_compatible owns no prefix and a base_url row is defined by
        # its endpoint — neither may be read as a mismatch (HRP-498 review).
        azure = await _add_config(
            db,
            tenant.id,
            provider="azure",
            model="gpt-4o",
            api_key="sk-azure",
            base_url="https://acme.openai.azure.example/v1",
        )
        assert providers.row_is_consistent(azure) is True
        assert providers.model_matches_provider("azure", "claude-sonnet-5") is True
        assert (
            providers.model_matches_provider(
                "openai", "claude-sonnet-5", "https://litellm.example/v1"
            )
            is True
        )
        assert providers.model_matches_provider("openai", "claude-sonnet-5") is False
        assert providers.model_matches_provider("openai", "gpt-4o") is True
        assert providers.model_matches_provider("openai", "qwen2.5-72b") is True

    async def test_sync_resolver_matches_async(self) -> None:
        # The sync twin shares _pick_target — a smoke check that it exists
        # and produces the fallback shape without a DB.
        fallback = providers._fallback_target("claude-sonnet-5")
        assert fallback.provider == "anthropic"
        assert fallback.source == "global"


# ---------------------------------------------------------------------------
# HRP-502: a model no prefix owns must not ride the platform default
# ---------------------------------------------------------------------------


class TestUnclassifiableModelDispatch:
    """Both resolvers funnel through ``_fallback_target``, so the routing
    decision is asserted there; the async path additionally proves the
    catalog lookup is wired in."""

    async def test_unknown_model_is_refused_when_the_default_has_no_key(
        self, db: AsyncSession, tenant
    ) -> None:
        """Nothing can serve it — a clear 422 beats a provider auth error."""
        with (
            patch.object(settings, "llm_provider", "anthropic"),
            patch.object(settings, "anthropic_api_key", ""),
            pytest.raises(AppError) as exc,
        ):
            await providers.resolve_generation_target(db, tenant.id, "mystery-9000")
        assert exc.value.status_code == 422
        assert exc.value.code == "llm_model_provider_unresolved"

    async def test_a_configured_default_still_takes_an_unknown_name(
        self, db: AsyncSession, tenant
    ) -> None:
        """Review fix: an install on OpenAI with a key has always served
        new OpenAI families whose prefix this table does not know yet —
        refusing those would break a working setup."""
        with (
            patch.object(settings, "llm_provider", "openai"),
            patch.object(settings, "openai_api_key", "sk-global"),
        ):
            target = await providers.resolve_generation_target(
                db, tenant.id, "chatgpt-brand-new"
            )
        assert target.provider == "openai"
        assert target.source == "global"

    def test_the_silent_celery_path_keeps_working(self) -> None:
        """ai/tasks.py resolves with no model pinned and no session of its
        own — that path must never raise."""
        with (
            patch.object(settings, "llm_provider", "anthropic"),
            patch.object(settings, "anthropic_api_key", ""),
        ):
            assert providers._fallback_target(None).provider == "anthropic"

    async def test_catalog_resolves_a_model_no_prefix_owns(
        self, db: AsyncSession, tenant
    ) -> None:
        # A newly named OpenAI family the prefix table has never heard of:
        # the discovery sweep recorded whose API listed it.
        db.add(
            ModelCatalogEntry(
                provider="openai",
                model_id="chatgpt-next",
                label="ChatGPT Next",
                status="approved",
                enabled=True,
                source="discovered",
            )
        )
        await db.commit()

        with patch.object(settings, "llm_provider", "anthropic"):
            target = await providers.resolve_generation_target(
                db, tenant.id, "chatgpt-next"
            )
        assert target.provider == "openai"
        assert target.source == "global"

    async def test_prefix_still_wins_without_touching_the_catalog(
        self, db: AsyncSession, tenant
    ) -> None:
        # A classifiable id must not pay for a catalog query.
        from app.modules.ai import model_catalog_service

        with patch.object(
            model_catalog_service,
            "provider_for_model",
            side_effect=AssertionError("catalog queried for a classifiable model"),
        ):
            target = await providers.resolve_generation_target(
                db, tenant.id, "gemini-2.5-pro"
            )
        assert target.provider == "gemini"

    async def test_no_model_requested_still_uses_the_platform_default(
        self, db: AsyncSession, tenant
    ) -> None:
        # The recruitment pipeline pins no model — that is not an error.
        with patch.object(settings, "llm_provider", "anthropic"):
            target = await providers.resolve_generation_target(db, tenant.id, None)
        assert target.provider == "anthropic"

    def test_a_local_default_may_serve_arbitrary_names(self) -> None:
        # Self-hosted installs name their models freely; refusing there
        # would break the very setup that has no prefix to match.
        with patch.object(settings, "llm_provider", "openai_compatible"):
            target = providers._fallback_target("qwen2.5-72b")
        assert target.provider == "openai_compatible"

    def test_catalog_answer_is_honoured_by_the_shared_fallback(self) -> None:
        with patch.object(settings, "llm_provider", "anthropic"):
            target = providers._fallback_target("mystery-9000", "gemini")
        assert target.provider == "gemini"

    def test_catalog_answer_is_canonicalized(self) -> None:
        # Catalog rows may carry a legacy provider name.
        with patch.object(settings, "llm_provider", "anthropic"):
            target = providers._fallback_target("mystery-9000", "claude")
        assert target.provider == "anthropic"


# ---------------------------------------------------------------------------
# Yandex as a first-class provider (HRP-599)
# ---------------------------------------------------------------------------


class TestYandexProvider:
    def test_yandex_is_canonical_not_an_alias(self) -> None:
        assert "yandex" in providers.PROVIDERS
        assert providers.resolve_provider_name("yandex") == "yandex"

    def test_classify_yandex_models(self) -> None:
        assert providers.classify_model("yandexgpt") == "yandex"
        assert providers.classify_model("yandexgpt-lite") == "yandex"
        # The model-URI scheme shares its first three characters with the
        # OpenAI prefix — the longest matching prefix must win.
        assert providers.classify_model("gpt://b1gfolder/yandexgpt/latest") == "yandex"
        assert providers.classify_model("gpt-4o") == "openai"

    def test_global_key_reads_yandex_setting(self) -> None:
        with patch.object(settings, "yandex_api_key", "ya-global"):
            assert providers.global_key("yandex") == "ya-global"

    async def test_yandex_model_falls_back_to_platform_key(
        self, db: AsyncSession, tenant
    ) -> None:
        target = await providers.resolve_generation_target(db, tenant.id, "yandexgpt")
        assert target.provider == "yandex"
        assert target.source == "global"

    async def test_base_url_row_keeps_endpoint_and_yandex_dispatch(
        self, db: AsyncSession, tenant
    ) -> None:
        # Rows saved while "yandex" was an openai_compatible alias carry a
        # base_url — the endpoint is preserved, and the yandex dispatch
        # path keeps expanding model URIs (review fix: relabeling these
        # rows openai_compatible skipped the URI expansion entirely).
        await _add_config(
            db,
            tenant.id,
            provider="yandex",
            model="gpt://b1gfolder/yandexgpt/latest",
            api_key="ya-tenant",
            base_url="https://llm.api.cloud.yandex.net/v1",
        )
        target = await providers.resolve_generation_target(
            db, tenant.id, "gpt://b1gfolder/yandexgpt/latest"
        )
        assert target.provider == "yandex"
        assert target.base_url == "https://llm.api.cloud.yandex.net/v1"
        assert target.api_key == "ya-tenant"
        assert target.source == "local"

    async def test_byok_key_with_full_uri_model(self, db: AsyncSession, tenant) -> None:
        # Yandex keys are folder-scoped — a tenant config is self-contained
        # only when the model URI carries the tenant's folder.
        await _add_config(
            db,
            tenant.id,
            provider="yandex",
            model="gpt://b1gtenant/yandexgpt/latest",
            api_key="ya-tenant",
        )
        target = await providers.resolve_generation_target(
            db, tenant.id, "gpt://b1gtenant/yandexgpt/latest"
        )
        assert target.provider == "yandex"
        assert target.api_key == "ya-tenant"
        assert target.source == "byok"

    async def test_byok_short_name_row_is_skipped(
        self, db: AsyncSession, tenant
    ) -> None:
        # A short-name BYOK row would pair the tenant's folder-scoped key
        # with the operator's folder id — like a base_url-less local row,
        # it is misconfigured and must fall back to the platform credential
        # (which is also what these rows did in the alias era).
        await _add_config(
            db, tenant.id, provider="yandex", model="yandexgpt", api_key="ya-tenant"
        )
        target = await providers.resolve_generation_target(db, tenant.id, "yandexgpt")
        assert target.provider == "yandex"
        assert target.api_key is None
        assert target.source == "global"


class TestYandexDispatch:
    async def test_short_model_name_expands_to_folder_uri(
        self, monkeypatch, fake_openai_factory
    ) -> None:
        from app.modules.ai import llm_client

        captured: dict = {}
        monkeypatch.setattr(llm_client.settings, "yandex_api_key", "ya-global")
        monkeypatch.setattr(llm_client.settings, "yandex_folder_id", "b1gfolder")
        with patch.object(
            llm_client, "_get_openai", return_value=fake_openai_factory(captured)
        ) as get_openai:
            out = await llm_client.generate("hi", model="yandexgpt")
        assert out == "ok"
        get_openai.assert_called_once_with("ya-global", llm_client.YANDEX_BASE_URL)
        assert captured["model"] == "gpt://b1gfolder/yandexgpt/latest"

    async def test_full_model_uri_passes_verbatim(
        self, monkeypatch, fake_openai_factory
    ) -> None:
        # A full URI carries its own folder — no folder config required.
        from app.modules.ai import llm_client

        captured: dict = {}
        monkeypatch.setattr(llm_client.settings, "yandex_api_key", "ya-global")
        monkeypatch.setattr(llm_client.settings, "yandex_folder_id", "")
        with patch.object(
            llm_client, "_get_openai", return_value=fake_openai_factory(captured)
        ):
            await llm_client.generate(
                "hi", model="gpt://b1gother/yandexgpt-lite/latest"
            )
        assert captured["model"] == "gpt://b1gother/yandexgpt-lite/latest"

    async def test_byok_credentials_reach_the_client(
        self, monkeypatch, fake_openai_factory
    ) -> None:
        from app.modules.ai import llm_client

        captured: dict = {}
        monkeypatch.setattr(llm_client.settings, "yandex_api_key", "ya-platform")
        target = providers.GenerationTarget(
            provider="yandex", api_key="ya-byok", source="byok"
        )
        with patch.object(
            llm_client, "_get_openai", return_value=fake_openai_factory(captured)
        ) as get_openai:
            await llm_client.generate(
                "hi", model="gpt://b1gtenant/yandexgpt/latest", credentials=target
            )
        get_openai.assert_called_once_with("ya-byok", llm_client.YANDEX_BASE_URL)

    async def test_tenant_endpoint_never_gets_the_platform_key(
        self, monkeypatch, fake_openai_factory
    ) -> None:
        # A keyless row pointing at a tenant endpoint must not inherit the
        # platform Yandex key (same invariant as the OpenAI factory).
        from app.modules.ai import llm_client

        captured: dict = {}
        monkeypatch.setattr(llm_client.settings, "yandex_api_key", "ya-platform")
        target = providers.GenerationTarget(
            provider="yandex",
            base_url="https://proxy.example/v1",
            source="local",
        )
        with patch.object(
            llm_client, "_get_openai", return_value=fake_openai_factory(captured)
        ) as get_openai:
            await llm_client.generate(
                "hi", model="gpt://b1gfolder/yandexgpt/latest", credentials=target
            )
        get_openai.assert_called_once_with(None, "https://proxy.example/v1")

    async def test_gateway_row_short_model_passes_verbatim(
        self, monkeypatch, fake_openai_factory
    ) -> None:
        # Alias-era gateway rows store short names and the endpoint owns
        # the model namespace: no folder expansion (which would leak the
        # operator's folder id to a tenant endpoint) and no folder
        # requirement (which would 422 every pre-existing install).
        from app.modules.ai import llm_client

        captured: dict = {}
        monkeypatch.setattr(llm_client.settings, "yandex_folder_id", "")
        target = providers.GenerationTarget(
            provider="yandex",
            base_url="https://gateway.example/v1",
            source="local",
        )
        with patch.object(
            llm_client, "_get_openai", return_value=fake_openai_factory(captured)
        ):
            await llm_client.generate("hi", model="yandexgpt", credentials=target)
        assert captured["model"] == "yandexgpt"

    async def test_missing_folder_is_a_config_error(self, monkeypatch) -> None:
        from app.modules.ai import llm_client

        monkeypatch.setattr(llm_client.settings, "yandex_api_key", "ya-global")
        monkeypatch.setattr(llm_client.settings, "yandex_folder_id", "")
        with (
            patch.object(llm_client, "_get_openai"),
            pytest.raises(AppError) as exc,
        ):
            await llm_client.generate("hi", model="yandexgpt")
        assert exc.value.code == "llm_yandex_folder_missing"

    async def test_missing_platform_key_is_a_config_error(self, monkeypatch) -> None:
        # Review fix: an empty key used to ride the _get_openai "not-needed"
        # hatch and come back as an opaque upstream 401.
        from app.modules.ai import llm_client

        monkeypatch.setattr(llm_client.settings, "yandex_api_key", "")
        monkeypatch.setattr(llm_client.settings, "yandex_folder_id", "b1gfolder")
        with (
            patch.object(llm_client, "_get_openai"),
            pytest.raises(AppError) as exc,
        ):
            await llm_client.generate("hi", model="yandexgpt")
        assert exc.value.code == "llm_yandex_key_missing"

    async def test_foreign_scheme_model_passes_verbatim(
        self, monkeypatch, fake_openai_factory
    ) -> None:
        # Tuned models come as ds:// URIs — nesting them inside gpt:// would
        # mangle them into a provider-side 404 (review fix).
        from app.modules.ai import llm_client

        captured: dict = {}
        monkeypatch.setattr(llm_client.settings, "yandex_api_key", "ya-global")
        monkeypatch.setattr(llm_client.settings, "yandex_folder_id", "b1gfolder")
        target = providers.GenerationTarget(provider="yandex")
        with patch.object(
            llm_client, "_get_openai", return_value=fake_openai_factory(captured)
        ):
            await llm_client.generate(
                "hi", model="ds://b1gfolder/tuned-1", credentials=target
            )
        assert captured["model"] == "ds://b1gfolder/tuned-1"

    def test_platform_endpoint_client_keeps_sdk_retries(self) -> None:
        # The hardcoded platform endpoint is not a tenant-supplied URL: it
        # must keep the SDK transport and its 3 retries instead of the
        # SSRF-guarded zero-retry client (review fix).
        from app.modules.ai import llm_client

        llm_client._client_cache.clear()
        client = llm_client._get_openai("ya-key", llm_client.YANDEX_BASE_URL)
        assert client.max_retries == 3
        llm_client._client_cache.clear()

    def test_platform_default_model(self) -> None:
        from app.modules.ai import llm_client

        with (
            patch.object(settings, "llm_provider", "yandex"),
            patch.object(settings, "yandex_api_key", "ya-global"),
        ):
            assert llm_client._get_default_model() == "yandexgpt"

    def test_default_model_accepts_canonical_provider_names(self) -> None:
        # LLM_PROVIDER=anthropic is legal everywhere else in the platform;
        # the default-model lookup must not silently hand it gpt-4o.
        from app.modules.ai import llm_client

        with (
            patch.object(settings, "llm_provider", "anthropic"),
            patch.object(settings, "anthropic_api_key", "sk-ant"),
        ):
            assert (
                llm_client._get_default_model()
                == model_registry.BALANCED_MODELS["anthropic"]
            )

    async def test_keyless_default_falls_back_to_openai_entirely(
        self, monkeypatch, fake_openai_factory
    ) -> None:
        # LLM_PROVIDER=yandex without a key: the default model falls back
        # to OpenAI — the provider must follow the model, not stay yandex
        # and mangle gpt-4o into a gpt:// URI (review fix).
        from app.modules.ai import llm_client

        captured: dict = {}
        monkeypatch.setattr(llm_client.settings, "llm_provider", "yandex")
        monkeypatch.setattr(llm_client.settings, "yandex_api_key", "")
        with patch.object(
            llm_client, "_get_openai", return_value=fake_openai_factory(captured)
        ) as get_openai:
            await llm_client.generate("hi")
        get_openai.assert_called_once_with(None, None)
        assert captured["model"] == model_registry.BALANCED_MODELS["openai"]


# ---------------------------------------------------------------------------
# llm_client dispatch honours resolved credentials
# ---------------------------------------------------------------------------


class TestLLMClientDispatch:
    async def test_credentials_route_to_local_openai(self, fake_openai_factory) -> None:
        from app.modules.ai import llm_client

        captured: dict = {}
        fake_client = fake_openai_factory(captured)
        target = providers.GenerationTarget(
            provider="openai_compatible",
            api_key="local-key",
            base_url="http://ollama.internal:11434/v1",
            source="local",
            model="qwen2.5-72b",
        )
        with patch.object(
            llm_client, "_get_openai", return_value=fake_client
        ) as get_openai:
            out = await llm_client.generate("hi", credentials=target)
        assert out == "ok"
        get_openai.assert_called_once_with(
            "local-key", "http://ollama.internal:11434/v1"
        )
        # No model was requested — the local config's model applies, and the
        # local path must not clamp max_tokens with the gpt-4o table.
        assert captured["model"] == "qwen2.5-72b"
        assert captured["max_tokens"] == 8192

    async def test_credentials_api_key_reaches_anthropic_factory(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from app.modules.ai import llm_client

        response = SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(text="ok")]
        )
        fake_client = SimpleNamespace(
            messages=SimpleNamespace(create=AsyncMock(return_value=response))
        )
        target = providers.GenerationTarget(
            provider="anthropic", api_key="sk-byok", source="byok"
        )
        with patch.object(
            llm_client, "_get_anthropic", return_value=fake_client
        ) as get_anthropic:
            out = await llm_client.generate(
                "hi", model="claude-sonnet-5", credentials=target
            )
        assert out == "ok"
        get_anthropic.assert_called_once_with("sk-byok")

    async def test_client_cache_is_keyed_by_key_fingerprint(self) -> None:
        from app.modules.ai import llm_client

        llm_client._client_cache.clear()
        a = llm_client._get_anthropic("sk-one")
        b = llm_client._get_anthropic("sk-one")
        c = llm_client._get_anthropic("sk-two")
        assert a is b
        assert a is not c
        llm_client._client_cache.clear()

    async def test_client_cache_is_bounded_and_closes_evicted(
        self, monkeypatch
    ) -> None:
        """HRP-501: the cache used to be an unbounded dict — every rotated
        BYOK key left its connection pool behind for the process lifetime.
        It is an LRU now, and the evicted client is closed."""
        from app.modules.ai import llm_client

        # The close is deferred by a grace period in production; collapse it
        # so the eviction is observable in one loop turn.
        monkeypatch.setattr(llm_client, "_EVICTED_CLIENT_GRACE_S", 0)
        llm_client._client_cache.clear()
        closed: list[str] = []

        class _FakeClient:
            def __init__(self, name: str) -> None:
                self.name = name

            async def close(self) -> None:
                closed.append(self.name)

        for i in range(llm_client._CLIENT_CACHE_MAX):
            llm_client._cache_put(("openai", f"fp{i}", ""), _FakeClient(f"fp{i}"))
        assert len(llm_client._client_cache) == llm_client._CLIENT_CACHE_MAX

        # Touch the oldest entry so the LRU order — not insertion order —
        # decides who leaves.
        llm_client._cache_get(("openai", "fp0", ""))
        llm_client._cache_put(("openai", "overflow", ""), _FakeClient("overflow"))

        await asyncio.sleep(0.05)  # let the deferred close task run
        assert len(llm_client._client_cache) == llm_client._CLIENT_CACHE_MAX
        assert closed == ["fp1"]
        assert llm_client._cache_get(("openai", "fp0", "")) is not None
        assert llm_client._cache_get(("openai", "fp1", "")) is None
        llm_client._client_cache.clear()

    async def test_eviction_does_not_close_under_an_in_flight_request(self) -> None:
        """HRP-501 review: closing on eviction tore the connection pool out
        from under a generation that was still running (up to 1800 s on the
        streaming path) — and the create_task handle was dropped, so the
        close could also be garbage-collected before it ran."""
        from app.modules.ai import llm_client

        llm_client._client_cache.clear()
        closed: list[str] = []

        class _FakeClient:
            def __init__(self, name: str) -> None:
                self.name = name

            async def close(self) -> None:
                closed.append(self.name)

        for i in range(llm_client._CLIENT_CACHE_MAX):
            llm_client._cache_put(("openai", f"fp{i}", ""), _FakeClient(f"fp{i}"))
        llm_client._cache_put(("openai", "overflow", ""), _FakeClient("overflow"))

        await asyncio.sleep(0)
        assert closed == []  # still inside the grace window
        pending = [t for t in llm_client._pending_closes if not t.done()]
        assert pending, "the deferred close must be strong-referenced"

        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        # Cancellation means the loop is going away — the pool is released
        # rather than leaked into the next task on this worker.
        assert closed == ["fp0"]
        llm_client._client_cache.clear()

    async def test_platform_key_never_sent_to_tenant_base_url(
        self, monkeypatch
    ) -> None:
        """A keyless row with a tenant base_url must not inherit the
        platform OpenAI key — it would leak as a Bearer token to an
        arbitrary host (white-label-fleet review, finding #1)."""
        from app.modules.ai import llm_client

        monkeypatch.setattr(llm_client.settings, "openai_api_key", "sk-platform-secret")
        llm_client._client_cache.clear()
        leaked = llm_client._get_openai(
            api_key=None, base_url="https://attacker.example/v1"
        )
        assert leaked.api_key == "not-needed"
        # Without a base_url the platform key still applies (global config).
        default = llm_client._get_openai(api_key=None, base_url=None)
        assert default.api_key == "sk-platform-secret"
        # A row that carries both its own key and a base_url uses the row
        # key — never the platform one.
        byok = llm_client._get_openai(
            api_key="sk-tenant-row", base_url="https://ollama.internal/v1"
        )
        assert byok.api_key == "sk-tenant-row"
        llm_client._client_cache.clear()
