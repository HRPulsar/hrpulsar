"""Business logic for tenant AI settings."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.core.errors import AppError
from app.modules.ai import model_registry, providers
from app.modules.ai_settings.models import TenantAISettings
from app.modules.ai_settings.schemas import AISettingsUpdate

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


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


def upsert_allowed_model(entry: dict[str, Any]) -> None:
    """Insert or replace one whitelist entry.

    HRP-466 moderation path: platform admin approves a discovered model
    with an explicit multiplier, which must reach the in-memory registry
    immediately so billing stays on the fast lookup (no DB hit per charge).
    """
    global _allowed_models
    normalized = {
        "provider": entry["provider"],
        "model": entry["model"],
        "label": entry.get("label", entry["model"]),
        "credit_multiplier": float(entry.get("credit_multiplier", 1.0)),
    }
    _allowed_models = [
        e for e in _allowed_models if e["model"] != normalized["model"]
    ] + [normalized]


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

    if "llm_model" in data and data["llm_model"]:
        # HRP-466: when the catalog has a row for the model, the catalog is
        # authoritative — disabling a row there is the kill-switch, even for
        # curated models the in-memory whitelist would otherwise pass. The
        # whitelist only covers models the catalog has never seen.
        from app.modules.ai import model_catalog_service

        entry = await model_catalog_service.get_entry(db, data["llm_model"])
        if entry is not None:
            allowed = entry.status == "approved" and entry.enabled
        else:
            allowed = data["llm_model"] in _allowed_model_set()
        if not allowed:
            raise AppError(
                "llm_model_not_allowed",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                model=data["llm_model"],
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
    return providers.resolve_provider_name(app_settings.llm_provider) or "anthropic"


def get_effective_provider(row: TenantAISettings) -> str:
    """Provider derived from override model, otherwise from platform default.

    Model-name classification lives in the provider registry (HRP-465);
    unclassifiable names (local/OpenAI-compatible models) fall back to
    "openai" — they are served through the OpenAI-compatible path.
    """
    if row.llm_model:
        return providers.classify_model(row.llm_model) or "openai"
    return _platform_provider()


def get_effective_model(row: TenantAISettings) -> str:
    """Override wins; otherwise pull from preset for the active provider.

    Catalog-blind: use :func:`get_effective_model_async` wherever a
    session is available, so a model the platform admin disabled stops
    being dispatched (HRP-500).
    """
    if row.llm_model:
        return row.llm_model

    provider = _platform_provider()
    preset = EFFORT_PRESETS.get(row.effort_level) or EFFORT_PRESETS[DEFAULT_EFFORT]
    return preset["models"].get(provider, preset["models"]["anthropic"])


async def get_effective_model_async(db: AsyncSession, row: TenantAISettings) -> str:
    """Effective model, checked against the catalog kill-switch.

    HRP-500 (review #12): disabling a catalog row blocked *picking* the
    model but not *using* it — tenants on an effort preset never pin a
    model, so ``get_effective_model`` kept resolving the hard-coded preset
    id and every unpinned tenant went on calling a model the platform
    admin had just turned off. When the resolved model is not pickable any
    more, fall back to another approved+enabled model of the same tier and
    provider; with no substitute the preset id stands (killing generation
    outright would be worse than one more call to a deprecated model).
    """
    from app.modules.ai import model_catalog_service

    model = get_effective_model(row)
    if await model_catalog_service.is_model_allowed(db, model):
        return model
    entry = await model_catalog_service.get_entry(db, model)
    if entry is None:
        # The catalog has never seen this model (local/BYOK name, or a
        # fresh install before the first seed) — it is not the catalog's
        # call to override it.
        return model

    # The replacement must stay on the provider of the model being
    # replaced, not on the platform default: a tenant pinned to gpt-4o
    # through its own OpenAI key would otherwise be handed a Claude model,
    # silently bypassing its BYOK credentials and contradicting the
    # ``effective_provider`` the same projection reports (review #2).
    # Same for the tier — a pinned model's tier is the catalog row's, not
    # the tenant's effort level (which is "custom" for every pinned row).
    provider = entry.provider or get_effective_provider(row)
    tier = entry.tier or (
        row.effort_level if row.effort_level in EFFORT_PRESETS else DEFAULT_EFFORT
    )
    substitute = await model_catalog_service.pick_tier_model(db, provider, tier)
    if substitute is None:
        logger.warning(
            "ai settings: model %s is disabled in the catalog and no %s/%s "
            "replacement is approved — keeping it",
            model,
            provider,
            tier,
        )
        return model
    logger.warning(
        "ai settings: model %s is disabled in the catalog — falling back to %s",
        model,
        substitute,
    )
    return substitute


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
    """Per-model multiplier from the in-memory whitelist (read projection).

    Lookup order: effective model → entry in the registered whitelist. Falls
    back to 1.0 when the model isn't on the list (community edition or a
    legacy row pinned to a no-longer-allowed model). Billing must NOT use
    this — see :func:`get_effective_credit_multiplier_async`.
    """
    model = get_effective_model(row)
    entry = _model_lookup(model)
    if entry is None:
        return 1.0
    return float(entry["credit_multiplier"])


async def get_effective_credit_multiplier_async(
    db: AsyncSession, row: TenantAISettings
) -> float:
    """Billing-grade multiplier: the catalog row, then the registry, then 1.0.

    HRP-500 (review #10): the catalog is the source of truth and the
    in-memory registry is a per-process cache of it. A moderation approval
    (or a later multiplier edit) upserts the registry only in the uvicorn
    worker that served the request, so a registry-first lookup billed the
    same tenant differently depending on which worker answered. Reading
    the moderated row first makes every worker agree; curated seed rows
    carry NULL and still fall through to their credits.yaml price.

    Used by `ee.credits._resolve_cost`.
    """
    from app.modules.ai import model_catalog_service

    model = await get_effective_model_async(db, row)
    stored = await model_catalog_service.stored_multiplier(db, model)
    if stored is not None:
        return float(stored)

    entry = _model_lookup(model)
    if entry is not None:
        return float(entry["credit_multiplier"])

    # HRP-500 (review #11): a tenant pinned to a model that was dropped
    # from credits.yaml and never moderated in the catalog would bill at
    # 1.0 silently — a 3.0× model charged as 1.0×. Still bill (refusing
    # the action helps nobody), but leave a trace an operator can find.
    logger.warning(
        "billing: no credit multiplier for model %s (tenant %s) — charging 1.0",
        model,
        row.tenant_id,
    )
    return 1.0


# ---------------------------------------------------------------------------
# Prompt augmentation helpers (used by prompts.py)
# ---------------------------------------------------------------------------


_LANGUAGE_NAMES = {"en": "English", "de": "German"}


def build_language_directive(row: TenantAISettings) -> str:
    """Output-language directive appended to AI system prompts.

    The verbatim carve-out is load-bearing (HRP-480 review): downstream
    code matches LLM output back to DB rows by English titles and enum
    values (`type` / `material_type` / `skill_level`, grade titles), so
    a translated echo-back would be silently dropped or fail schema
    validation.
    """
    name = _LANGUAGE_NAMES.get(row.content_language, "English")
    return (
        f"Generate ALL content in {name}. "
        "Echo machine-readable values verbatim in their original wording, "
        "never translated: enum values (such as `type`, `material_type`), "
        "and any skill-level or grade titles that come from the input."
    )


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


async def to_read_dict_async(db: AsyncSession, row: TenantAISettings) -> dict[str, Any]:
    """Read projection with the multiplier billing will actually charge.

    HRP-500 (review #14): the sync projection resolves the multiplier from
    the in-memory registry only, while billing reads the catalog — so the
    settings page could quote x1.0 for a model charged at x2.5 (and the
    spend preview inherited the same phantom delta).
    """
    effective_model = await get_effective_model_async(db, row)
    return to_read_dict(
        row,
        effective_model=effective_model,
        credit_multiplier=await get_effective_credit_multiplier_async(db, row),
    )


def to_read_dict(
    row: TenantAISettings,
    *,
    effective_model: str | None = None,
    credit_multiplier: float | None = None,
) -> dict[str, Any]:
    """Read projection. ``effective_model``/``credit_multiplier`` come from
    the catalog-aware async resolvers when the caller has a session —
    without them this falls back to the registry-only values."""
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        # The DB no longer CHECKs the column (HRP-480); normalize a code
        # the API contract does not know so reads keep working instead of
        # failing response_model validation with a 500.
        "content_language": (
            row.content_language
            if row.content_language in _LANGUAGE_NAMES
            else DEFAULT_LANGUAGE
        ),
        "effort_level": row.effort_level,
        "llm_model": row.llm_model,
        "temperature": row.temperature,
        "max_retries": row.max_retries,
        "company_context": row.company_context,
        "effective_model": effective_model or get_effective_model(row),
        "effective_provider": get_effective_provider(row),
        "effective_temperature": get_effective_temperature(row),
        "effective_max_retries": get_effective_max_retries(row),
        "effective_credit_multiplier": (
            credit_multiplier
            if credit_multiplier is not None
            else get_effective_credit_multiplier(row)
        ),
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
