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

from fastapi import status
from sqlalchemy import select

from app.config import settings
from app.core.errors import AppError

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
    "yandex": ProviderSpec(
        name="yandex",
        label="YandexGPT",
        global_key_attr="yandex_api_key",
        # Yandex model URIs ("gpt://<folder>/<model>") share their first
        # three characters with the OpenAI prefix — classify_model picks
        # the longest matching prefix, so ownership stays unambiguous.
        classify_prefixes=("gpt://", "yandexgpt"),
        # Alias-era rows carry a base_url (gateway/proxy); the yandex
        # dispatch honours it instead of the platform endpoint.
        supports_local=True,
    ),
    "openai_compatible": ProviderSpec(
        name="openai_compatible",
        label="OpenAI-compatible (local)",
        global_key_attr=None,
        supports_local=True,
    ),
}

# Legacy/BYOK provider names accepted from stored rows and recruitment
# schemas, mapped onto a canonical spec. Azure/GigaChat expose
# OpenAI-compatible chat endpoints — their rows carry a ``base_url``.
PROVIDER_ALIASES: dict[str, str] = {
    "claude": "anthropic",
    "azure": "openai_compatible",
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
    """Provider owning this model name by prefix, or None when unknown.

    The longest matching prefix wins — "gpt://…" (Yandex model URIs)
    must not be claimed by the shorter OpenAI "gpt" prefix.
    """
    if not model:
        return None
    owner: str | None = None
    owner_len = -1
    for spec in PROVIDERS.values():
        for prefix in spec.classify_prefixes:
            if len(prefix) > owner_len and model.startswith(prefix):
                owner, owner_len = spec.name, len(prefix)
    return owner


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


def base_url_from_settings(provider_settings: dict[str, Any] | None) -> str | None:
    """The HTTP(S) ``base_url`` stored in a config row's ``settings`` JSON.

    Shared with the recruitment settings validator, which has the raw dict
    rather than a row (HRP-498).
    """
    raw = (provider_settings or {}).get("base_url")
    if isinstance(raw, str) and raw.startswith(("http://", "https://")):
        return raw
    return None


def _row_base_url(row: Any) -> str | None:
    return base_url_from_settings(row.settings)


def row_key_status(row: Any, *, kind: str = "llm_provider") -> tuple[str | None, str]:
    """``(plaintext, status)`` for one BYOK config row.

    Status is ``missing`` / ``ok`` / ``decrypt_failed``; see
    :func:`app.core.crypto.decrypt_optional_secret`. A stale key must not
    kill generation — every caller falls back to the platform credential —
    but callers that report configuration state need to tell "no key" from
    "unreadable key" (HRP-514).
    """
    from app.core.crypto import decrypt_optional_secret

    return decrypt_optional_secret(row.api_key_encrypted, context=f"{kind}:{row.id}")


def decrypt_row_key(row: Any, *, kind: str = "llm_provider") -> str | None:
    """Plaintext API key of a BYOK config row, or None when absent/stale.

    Shared with the transcription BYOK path, which used to pass the stored
    ciphertext to the provider as a Bearer token (HRP-506).
    """
    return row_key_status(row, kind=kind)[0]


def model_matches_provider(
    provider: str | None, model: str | None, base_url: str | None = None
) -> bool:
    """False only when a model name provably belongs to another provider.

    Prefix ownership says nothing about OpenAI-compatible proxies:
    ``openai_compatible`` owns no prefix at all (local model names are
    arbitrary) and ``azure``/``gigachat`` canonicalize onto it while
    serving upstream ids verbatim — ``{provider: "azure", model:
    "gpt-4o"}`` is the *normal* Azure configuration. Treating it as a
    mismatch rejected every proxy BYOK row (HRP-498 review). The same
    applies to any row carrying a ``base_url``: there the endpoint, not
    the model name, decides what is served (see :func:`_pick_target`).
    """
    canonical = resolve_provider_name(provider)
    if canonical is None or not model:
        return True
    if canonical == "openai_compatible" or base_url is not None:
        return True
    owner = classify_model(model)
    return owner is None or owner == canonical


def row_is_consistent(row: Any) -> bool:
    """False when a config row's model belongs to another provider.

    HRP-498 backfilled and now validates such pairs, but a row saved
    before the guard (or edited straight in the DB) must not become a
    dispatch target — its provider would 404 on a model it never served.
    """
    return model_matches_provider(row.provider, row.model, _row_base_url(row))


def yandex_byok_model_is_self_contained(
    model: str | None, base_url: str | None
) -> bool:
    """Whether a keyed Yandex row would actually be dispatched.

    Mirrors the skip inside ``_pick_target``: without a ``base_url`` a
    Yandex row is self-contained only when its model URI carries the
    folder (``gpt://<folder>/…``) — a short name would pair the tenant's
    key with the operator's folder. The save path refuses such rows up
    front (HRP-599 review): a silently skipped BYOK key means the
    platform pays for what the tenant thinks is their own usage.
    """
    return base_url is not None or (model or "").startswith("gpt://")


def _pick_target(rows: list[Any], model: str | None) -> GenerationTarget | None:
    """Resolve a tenant's config rows against the requested model.

    Match order: exact model match first (local model names are arbitrary,
    prefixes can't classify them), then any row for the model's classified
    provider. Rows with an unknown provider name are skipped.
    """
    classified = classify_model(model)

    def _target(row: Any, provider: str) -> GenerationTarget | None:
        base_url = _row_base_url(row)
        api_key = decrypt_row_key(row)
        if provider == "yandex":
            # Stays on the yandex dispatch (model-URI expansion) even with
            # a base_url — relabeling these rows openai_compatible sent the
            # bare short name upstream (review fix). Yandex keys are
            # folder-scoped, so a keyed row without a base_url is
            # self-contained only when its model URI carries the folder;
            # a short-name row would pair the tenant key with the
            # operator's folder — skip it like a base_url-less local row.
            if base_url is None and not (row.model or "").startswith("gpt://"):
                # Rows like this predate the save-time guard
                # (ensure_yandex_model_is_dispatchable) — leave a trace:
                # the tenant thinks their key is in use, but the request
                # is about to fall back to the platform credential.
                logger.warning(
                    "yandex BYOK row %s skipped: model %r is not a "
                    "gpt:// URI and the row has no base_url",
                    row.id,
                    row.model,
                )
                return None
            if base_url is None and api_key is None:
                return None
            return GenerationTarget(
                provider="yandex",
                api_key=api_key,
                base_url=base_url,
                source="local" if base_url is not None else "byok",
                model=row.model or None,
            )
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
        if not row_is_consistent(row):
            # HRP-498 review: an exact model match does not redeem an
            # inconsistent row — {provider: "anthropic", model: "gpt-4o"}
            # would send gpt-4o to Anthropic and 404. Only the *no model
            # requested* branch used to check this.
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
            if provider is None or not row_is_consistent(row):
                continue
            resolved = _target(row, provider)
            if resolved is not None:
                return resolved
    return None


def _accepts_unknown_models(provider: str) -> bool:
    """True when the provider serves arbitrary model names.

    Only local OpenAI-compatible servers do — their ids are whatever the
    operator loaded, so a name no prefix owns is normal there.
    """
    spec = PROVIDERS.get(provider)
    return bool(spec and spec.supports_local)


def _fallback_target(
    model: str | None, catalog_provider: str | None = None
) -> GenerationTarget:
    """Dispatch target when no tenant config row matched.

    HRP-502: an id no prefix owns used to be handed to whatever
    ``LLM_PROVIDER`` happens to be — Anthropic on the stock install — so a
    mistyped or newly-named OpenAI model went out on the platform's
    Anthropic key and came back as a provider-side 404 nobody could act on.

    Resolution order: the prefix table, then the catalog (a discovered row
    records which provider's API listed the id), then the platform default.
    The default still takes an unclassifiable name — an installation
    running ``LLM_PROVIDER=openai`` with a key set has always served new
    OpenAI families whose prefix this table does not know yet, and refusing
    those would break working setups (review fix). It is logged, because
    the same fallback is what carried mistyped ids to the wrong vendor.

    The refusal is kept for the one case where dispatch cannot work at all:
    a default provider with no credentials to call it with. Better a clear
    422 than a provider-side auth error.

    ``model=None`` is not an error: the caller pinned no model and the
    platform default supplies both the provider and the model.
    """
    provider = classify_model(model) or resolve_provider_name(catalog_provider)
    if provider is not None:
        return GenerationTarget(provider=provider)

    default = default_provider()
    if not model or _accepts_unknown_models(default):
        return GenerationTarget(provider=default)

    if global_key(default) is None:
        logger.warning(
            "generation: model %s matches no provider and the default (%s) has "
            "no key — refusing to dispatch",
            model,
            default,
        )
        raise AppError(
            "llm_model_provider_unresolved",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            model=model,
        )

    logger.warning(
        "generation: model %s matches no provider and is not in the catalog — "
        "dispatching to the platform default (%s); check the id if it 404s",
        model,
        default,
    )
    return GenerationTarget(provider=default)


async def _catalog_provider(db: AsyncSession, model: str | None) -> str | None:
    """Provider the model catalog records for ``model``.

    Skipped unless the prefix table came up empty — this is a fallback,
    and generation must not pay for a query it will not use.
    """
    if not model or classify_model(model) is not None:
        return None
    from app.modules.ai import model_catalog_service

    return await model_catalog_service.provider_for_model(db, model)


def _catalog_provider_sync(db: Session, model: str | None) -> str | None:
    """Sync twin of :func:`_catalog_provider`."""
    if not model or classify_model(model) is not None:
        return None
    from app.modules.ai import model_catalog_service

    return model_catalog_service.provider_for_model_sync(db, model)


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
    picked = _pick_target(rows, model)
    if picked is not None:
        return picked
    return _fallback_target(model, await _catalog_provider(db, model))


def resolve_generation_target_sync(
    db: Session, tenant_id: uuid.UUID, model: str | None
) -> GenerationTarget:
    """Sync twin of :func:`resolve_generation_target` for Celery workers
    that hold a synchronous Session (recruitment analysis tasks)."""
    rows = list(db.execute(_rows_query(tenant_id)).scalars().all())
    picked = _pick_target(rows, model)
    if picked is not None:
        return picked
    return _fallback_target(model, _catalog_provider_sync(db, model))


async def configured_providers(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Per-provider availability for the admin UI.

    A provider is configured when any credential source exists for it:
    ``byok`` (tenant key), ``local`` (tenant base_url), or ``global``
    (platform env key). Only configured providers should be offered in
    model/provider selectors.

    HRP-514: a non-empty ciphertext is not a usable key. When it fails to
    decrypt, generation silently falls back to the platform key, so the
    row must not be reported as BYOK — ``key_status`` carries
    ``decrypt_failed`` instead, and the effective source is whatever the
    fallback actually uses.
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
        key_status: str | None = None
        for row in by_provider.get(spec.name, []):
            if _row_base_url(row) is not None:
                # A local row needs no key at all — a ``decrypt_failed``
                # picked up from an unrelated earlier row of the same
                # provider must not be reported against it.
                source = "local"
                key_status = None
                break
            plaintext, status = row_key_status(row)
            if status == "decrypt_failed" and key_status is None:
                key_status = "decrypt_failed"
            if plaintext is not None and source is None:
                source = "byok"
                key_status = "ok"
        if source is None and global_key(spec.name) is not None:
            source = "global"
        out.append(
            {
                "provider": spec.name,
                "label": spec.label,
                "configured": source is not None,
                "source": source,
                "supports_local": spec.supports_local,
                "key_status": key_status,
            }
        )
    return out
