"""Which outside AI processors may receive a tenant's data (HRP-1005).

A processor is a company a platform-keyed call hands data to, not a feature:
Whisper and embeddings both go to ``openai``, SpeechKit to ``yandex``. The
instance lists the processors every tenant may use (``AI_PROCESSORS_DEFAULT``,
empty = all); the platform admin adds or removes processors per tenant
(``tenants.ai_processor_overrides``) or cuts the tenant off platform keys
entirely (``tenants.ai_own_keys_only``). A tenant's own keys (BYOK) are its
own contract with the provider and are never restricted here.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import status
from sqlalchemy import select

from app.config import AI_PROCESSOR_NAMES, settings
from app.core.errors import AppError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

PROCESSORS = AI_PROCESSOR_NAMES

# Company names, not translated.
PROCESSOR_LABELS: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "gemini": "Google",
    "yandex": "Yandex",
    "jev": "TypeSafe (Jev)",
    "deepgram": "Deepgram",
    "assemblyai": "AssemblyAI",
}

# Settings attributes holding each processor's platform key.
_PLATFORM_KEYS: dict[str, tuple[str, ...]] = {
    "anthropic": ("anthropic_api_key",),
    "openai": ("openai_api_key",),
    "gemini": ("gemini_api_key",),
    "yandex": ("yandex_api_key", "yandex_speechkit_api_key"),
    "jev": ("jev_api_key",),
    "deepgram": ("deepgram_api_key",),
    "assemblyai": ("assemblyai_api_key",),
}


def instance_default() -> frozenset[str]:
    """The instance's list; empty setting = every processor."""
    names = {
        name.strip().lower()
        for name in settings.ai_processors_default.split(",")
        if name.strip()
    }
    return frozenset(names) if names else frozenset(PROCESSORS)


def effective_processors(
    overrides: dict[str, bool] | None, own_keys_only: bool
) -> frozenset[str]:
    """The instance list with the tenant's adjustments applied."""
    if own_keys_only:
        return frozenset()
    allowed = set(instance_default())
    for name, enabled in (overrides or {}).items():
        if enabled:
            allowed.add(name)
        else:
            allowed.discard(name)
    # A key edited straight into the DB must not invent a processor.
    return frozenset(allowed & set(PROCESSORS))


def _tenant_query(tenant_id: uuid.UUID) -> Any:
    from app.modules.company.models import Tenant

    return select(Tenant.ai_processor_overrides, Tenant.ai_own_keys_only).where(
        Tenant.id == tenant_id
    )


async def allowed_processors(db: AsyncSession, tenant_id: uuid.UUID) -> frozenset[str]:
    """Processors this tenant's data may reach on platform keys."""
    row = (await db.execute(_tenant_query(tenant_id))).first()
    return effective_processors(row[0], row[1]) if row else instance_default()


def allowed_processors_sync(db: Session, tenant_id: uuid.UUID) -> frozenset[str]:
    """Sync twin of :func:`allowed_processors` for Celery workers."""
    row = db.execute(_tenant_query(tenant_id)).first()
    return effective_processors(row[0], row[1]) if row else instance_default()


def platform_key_configured(name: str) -> bool:
    return any(getattr(settings, attr, "") for attr in _PLATFORM_KEYS.get(name, ()))


async def require_processor(db: AsyncSession, tenant_id: uuid.UUID, name: str) -> None:
    """Refuse a call that would hand this tenant's data to ``name``."""
    if name not in await allowed_processors(db, tenant_id):
        raise AppError(
            "ai_processor_not_allowed", status.HTTP_409_CONFLICT, processor=name
        )


# --- Generation: which model a tenant's call really goes out on -------------

LLM_PROVIDERS = ("anthropic", "openai", "gemini", "yandex")


def _tier_models() -> dict[str, dict[str, str]]:
    from app.modules.ai import model_registry

    return {
        "fast": model_registry.FAST_MODELS,
        "balanced": model_registry.BALANCED_MODELS,
        "thorough": model_registry.THOROUGH_MODELS,
    }


def _permitted(provider: str, allowed: frozenset[str], byok: dict[str, str | None]) -> bool:
    return provider in byok or provider in allowed


def _usable(provider: str, allowed: frozenset[str], byok: dict[str, str | None]) -> bool:
    from app.modules.ai import providers

    return provider in byok or (
        provider in allowed and providers.global_key(provider) is not None
    )


def _substitution_order() -> list[str]:
    from app.modules.ai import providers

    first = providers.default_provider()
    rest = [p for p in LLM_PROVIDERS if p != first]
    return [first, *rest] if first in LLM_PROVIDERS else rest


def _catalog_query() -> Any:
    from app.modules.ai.models import ModelCatalogEntry

    return (
        select(ModelCatalogEntry)
        .where(ModelCatalogEntry.status == "approved")
        .order_by(ModelCatalogEntry.provider, ModelCatalogEntry.model_id)
    )


async def approved_catalog(db: AsyncSession) -> list[Any]:
    return list((await db.execute(_catalog_query())).scalars().all())


