"""Phase CR10b — TenantAISettings model, service, and router."""

import uuid

import pytest
import pytest_asyncio
from app.core.security import create_access_token, hash_password
from app.modules.ai_settings import service
from app.modules.ai_settings.models import TenantAISettings
from app.modules.ai_settings.schemas import AISettingsUpdate
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


class TestServiceLazyCreate:
    async def test_get_or_default_creates_row(self, db: AsyncSession, tenant) -> None:
        row = await service.get_or_default(db, tenant.id)
        assert row.tenant_id == tenant.id
        assert row.content_language == "en"
        assert row.effort_level == "balanced"
        assert row.temperature == 0.3
        assert row.max_retries == 5
        assert row.llm_model is None
        assert row.company_context is None

    async def test_get_or_default_returns_existing(
        self, db: AsyncSession, tenant
    ) -> None:
        first = await service.get_or_default(db, tenant.id)
        second = await service.get_or_default(db, tenant.id)
        assert first.id == second.id


class TestServiceUpdate:
    async def test_apply_preset_thorough_changes_temperature_and_retries(
        self, db: AsyncSession, tenant
    ) -> None:
        row = await service.update(
            db, tenant.id, AISettingsUpdate(effort_level="thorough")
        )
        assert row.effort_level == "thorough"
        assert row.temperature == 0.2
        assert row.max_retries == 7

    async def test_explicit_temperature_flips_to_custom(
        self, db: AsyncSession, tenant
    ) -> None:
        row = await service.update(db, tenant.id, AISettingsUpdate(temperature=0.9))
        assert row.effort_level == "custom"
        assert row.temperature == 0.9

    async def test_explicit_max_retries_flips_to_custom(
        self, db: AsyncSession, tenant
    ) -> None:
        row = await service.update(db, tenant.id, AISettingsUpdate(max_retries=8))
        assert row.effort_level == "custom"
        assert row.max_retries == 8

    async def test_explicit_llm_model_flips_to_custom(
        self, db: AsyncSession, tenant
    ) -> None:
        row = await service.update(
            db, tenant.id, AISettingsUpdate(llm_model="claude-opus-4-8")
        )
        assert row.effort_level == "custom"
        assert row.llm_model == "claude-opus-4-8"

    async def test_company_context_persists(self, db: AsyncSession, tenant) -> None:
        row = await service.update(
            db, tenant.id, AISettingsUpdate(company_context="Acme Corp")
        )
        assert row.company_context == "Acme Corp"
        assert row.effort_level == "balanced"  # context alone is not "custom"


class TestServiceModelWhitelist:
    """CR10c — only models from `list_allowed_models()` may be assigned."""

    async def test_known_model_accepted(self, db: AsyncSession, tenant) -> None:
        row = await service.update(
            db, tenant.id, AISettingsUpdate(llm_model="claude-haiku-4-5-20251001")
        )
        assert row.llm_model == "claude-haiku-4-5-20251001"

    async def test_unknown_model_rejected(self, db: AsyncSession, tenant) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await service.update(
                db, tenant.id, AISettingsUpdate(llm_model="gpt-5-imaginary")
            )
        assert exc.value.status_code == 422

    async def test_null_model_resets_override(self, db: AsyncSession, tenant) -> None:
        await service.update(
            db, tenant.id, AISettingsUpdate(llm_model="claude-opus-4-8")
        )
        row = await service.update(db, tenant.id, AISettingsUpdate(llm_model=None))
        assert row.llm_model is None

    async def test_list_allowed_models_returns_at_least_preset_models(
        self,
    ) -> None:
        whitelist = service.list_allowed_models()
        models = {entry["model"] for entry in whitelist}
        # Every model in EFFORT_PRESETS must be selectable.
        for preset in service.EFFORT_PRESETS.values():
            for provider_model in preset["models"].values():
                assert provider_model in models

    async def test_effective_credit_multiplier_default_is_one(
        self, db: AsyncSession, tenant
    ) -> None:
        row = await service.get_or_default(db, tenant.id)
        # Balanced preset, default whitelist — sonnet should be 1.0×.
        assert service.get_effective_credit_multiplier(row) == pytest.approx(1.0)


