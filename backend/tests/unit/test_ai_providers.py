"""HRP-465 — LLM provider registry, key-based gating, BYOK/local resolution."""

import asyncio
import uuid
from unittest.mock import patch

import pytest
from app.config import settings
from app.core.crypto import encrypt_secret
from app.modules.ai import providers
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
        settings, anthropic_api_key="", openai_api_key="", gemini_api_key=""
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
# llm_client dispatch honours resolved credentials
# ---------------------------------------------------------------------------


class TestLLMClientDispatch:
    async def test_credentials_route_to_local_openai(self) -> None:
        from types import SimpleNamespace

        from app.modules.ai import llm_client

        captured: dict = {}

        class _FakeCompletions:
            async def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            finish_reason="stop",
                            message=SimpleNamespace(content="ok"),
                        )
                    ]
                )

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=_FakeCompletions())
        )
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