def approved_catalog_sync(db: Session) -> list[Any]:
    return list(db.execute(_catalog_query()).scalars().all())


def choose_model(
    model: str,
    catalog: list[Any],
    allowed: frozenset[str],
    byok: dict[str, str | None],
) -> tuple[str, str] | None:
    """``(model, provider)`` a tenant's call on ``model`` may go out on.

    ``model`` itself when its provider is permitted (allowed, or the tenant's
    own BYOK). Otherwise a model of the same tier on the first usable provider
    in ``LLM_PROVIDER``-first order: the tenant's BYOK row model, else the
    catalog's pick for that tier, else the preset model. None when no LLM
    provider is usable. Local models are not governed by the list.
    """
    from app.modules.ai import model_catalog_service, providers

    entry = next((row for row in catalog if row.model_id == model), None)
    provider = (
        providers.classify_model(model)
        or (entry.provider if entry is not None else None)
        or providers.default_provider()
    )
    if provider not in LLM_PROVIDERS or _permitted(provider, allowed, byok):
        return model, provider

    tiers = _tier_models()
    tier = entry.tier if entry is not None and entry.tier in tiers else "balanced"
    for candidate in _substitution_order():
        if not _usable(candidate, allowed, byok):
            continue
        own = byok.get(candidate)
        if own:
            return own, candidate
        picked = model_catalog_service._pick_tier_row(
            [row for row in catalog if row.provider == candidate], tier
        )
        substitute = picked.model_id if picked is not None else tiers[tier].get(candidate)
        if substitute:
            return substitute, candidate
    # The tenant's own OpenAI-compatible server (Azure, GigaChat, a local
    # one) carries no LLM_PROVIDERS name but is its own key all the same:
    # the last resort before refusing, on the model its row serves.
    for candidate, own in byok.items():
        if candidate not in LLM_PROVIDERS and own:
            return own, candidate
    return None


def enforce_target(
    target: Any,
    model: str | None,
    rows: list[Any],
    allowed: frozenset[str],
    catalog: list[Any],
) -> Any:
    """Platform-key dispatch target the tenant's list permits.

    ``target`` comes from ``providers._fallback_target`` (no BYOK row matched
    the request) — it is always a keyless "global" target, so it may be kept
    only when its own provider is on the ``allowed`` list. A provider the
    tenant merely *also* reaches through BYOK for some other model must not
    ride this keyless target under that provider's name — that would dispatch
    a disallowed/own-keys-only provider on the platform key (HRP-1005 review
    R5). When not allowed, ``choose_model`` picks the model to send instead;
    when its provider is covered by the tenant's BYOK, dispatch borrows that
    row's credentials for the chosen model — never a bare global target for a
    provider that is not allowed.
    """
    from app.modules.ai import llm_client, providers

    if target.provider not in LLM_PROVIDERS:
        return target
    if target.provider in allowed:
        return target
    byok = providers.byok_models(rows)
    chosen = choose_model(
        model or llm_client._get_default_model(), catalog, allowed, byok
    )
    if chosen is None:
        raise AppError("ai_no_allowed_processor", status.HTTP_409_CONFLICT)
    substitute, provider = chosen
    if provider in byok:
        provider_rows = [
            row for row in rows if providers.resolve_provider_name(row.provider) == provider
        ]
        own = providers._pick_target(rows, substitute) or providers._pick_target(
            provider_rows, None
        )
        if own is not None:
            return dataclasses.replace(own, model=substitute, forced_model=True)
    return providers.GenerationTarget(
        provider=provider, model=substitute, forced_model=True
    )


async def substitute_model(
    db: AsyncSession, tenant_id: uuid.UUID, model: str
) -> str | None:
    """The model a tenant's call on ``model`` really goes out on, or None
    when no LLM provider is usable. Billing and the settings page read this,
    so they agree with dispatch (HRP-1005)."""
    from app.modules.ai import providers

    rows = await providers.load_rows(db, tenant_id)
    if providers._pick_target(rows, model) is not None:
        # The tenant's own row (BYOK/local — including a proxy row like
        # Azure/GigaChat, keyed under a different canonical provider) already
        # dispatches this exact model: BYOK is never restricted by the
        # processor list (HRP-1005 review R4), so it must not be substituted
        # away here either.
        return model

    # HRP-1005 (F5): a model whose provider a prefix already owns needs no
    # catalog row to resolve that provider — skip the (comparatively heavy)
    # approved-catalog query unless the provider is actually unclassifiable
    # (only the catalog knows who owns it) or is classifiable but not
    # permitted, i.e. a substitution may actually happen.
    classified = providers.classify_model(model)
    if classified is not None and classified not in LLM_PROVIDERS:
        return model
    byok = providers.byok_models(rows)
    allowed = await allowed_processors(db, tenant_id)
    if classified is not None and _permitted(classified, allowed, byok):
        return model
    chosen = choose_model(model, await approved_catalog(db), allowed, byok)
    return chosen[0] if chosen is not None else None