class TestServiceReset:
    async def test_reset_returns_defaults(self, db: AsyncSession, tenant) -> None:
        await service.update(
            db,
            tenant.id,
            AISettingsUpdate(
                effort_level="thorough",
                company_context="Acme",
                llm_model="claude-opus-4-8",
            ),
        )
        row = await service.reset(db, tenant.id)
        assert row.effort_level == "balanced"
        assert row.content_language == "en"
        assert row.company_context is None
        assert row.llm_model is None
        assert row.temperature == 0.3
        assert row.max_retries == 5


class TestEffectiveResolvers:
    async def test_effective_temperature_uses_preset_for_fast(
        self, db: AsyncSession, tenant
    ) -> None:
        row = await service.update(db, tenant.id, AISettingsUpdate(effort_level="fast"))
        assert service.get_effective_temperature(row) == 0.5

    async def test_effective_temperature_uses_stored_for_custom(
        self, db: AsyncSession, tenant
    ) -> None:
        row = await service.update(db, tenant.id, AISettingsUpdate(temperature=0.9))
        assert service.get_effective_temperature(row) == 0.9

    async def test_effective_model_uses_preset(self, db: AsyncSession, tenant) -> None:
        row = await service.update(
            db, tenant.id, AISettingsUpdate(effort_level="thorough")
        )
        assert service.get_effective_model(row) == "claude-opus-4-8"

    async def test_effective_model_uses_override(
        self, db: AsyncSession, tenant
    ) -> None:
        row = await service.update(db, tenant.id, AISettingsUpdate(llm_model="gpt-4o"))
        assert service.get_effective_model(row) == "gpt-4o"
        assert service.get_effective_provider(row) == "openai"


class TestSystemPromptExtras:
    async def test_language_directive_default_english(
        self, db: AsyncSession, tenant
    ) -> None:
        row = await service.get_or_default(db, tenant.id)
        directive = service.build_language_directive(row)
        assert "English" in directive

    async def test_extras_include_company_context(
        self, db: AsyncSession, tenant
    ) -> None:
        row = await service.update(
            db, tenant.id, AISettingsUpdate(company_context="Acme Corp")
        )
        extras = service.build_system_prompt_extras(row)
        assert any("Acme Corp" in part for part in extras)
        assert any("English" in part for part in extras)

    async def test_language_directive_german(self, db: AsyncSession, tenant) -> None:
        row = await service.update(
            db, tenant.id, AISettingsUpdate(content_language="de")
        )
        assert "German" in service.build_language_directive(row)

    async def test_language_directive_unknown_code_falls_back_to_english(
        self, db: AsyncSession, tenant
    ) -> None:
        # The DB CHECK is gone (HRP-480); a row carrying a code the service
        # does not know must still yield a safe English directive.
        row = await service.get_or_default(db, tenant.id)
        row.content_language = "xx"
        assert "English" in service.build_language_directive(row)

    async def test_to_read_dict_normalizes_unknown_language(
        self, db: AsyncSession, tenant
    ) -> None:
        # Same scenario at the read boundary: an out-of-contract value must
        # not break GET/PATCH via response_model validation.
        row = await service.get_or_default(db, tenant.id)
        row.content_language = "xx"
        assert service.to_read_dict(row)["content_language"] == "en"


