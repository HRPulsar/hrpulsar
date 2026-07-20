"""Phase CR10b/CR10c — TenantAISettings is honored by every AI generation path.

Covers:
- prompts.build_system_competence / build_system_position augment the
  base system message with the tenant's language directive and
  company context.
- llm_client.generate / generate_json read effective model + temperature
  from `tenant_settings` when no explicit override is given.
- tasks._generate_json_with_retries forwards settings into llm_client.
- ai/service.py sync handlers (generate_competences, generate_indicators,
  suggest_pdp, generate_positions) load tenant settings and forward them.
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.modules.ai import llm_client, prompts
from app.modules.ai import service as ai_service
from app.modules.ai.tasks import _generate_json_with_retries
from app.modules.ai_settings import service as ai_settings_service
from app.modules.ai_settings.schemas import AISettingsUpdate
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Prompt augmentation
# ---------------------------------------------------------------------------


class TestSystemPromptAugmentation:
    async def test_competence_prompt_with_default_settings_mentions_english(
        self, db: AsyncSession, tenant
    ) -> None:
        settings = await ai_settings_service.get_or_default(db, tenant.id)
        system = prompts.build_system_competence(settings)
        assert "English" in system
        assert prompts.SYSTEM_COMPETENCE in system

    async def test_competence_prompt_includes_company_context(
        self, db: AsyncSession, tenant
    ) -> None:
        settings = await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(company_context="Acme Corp")
        )
        system = prompts.build_system_competence(settings)
        assert "Acme Corp" in system

    async def test_position_prompt_includes_company_context(
        self, db: AsyncSession, tenant
    ) -> None:
        settings = await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(company_context="Acme Corp")
        )
        system = prompts.build_system_position(settings)
        assert "Acme Corp" in system
        assert prompts.SYSTEM_POSITION in system

    def test_competence_prompt_with_no_settings_returns_base(self) -> None:
        assert prompts.build_system_competence(None) == prompts.SYSTEM_COMPETENCE

    def test_position_prompt_with_no_settings_returns_base(self) -> None:
        assert prompts.build_system_position(None) == prompts.SYSTEM_POSITION


# ---------------------------------------------------------------------------
# llm_client honors tenant_settings
# ---------------------------------------------------------------------------


class TestLLMClientUsesSettings:
    async def test_thorough_preset_picks_opus(self, db: AsyncSession, tenant) -> None:
        settings = await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(effort_level="thorough")
        )

        captured: dict = {}

        async def fake_anthropic(prompt, system, model, temperature, max_tokens):
            captured["model"] = model
            captured["temperature"] = temperature
            return "ok"

        with patch.object(llm_client, "_generate_anthropic", new=fake_anthropic):
            await llm_client.generate(
                "test prompt", system="sys", tenant_settings=settings
            )

        assert captured["model"] == "claude-opus-4-7"
        assert captured["temperature"] == 0.2

    async def test_fast_preset_picks_haiku(self, db: AsyncSession, tenant) -> None:
        settings = await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(effort_level="fast")
        )

        captured: dict = {}

        async def fake_anthropic(prompt, system, model, temperature, max_tokens):
            captured["model"] = model
            captured["temperature"] = temperature
            return "ok"

        with patch.object(llm_client, "_generate_anthropic", new=fake_anthropic):
            await llm_client.generate(
                "test prompt", system="sys", tenant_settings=settings
            )

        assert captured["model"] == "claude-haiku-4-5-20251001"
        assert captured["temperature"] == 0.5

    async def test_explicit_model_overrides_preset(
        self, db: AsyncSession, tenant
    ) -> None:
        settings = await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(effort_level="fast")
        )

        captured: dict = {}

        async def fake_anthropic(prompt, system, model, temperature, max_tokens):
            captured["model"] = model
            captured["temperature"] = temperature
            return "ok"

        with patch.object(llm_client, "_generate_anthropic", new=fake_anthropic):
            await llm_client.generate(
                "test prompt",
                system="sys",
                model="claude-opus-4-7",
                temperature=0.1,
                tenant_settings=settings,
            )

        assert captured["model"] == "claude-opus-4-7"
        assert captured["temperature"] == 0.1

    async def test_custom_settings_use_stored_values(
        self, db: AsyncSession, tenant
    ) -> None:
        settings = await ai_settings_service.update(
            db,
            tenant.id,
            AISettingsUpdate(
                llm_model="claude-opus-4-7", temperature=0.42, max_retries=4
            ),
        )
        assert settings.effort_level == "custom"

        captured: dict = {}

        async def fake_anthropic(prompt, system, model, temperature, max_tokens):
            captured["model"] = model
            captured["temperature"] = temperature
            return "ok"

        with patch.object(llm_client, "_generate_anthropic", new=fake_anthropic):
            await llm_client.generate(
                "test prompt", system="sys", tenant_settings=settings
            )

        assert captured["model"] == "claude-opus-4-7"
        assert captured["temperature"] == 0.42


# ---------------------------------------------------------------------------
# _generate_json_with_retries
# ---------------------------------------------------------------------------


class TestRetryHelper:
    async def test_forwards_settings_to_llm_client(
        self, db: AsyncSession, tenant
    ) -> None:
        settings = await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(effort_level="thorough")
        )

        mock = AsyncMock(return_value=[{"ok": True}])
        with patch.object(llm_client, "generate_json", new=mock):
            result = await _generate_json_with_retries(
                "prompt",
                system="sys",
                tenant_settings=settings,
                max_retries=3,
            )

        assert result == [{"ok": True}]
        mock.assert_called_once()
        kwargs = mock.call_args.kwargs
        assert kwargs["system"] == "sys"
        assert kwargs["tenant_settings"] is settings

    async def test_retries_on_parse_error(self, db: AsyncSession, tenant) -> None:
        settings = await ai_settings_service.get_or_default(db, tenant.id)

        call_count = {"n": 0}

        async def flaky(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise json.JSONDecodeError("bad", "", 0)
            return [{"ok": True}]

        with patch.object(llm_client, "generate_json", new=flaky):
            result = await _generate_json_with_retries(
                "prompt",
                system="sys",
                tenant_settings=settings,
                max_retries=5,
            )

        assert result == [{"ok": True}]
        assert call_count["n"] == 3

    async def test_raises_after_budget_exhausted(
        self, db: AsyncSession, tenant
    ) -> None:
        settings = await ai_settings_service.get_or_default(db, tenant.id)

        async def always_bad(*args, **kwargs):
            raise json.JSONDecodeError("bad", "", 0)

        with (
            patch.object(llm_client, "generate_json", new=always_bad),
            pytest.raises(json.JSONDecodeError),
        ):
            await _generate_json_with_retries(
                "prompt",
                system="sys",
                tenant_settings=settings,
                max_retries=2,
            )


# ---------------------------------------------------------------------------
# CR10c — sync handlers in ai/service.py forward tenant_settings
# ---------------------------------------------------------------------------


class TestSyncHandlersForwardSettings:
    """Each sync handler must:
    1) lazy-load (or create) TenantAISettings for the tenant_id, and
    2) pass that row plus the augmented system prompt to llm_client.
    """

    async def test_generate_competences_forwards_settings(
        self, db: AsyncSession, tenant
    ) -> None:
        await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(company_context="Acme Corp")
        )

        captured: dict = {}

        async def fake_generate_json(prompt, **kwargs):
            captured["prompt"] = prompt
            captured["system"] = kwargs.get("system")
            captured["tenant_settings"] = kwargs.get("tenant_settings")
            return [{"title": "Group", "competences": []}]

        with patch.object(llm_client, "generate_json", new=fake_generate_json):
            await ai_service.generate_competences(
                db,
                tenant.id,
                None,
                "Backend Developer",
                company_description="ctx",
            )

        assert captured["tenant_settings"] is not None
        assert captured["tenant_settings"].tenant_id == tenant.id
        assert "English" in captured["system"]
        assert "Acme Corp" in captured["system"]

    async def test_generate_indicators_forwards_settings(
        self, db: AsyncSession, tenant
    ) -> None:
        captured: dict = {}

        async def fake_generate_json(prompt, **kwargs):
            captured["tenant_settings"] = kwargs.get("tenant_settings")
            captured["system"] = kwargs.get("system")
            return [{"title": "ind", "skill_level": "basic", "weight": 1}]

        with patch.object(llm_client, "generate_json", new=fake_generate_json):
            await ai_service.generate_indicators(db, tenant.id, None, "Code review")

        assert captured["tenant_settings"] is not None
        assert captured["tenant_settings"].tenant_id == tenant.id
        assert "English" in captured["system"]

    async def test_suggest_pdp_forwards_settings(
        self,
        db: AsyncSession,
        tenant,
    ) -> None:
        captured: dict = {}

        async def fake_generate_json(prompt, **kwargs):
            captured["tenant_settings"] = kwargs.get("tenant_settings")
            captured["system"] = kwargs.get("system")
            return [{"title": "Goal", "competence_title": "X", "materials": []}]

        # Mock the context builder — it requires real Assessment rows which
        # are out of scope here. We're only checking settings forwarding.
        async def fake_collect(_db, _aid):
            return "PDP prompt body"

        assessment_id = uuid.uuid4()
        with (
            patch.object(llm_client, "generate_json", new=fake_generate_json),
            patch.object(ai_service, "_collect_context_for_pdp", new=fake_collect),
        ):
            await ai_service.suggest_pdp(db, tenant.id, None, assessment_id)

        assert captured["tenant_settings"] is not None
        assert captured["tenant_settings"].tenant_id == tenant.id
        assert "English" in captured["system"]

    async def test_generate_positions_forwards_settings(
        self, db: AsyncSession, tenant
    ) -> None:
        captured: dict = {}

        async def fake_generate_json(prompt, **kwargs):
            captured["tenant_settings"] = kwargs.get("tenant_settings")
            captured["system"] = kwargs.get("system")
            return []

        with patch.object(llm_client, "generate_json", new=fake_generate_json):
            await ai_service.generate_positions(db, tenant.id, None)

        assert captured["tenant_settings"] is not None
        assert captured["tenant_settings"].tenant_id == tenant.id
        assert "English" in captured["system"]
        assert prompts.SYSTEM_POSITION in captured["system"]
