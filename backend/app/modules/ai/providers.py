"""Data-driven LLM provider registry (HRP-465).

Single source of truth for which providers the platform knows, how a model
name maps onto a provider, and where credentials come from. Everything that
used to be a scattered prefix chain (``llm_client._resolve_provider``,
``ai_settings.service.get_effective_provider``) resolves through this module
so a new provider lands in exactly one place.

Credential precedence for generation: per-tenant BYOK/local config
(``recruitment.models.LLMProviderConfig`` — key encrypted at rest) wins over
the platform-wide env key. ``openai_compatible`` covers self-hosted
OpenAI-API servers (Ollama, vLLM, LM Studio, …) — ``base_url`` lives in the
config row's ``settings`` JSON, an API key is optional.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderSpec:
    """One provider the platform can generate through."""

    name: str
    label: str
    # ``app.config.Settings`` attribute holding the platform-wide API key,
    # or None when the provider has no global key (local servers).
    global_key_attr: str | None
    # Accepts a per-tenant ``base_url`` (OpenAI-compatible local servers).
    supports_local: bool = False
    # Model-name prefixes owned by this provider (dispatch fallback; local
    # model names are arbitrary, so BYOK rows match by model first).
    classify_prefixes: tuple[str, ...] = ()


PROVIDERS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        name="anthropic",
        label="Anthropic",
        global_key_attr="anthropic_api_key",
        classify_prefixes=("claude",),
    ),
    "openai": ProviderSpec(
        name="openai",
        label="OpenAI",
        global_key_attr="openai_api_key",
        classify_prefixes=("gpt", "o1", "o3", "o4", "text-embedding"),
    ),
    "gemini": ProviderSpec(
        name="gemini",
        label="Google Gemini",
        global_key_attr="gemini_api_key",
        classify_prefixes=("gemini",),
    ),
    "openai_compatible": ProviderSpec(
        name="openai_compatible",
        label="OpenAI-compatible (local)",
        global_key_attr=None,
        supports_local=True,
    ),
}

# Legacy/BYOK provider names accepted from stored rows and recruitment
# schemas, mapped onto a canonical spec. Azure/Yandex/GigaChat all expose
# OpenAI-compatible chat endpoints — their rows carry a ``base_url``.
PROVIDER_ALIASES: dict[str, str] = {
    "claude": "anthropic",
    "azure": "openai_compatible",
    "yandex": "openai_compatible",
    "gigachat": "openai_compatible",
}


def resolve_provider_name(name: str | None) -> str | None:
    """Canonical provider name for a stored/user-supplied one, or None."""
    if not name:
        return None
    lowered = name.lower()
    if lowered in PROVIDERS:
        return lowered
    return PROVIDER_ALIASES.get(lowered)


def classify_model(model: str | None) -> str | None:
    """Provider owning this model name by prefix, or None when unknown."""
    if not model:
        return None
    for spec in PROVIDERS.values():
        if spec.classify_prefixes and model.startswith(spec.classify_prefixes):
            return spec.name
    return None


def default_provider() -> str:
    """Platform default provider (env ``LLM_PROVIDER``) as a canonical name."""
    return resolve_provider_name(settings.llm_provider) or "openai"


def global_key(provider: str) -> str | None:
    spec = PROVIDERS.get(provider)
    if spec is None or spec.global_key_attr is None:
        return None
    return getattr(settings, spec.global_key_attr) or None


@dataclass(frozen=True)
class GenerationTarget:
    """Resolved dispatch target for one generation call."""

    provider: str
    api_key: str | None = None  # None → the provider's global env key
    base_url: str | None = None  # OpenAI-compatible servers only
    source: str = "global"  # global | byok | local
    # The BYOK/local row's configured model. llm_client uses it only when
    # the caller did not pick a model itself (recruitment pipeline).
    model: str | None = None


def _row_base_url(row: Any) -> str | None:
    raw = (row.settings or {}).get("base_url") if row.settings else None
    if isinstance(raw, str) and raw.startswith(("http://", "https://")):
        return raw
    return None


def _decrypt_row_key(row: Any) -> str | None:
    if not row.api_key_encrypted:
        return None
    from app.core.crypto import decrypt_secret

    try:
        return decrypt_secret(row.api_key_encrypted)
    except Exception:  # noqa: BLE001 — a stale key must not kill generation
        logger.warning(
            "LLM provider config %s: stored API key failed to decrypt; "
            "falling back to the platform key",
            row.id,
        )
        return None


def _pick_target(rows: list[Any], model: str | None) -> GenerationTarget | None:
    """Resolve a tenant's config rows against the requested model.

    Match order: exact model match first (local model names are arbitrary,
    prefixes can't classify them), then any row for the model's classified
    provider. Rows with an unknown provider name are skipped.
    """
    classified = classify_model(model)

    def _target(row: Any, provider: str) -> GenerationTarget | None:
        base_url = _row_base_url(row)
        api_key = _decrypt_row_key(row)
        if provider == "openai_compatible" or (
            provider == "openai" and base_url is not None
        ):
            # base_url is the whole point of a local row — without one it is
            # misconfigured and can't be dispatched. An OpenAI row pointing
            # at a custom endpoint is a local server too.
            if base_url is None:
                return None
            return GenerationTarget(
                provider="openai_compatible",
                api_key=api_key,
                base_url=base_url,
                source="local",
                model=row.model or None,
            )
        if api_key is not None:
            return GenerationTarget(
                provider=provider,
                api_key=api_key,
                source="byok",
                model=row.model or None,
            )
        return None

    for row in rows:
        provider = resolve_provider_name(row.provider)
        if provider is None or not model or row.model != model:
            continue
        resolved = _target(row, provider)
        if resolved is not None:
            return resolved

    if classified is not None:
        for row in rows:
            if resolve_provider_name(row.provider) != classified:
                continue
            resolved = _target(row, classified)
            if resolved is not None:
                return resolved
        return None

    if model is None:
        # No model requested (recruitment pipeline): the tenant's most
        # recently updated dispatchable config wins, model included.
        for row in rows:
            provider = resolve_provider_name(row.provider)
            if provider is None:
                continue
            resolved = _target(row, provider)
            if resolved is not None:
                return resolved
    return None


def _fallback_target(model: str | None) -> GenerationTarget:
    return GenerationTarget(provider=classify_model(model) or default_provider())


def _rows_query(tenant_id: uuid.UUID) -> Any:
    from app.modules.recruitment.models import LLMProviderConfig

    return (
        select(LLMProviderConfig)
        .where(
            LLMProviderConfig.tenant_id == tenant_id,
            LLMProviderConfig.is_active.is_(True),
        )
        .order_by(LLMProviderConfig.updated_at.desc())
    )


async def resolve_generation_target(
    db: AsyncSession, tenant_id: uuid.UUID, model: str | None
) -> GenerationTarget:
    """BYOK/local-aware dispatch target (async request path)."""
    result = await db.execute(_rows_query(tenant_id))
    rows = list(result.scalars().all())
    return _pick_target(rows, model) or _fallback_target(model)


def resolve_generation_target_sync(
    db: Session, tenant_id: uuid.UUID, model: str | None
) -> GenerationTarget:
    """Sync twin of :func:`resolve_generation_target` for Celery workers
    that hold a synchronous Session (recruitment analysis tasks)."""
    rows = list(db.execute(_rows_query(tenant_id)).scalars().all())
    return _pick_target(rows, model) or _fallback_target(model)


async def configured_providers(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Per-provider availability for the admin UI.

    A provider is configured when any credential source exists for it:
    ``byok`` (tenant key), ``local`` (tenant base_url), or ``global``
    (platform env key). Only configured providers should be offered in
    model/provider selectors.
    """
    result = await db.execute(_rows_query(tenant_id))
    rows = list(result.scalars().all())

    by_provider: dict[str, list[Any]] = {}
    for row in rows:
        provider = resolve_provider_name(row.provider)
        if provider is not None:
            by_provider.setdefault(provider, []).append(row)

    out: list[dict[str, Any]] = []
    for spec in PROVIDERS.values():
        source: str | None = None
        for row in by_provider.get(spec.name, []):
            if _row_base_url(row) is not None:
                source = "local"
                break
            if row.api_key_encrypted and source is None:
                source = "byok"
        if source is None and global_key(spec.name) is not None:
            source = "global"
        out.append(
            {
                "provider": spec.name,
                "label": spec.label,
                "configured": source is not None,
                "source": source,
                "supports_local": spec.supports_local,
            }
        )
    return out
