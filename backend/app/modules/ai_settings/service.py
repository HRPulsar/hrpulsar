"""Business logic for tenant AI settings."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.modules.ai import model_registry
from app.modules.ai_settings.models import TenantAISettings
from app.modules.ai_settings.schemas import AISettingsUpdate

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Effort presets
#
# Each preset bundles temperature, retry budget, a per-provider model, and
# `few_shot_count` (a CR11-only constant — promptbuilders read it directly).
# Stored DB columns (temperature, max_retries, llm_model) override the preset
# only when `effort_level == "custom"`.
# ---------------------------------------------------------------------------

EFFORT_PRESETS: dict[str, dict[str, Any]] = {
    "fast": {
        "description": "Fastest and cheapest, suitable for prototyping",
        "temperature": 0.5,
        "max_retries": 3,
        "few_shot_count": 3,
        "models": dict(model_registry.FAST_MODELS),
    },
    "balanced": {
        "description": "Balanced quality and cost (default)",
        "temperature": 0.3,
        "max_retries": 5,
        "few_shot_count": 6,
        "models": dict(model_registry.BALANCED_MODELS),
    },
    "thorough": {
        "description": "Highest quality, slower and more expensive",
        "temperature": 0.2,
        "max_retries": 7,
        "few_shot_count": 9,
        "models": dict(model_registry.THOROUGH_MODELS),
    },
}

DEFAULT_EFFORT = "balanced"
DEFAULT_LANGUAGE = "en"


# ---------------------------------------------------------------------------
# Allowed-model whitelist
#
# In community/self-hosted deployments only the preset models are reachable
# (multiplier 1.0× across the board). Enterprise calls `register_models()`
# during `ee.register_enterprise(app)` to publish the YAML-loaded list with
# real `credit_multiplier` values. Mirrors the `billing_hooks` rebinding
# trick — keeps `app.modules.*` decoupled from `ee/*`.
# ---------------------------------------------------------------------------


def _default_allowed_models() -> list[dict[str, Any]]:
    """Derive a community-edition whitelist from the preset models (×1.0)."""
    seen: set[tuple[str, str]] = set()
    models: list[dict[str, Any]] = []
    for preset in EFFORT_PRESETS.values():
        for provider, model in preset["models"].items():
            key = (provider, model)
            if key in seen:
                continue
            seen.add(key)
            models.append(
                {
                    "provider": provider,
                    "model": model,
                    "label": model,
                    "credit_multiplier": 1.0,
                }
            )
    return models


_allowed_models: list[dict[str, Any]] = _default_allowed_models()


def register_models(models: list[dict[str, Any]]) -> None:
    """Replace the in-memory whitelist. Called by `ee.register_enterprise(app)`."""
    global _allowed_models
    if not models:
        return
    _allowed_models = [
        {
            "provider": entry["provider"],
            "model": entry["model"],
            "label": entry.get("label", entry["model"]),
            "credit_multiplier": float(entry.get("credit_multiplier", 1.0)),
        }
        for entry in models
    ]


def list_allowed_models() -> list[dict[str, Any]]:
    return list(_allowed_models)


def _allowed_model_set() -> set[str]:
    return {entry["model"] for entry in _allowed_models}


def _model_lookup(model_id: str) -> dict[str, Any] | None:
    for entry in _allowed_models:
        if entry["model"] == model_id:
            return entry
    return None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def get_or_default(db: AsyncSession, tenant_id: uuid.UUID) -> TenantAISettings:
    """Return the tenant's row, creating it with defaults on first call."""
    result = await db.execute(
        select(TenantAISettings).where(TenantAISettings.tenant_id == tenant_id)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        return row

    row = TenantAISettings(
        tenant_id=tenant_id,
        content_language=DEFAULT_LANGUAGE,
        effort_level=DEFAULT_EFFORT,
        temperature=0.3,
        max_retries=5,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    patch: AISettingsUpdate,
) -> TenantAISettings:
    """Apply a partial update. Explicit overrides flip effort_level → custom."""
    row = await get_or_default(db, tenant_id)
    data = patch.model_dump(exclude_unset=True)

    if (
        "llm_model" in data
        and data["llm_model"]
        and data["llm_model"] not in _allowed_model_set()
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Model '{data['llm_model']}' is not in the allowed list",
        )

    custom_overrides = {"temperature", "max_retries", "llm_model"}
    explicit_override = any(
        field in data and data[field] is not None for field in custom_overrides
    )

    if "content_language" in data and data["content_language"] is not None:
        row.content_language = data["content_language"]
    if "company_context" in data:
        row.company_context = data["company_context"]
    if "llm_model" in data:
        row.llm_model = data["llm_model"]
    if "temperature" in data and data["temperature"] is not None:
        row.temperature = data["temperature"]
    if "max_retries" in data and data["max_retries"] is not None:
        row.max_retries = data["max_retries"]

    if "effort_level" in data and data["effort_level"] is not None:
        row.effort_level = data["effort_level"]
        if data["effort_level"] != "custom":
            apply_preset(row, data["effort_level"])
    elif explicit_override:
        row.effort_level = "custom"

    await db.commit()
    await db.refresh(row)
    return row


async def reset(db: AsyncSession, tenant_id: uuid.UUID) -> TenantAISettings:
    """Reset a tenant's AI settings to defaults (balanced, English, no context)."""
    row = await get_or_default(db, tenant_id)
    row.content_language = DEFAULT_LANGUAGE
    row.effort_level = DEFAULT_EFFORT
    row.llm_model = None
    row.temperature = EFFORT_PRESETS[DEFAULT_EFFORT]["temperature"]
    row.max_retries = EFFORT_PRESETS[DEFAULT_EFFORT]["max_retries"]
    row.company_context = None
    await db.commit()
    await db.refresh(row)
    return row


def apply_preset(row: TenantAISettings, preset_name: str) -> None:
    """Overwrite temperature/max_retries from the preset (in-place)."""
    preset = EFFORT_PRESETS.get(preset_name)
    if preset is None:
        return
    row.temperature = preset["temperature"]
    row.max_retries = preset["max_retries"]


# ---------------------------------------------------------------------------
# Effective-value resolvers (used by llm_client + prompts)
# ---------------------------------------------------------------------------


def _platform_provider() -> str:
    raw = (app_settings.llm_provider or "claude").lower()
    if raw == "claude":
        return "anthropic"
    return raw


def get_effective_provider(row: TenantAISettings) -> str:
    """Provider derived from override model, otherwise from platform default."""
    if row.llm_model:
        if row.llm_model.startswith("claude"):
            return "anthropic"
        if row.llm_model.startswith("gemini"):
            return "gemini"
        return "openai"
    return _platform_provider()


def get_effective_model(row: TenantAISettings) -> str:
    """Override wins; otherwise pull from preset for the active provider."""
    if row.llm_model:
        return row.llm_model

    provider = _platform_provider()
    preset = EFFORT_PRESETS.get(row.effort_level) or EFFORT_PRESETS[DEFAULT_EFFORT]
    return preset["models"].get(provider, preset["models"]["anthropic"])


def get_effective_temperature(row: TenantAISettings) -> float:
    """Custom uses stored value; preset levels read from the preset map."""
    if row.effort_level == "custom":
        return row.temperature
    preset = EFFORT_PRESETS.get(row.effort_level) or EFFORT_PRESETS[DEFAULT_EFFORT]
    return preset["temperature"]


def get_effective_max_retries(row: TenantAISettings) -> int:
    if row.effort_level == "custom":
        return row.max_retries
    preset = EFFORT_PRESETS.get(row.effort_level) or EFFORT_PRESETS[DEFAULT_EFFORT]
    return preset["max_retries"]


def get_effective_few_shot_count(row: TenantAISettings) -> int:
    """CR11 promptbuilders read this directly from the preset."""
    preset = EFFORT_PRESETS.get(row.effort_level) or EFFORT_PRESETS[DEFAULT_EFFORT]
    return preset["few_shot_count"]


def get_effective_credit_multiplier(row: TenantAISettings) -> float:
    """Per-model multiplier applied by `ee.credits._resolve_cost`.

    Lookup order: effective model → entry in the registered whitelist. Falls
    back to 1.0 when the model isn't on the list (community edition or a
    legacy row pinned to a no-longer-allowed model).
    """
    model = get_effective_model(row)
    entry = _model_lookup(model)
    if entry is None:
        return 1.0
    return float(entry["credit_multiplier"])


# ---------------------------------------------------------------------------
# Prompt augmentation helpers (used by prompts.py)
# ---------------------------------------------------------------------------


_LANGUAGE_NAMES = {"en": "English"}


def build_language_directive(row: TenantAISettings) -> str:
    name = _LANGUAGE_NAMES.get(row.content_language, "English")
    return f"Generate ALL content in {name}."


def build_system_prompt_extras(row: TenantAISettings | None) -> list[str]:
    """Return the language directive + optional company context block."""
    if row is None:
        return []
    parts = [build_language_directive(row)]
    if row.company_context:
        parts.append(f"Company context: {row.company_context}")
    return parts


# ---------------------------------------------------------------------------
# Read-projection helper (router builds AISettingsRead from this)
# ---------------------------------------------------------------------------


def to_read_dict(row: TenantAISettings) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "content_language": row.content_language,
        "effort_level": row.effort_level,
        "llm_model": row.llm_model,
        "temperature": row.temperature,
        "max_retries": row.max_retries,
        "company_context": row.company_context,
        "effective_model": get_effective_model(row),
        "effective_provider": get_effective_provider(row),
        "effective_temperature": get_effective_temperature(row),
        "effective_max_retries": get_effective_max_retries(row),
        "effective_credit_multiplier": get_effective_credit_multiplier(row),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_presets() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": preset["description"],
            "temperature": preset["temperature"],
            "max_retries": preset["max_retries"],
            "models": preset["models"],
        }
        for name, preset in EFFORT_PRESETS.items()
    ]