class TestUniqueConstraint:
    async def test_duplicate_tenant_row_rejected(
        self, db: AsyncSession, tenant
    ) -> None:
        await service.get_or_default(db, tenant.id)
        duplicate = TenantAISettings(tenant_id=tenant.id)
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestRouterGet:
    async def test_get_creates_lazy_row(
        self, auth_client: AsyncClient, db: AsyncSession, tenant
    ) -> None:
        existing = await db.execute(
            select(TenantAISettings).where(TenantAISettings.tenant_id == tenant.id)
        )
        assert existing.scalar_one_or_none() is None

        resp = await auth_client.get("/api/admin/ai-settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["effort_level"] == "balanced"
        assert body["content_language"] == "en"
        assert body["effective_model"]  # any non-empty default

        after = await db.execute(
            select(TenantAISettings).where(TenantAISettings.tenant_id == tenant.id)
        )
        assert after.scalar_one() is not None


class TestRouterPatch:
    async def test_patch_sets_thorough(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.patch(
            "/api/admin/ai-settings",
            json={"effort_level": "thorough"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["effort_level"] == "thorough"
        assert body["effective_temperature"] == 0.2
        assert body["effective_model"] == "claude-opus-4-8"

    async def test_patch_temperature_flips_to_custom(
        self, auth_client: AsyncClient
    ) -> None:
        resp = await auth_client.patch(
            "/api/admin/ai-settings",
            json={"temperature": 0.7},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["effort_level"] == "custom"
        assert body["temperature"] == 0.7

    async def test_patch_temperature_out_of_range_rejected(
        self, auth_client: AsyncClient
    ) -> None:
        resp = await auth_client.patch(
            "/api/admin/ai-settings",
            json={"temperature": 1.5},
        )
        assert resp.status_code == 422

    async def test_patch_max_retries_out_of_range_rejected(
        self, auth_client: AsyncClient
    ) -> None:
        resp = await auth_client.patch(
            "/api/admin/ai-settings",
            json={"max_retries": 99},
        )
        assert resp.status_code == 422

    async def test_patch_unsupported_language_rejected(
        self, auth_client: AsyncClient
    ) -> None:
        resp = await auth_client.patch(
            "/api/admin/ai-settings",
            json={"content_language": "fr"},
        )
        assert resp.status_code == 422

    async def test_patch_content_language_de_accepted(
        self, auth_client: AsyncClient
    ) -> None:
        resp = await auth_client.patch(
            "/api/admin/ai-settings",
            json={"content_language": "de"},
        )
        assert resp.status_code == 200
        assert resp.json()["content_language"] == "de"

        resp = await auth_client.get("/api/admin/ai-settings")
        assert resp.json()["content_language"] == "de"

    async def test_patch_company_context_too_long_rejected(
        self, auth_client: AsyncClient
    ) -> None:
        resp = await auth_client.patch(
            "/api/admin/ai-settings",
            json={"company_context": "a" * 2001},
        )
        assert resp.status_code == 422


class TestRouterReset:
    async def test_reset_returns_defaults(self, auth_client: AsyncClient) -> None:
        await auth_client.patch(
            "/api/admin/ai-settings",
            json={"effort_level": "thorough", "company_context": "Acme"},
        )
        resp = await auth_client.post("/api/admin/ai-settings/reset")
        assert resp.status_code == 200
        body = resp.json()
        assert body["effort_level"] == "balanced"
        assert body["company_context"] is None


class TestRouterPresets:
    async def test_presets_lists_three_tiers(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/api/admin/ai-settings/presets")
        assert resp.status_code == 200
        names = {p["name"] for p in resp.json()}
        assert names == {"fast", "balanced", "thorough"}


class TestRouterModels:
    async def test_models_returns_whitelist(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/api/admin/ai-settings/models")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert body, "whitelist must not be empty"
        for entry in body:
            assert {"provider", "model", "label", "credit_multiplier"} <= entry.keys()
            assert entry["provider"] in ("anthropic", "openai", "gemini")
            assert isinstance(entry["credit_multiplier"], (int, float))

    async def test_get_settings_exposes_effective_credit_multiplier(
        self, auth_client: AsyncClient
    ) -> None:
        resp = await auth_client.get("/api/admin/ai-settings")
        assert resp.status_code == 200
        body = resp.json()
        assert "effective_credit_multiplier" in body
        assert isinstance(body["effective_credit_multiplier"], (int, float))

    async def test_patch_unknown_model_rejected(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.patch(
            "/api/admin/ai-settings",
            json={"llm_model": "totally-fake-model"},
        )
        assert resp.status_code == 422


class TestRouterAuthorization:
    @pytest_asyncio.fixture
    async def non_admin_client(self, client: AsyncClient, db: AsyncSession, tenant):
        from app.modules.auth.models import User

        u = User(
            email=f"viewer-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("testpass123"),
            first_name="View",
            last_name="Only",
            tenant_id=tenant.id,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        token = create_access_token(str(u.id), str(tenant.id))
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    async def test_get_forbidden_for_non_admin(
        self, non_admin_client: AsyncClient
    ) -> None:
        resp = await non_admin_client.get("/api/admin/ai-settings")
        assert resp.status_code == 403

    async def test_patch_forbidden_for_non_admin(
        self, non_admin_client: AsyncClient
    ) -> None:
        resp = await non_admin_client.patch(
            "/api/admin/ai-settings",
            json={"effort_level": "fast"},
        )
        assert resp.status_code == 403
