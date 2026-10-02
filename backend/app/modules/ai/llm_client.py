"""Unified LLM client. Supports Claude, OpenAI, Gemini, and OpenAI-compatible
local servers (Ollama/vLLM/LM Studio via a per-tenant ``base_url``)."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

import anthropic
import httpx
import openai
from fastapi import status
from google import genai
from pydantic import BaseModel

from app.config import settings
from app.core import ai_usage_hooks, url_guard
from app.core.errors import AppError
from app.modules.ai import model_registry, providers

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.ai_settings.models import TenantAISettings

SchemaT = TypeVar("SchemaT", bound=BaseModel)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Usage:
    """Token counts a provider reported for one call; None = not reported."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None


def _openai_usage(response: Any) -> _Usage:
    usage = getattr(response, "usage", None)
    details = getattr(usage, "prompt_tokens_details", None)
    return _Usage(
        input_tokens=getattr(usage, "prompt_tokens", None),
        output_tokens=getattr(usage, "completion_tokens", None),
        cache_read_tokens=getattr(details, "cached_tokens", None),
    )


def _anthropic_usage(response: Any) -> _Usage:
    usage = getattr(response, "usage", None)
    return _Usage(
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", None),
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None),
    )


def _gemini_usage(response: Any) -> _Usage:
    meta = getattr(response, "usage_metadata", None)
    candidates = getattr(meta, "candidates_token_count", None)
    thoughts = getattr(meta, "thoughts_token_count", None)
    # 2.5 models bill thinking as output but report it apart (HRP-966).
    output = (
        None
        if candidates is None and thoughts is None
        else (candidates or 0) + (thoughts or 0)
    )
    return _Usage(
        input_tokens=getattr(meta, "prompt_token_count", None),
        output_tokens=output,
        cache_read_tokens=getattr(meta, "cached_content_token_count", None),
    )


# `provider` inside generate() is the dispatch key; the journal wants the
# catalog name (HRP-964).
_PROVIDER_CODES = {"claude": "anthropic"}
_SOURCE_CODES = {"global": "platform"}


def _provenance(
    provider: str, target: providers.GenerationTarget | None
) -> tuple[str, str]:
    """(provider code, credential source) for the journal."""
    if target is not None:
        return target.provider, _SOURCE_CODES.get(target.source, target.source)
    return _PROVIDER_CODES.get(provider, provider), "platform"


def _error_code(exc: BaseException) -> str:
    return exc.code if isinstance(exc, AppError) else type(exc).__name__


async def _record(
    kind: str,
    provider: str,
    model: str,
    credential_source: str,
    started: float,
    status: str,
    *,
    usage: _Usage | None = None,
    error_code: str | None = None,
) -> None:
    usage = usage or _Usage()
    record = ai_usage_hooks.CallRecord(
        kind=kind,
        provider=provider,
        model=model,
        credential_source=credential_source,
        latency_ms=int((time.perf_counter() - started) * 1000),
        status=status,
        error_code=error_code,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
    )
    try:
        await ai_usage_hooks.record_call(record)
    except Exception:  # noqa: BLE001 — the journal must never break a call
        logger.exception("AI usage record failed (model=%s)", model)


class LLMOutputTruncatedError(RuntimeError):
    """The model stopped at the max_tokens ceiling — output is incomplete.

    Every production caller consumes JSON; letting a clipped response
    reach ``json.loads`` surfaces as an opaque ``Unterminated string``
    error, so the provider helpers raise this instead. Callers that hit
    it should retry with a larger ``max_tokens`` budget or trim the
    prompt.
    """

    def __init__(self, model: str, max_tokens: int, usage: _Usage | None = None) -> None:
        super().__init__(
            f"LLM output truncated: {model} stopped at the max_tokens "
            f"ceiling ({max_tokens}); increase the max_tokens budget or "
            "reduce the requested output size"
        )
        self.usage = usage


# Provider clients, cached per (provider, key fingerprint, base_url) so BYOK
# tenants get their own client while the common global-key path still reuses
# one connection pool (HRP-465). The fingerprint keeps raw keys out of the
# cache keys (and out of any accidental debug output).
#
# HRP-501: bounded LRU. Every distinct fingerprint (a rotated BYOK key, a
# new tenant base_url) used to add a client — with its whole connection
# pool — that was never released, so a BYOK fleet leaked file descriptors
# for the process lifetime. Evicted clients are closed; the ceiling is
# generous enough that the hot set (platform keys + active BYOK tenants)
# never thrashes.
_CLIENT_CACHE_MAX = 64
_client_cache: OrderedDict[tuple[str, str, str], Any] = OrderedDict()

# HRP-501 review: eviction used to close the client immediately, but the
# evicted entry may still be serving an in-flight generation (up to 600 s
# on the plain paths, 1800 s on the Anthropic streaming one) — closing the
# pool under it aborts a request that already cost the tenant credits.
# Wait out the widest request window (``_ANTHROPIC_STREAM_TIMEOUT_S``,
# literal here because it is defined further down) before releasing it;
# nothing can still be borrowing the client by then.
_EVICTED_CLIENT_GRACE_S = 1800.0

# Deferred closes must be strong-referenced: asyncio only keeps a weak
# reference to a running task, so a create_task() whose handle is dropped
# can be garbage-collected mid-sleep and never close anything.
_pending_closes: set[asyncio.Task[None]] = set()


# The cache key omits deployment mode, the operator allowlist and the
# proxy env — all read once, when the client is built (HRP-505). Those are
# process-immutable in production, so a cached client never needs to
# re-evaluate the guard; tests that monkeypatch them must clear the cache.
def _cache_key(
    provider: str, api_key: str | None, base_url: str | None
) -> tuple[str, str, str]:
    fingerprint = hashlib.sha256((api_key or "").encode()).hexdigest()[:16]
    return (provider, fingerprint, base_url or "")


async def _close_client(client: Any) -> None:
    """Release one evicted SDK client's connection pool.

    ``close()`` is a coroutine on the OpenAI/Anthropic async clients and a
    plain method on the Gemini one — accept both, and never let a failing
    close propagate into a generation call.
    """
    closer = getattr(client, "aclose", None) or getattr(client, "close", None)
    if closer is None:
        return
    try:
        result = closer()
        if inspect.isawaitable(result):
            await result
    except Exception:  # noqa: BLE001 — eviction is best-effort housekeeping
        logger.debug("evicted LLM client failed to close", exc_info=True)


def _cache_get(key: tuple[str, str, str]) -> Any | None:
    client = _client_cache.get(key)
    if client is not None:
        _client_cache.move_to_end(key)
    return client


async def _close_client_after_grace(client: Any) -> None:
    """Close an evicted client once no request can still be borrowing it."""
    try:
        await asyncio.sleep(_EVICTED_CLIENT_GRACE_S)
    except asyncio.CancelledError:
        # The loop is being torn down (Celery runs every task under its own
        # asyncio.run) — nothing is in flight any more, so release the pool
        # now instead of leaking it into the next task on this worker.
        await _close_client(client)
        raise
    await _close_client(client)


def _schedule_close(client: Any) -> None:
    """Hand an evicted client to the deferred-close task, if we can."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None or loop.is_closed():
        # Built outside a loop (sync Celery bootstrap, tests) — drop the
        # reference and let GC reclaim the pool; there is no loop to run
        # the async close on.
        logger.debug("evicted LLM client dropped without a loop to close it on")
        return
    task = loop.create_task(_close_client_after_grace(client))
    _pending_closes.add(task)
    task.add_done_callback(_pending_closes.discard)


def _cache_put(key: tuple[str, str, str], client: Any) -> None:
    _client_cache[key] = client
    _client_cache.move_to_end(key)
    while len(_client_cache) > _CLIENT_CACHE_MAX:
        _, evicted = _client_cache.popitem(last=False)
        _schedule_close(evicted)


# HRP-599: Yandex Foundation Models' OpenAI-compatible endpoint. Generation
# reuses the whole OpenAI path (client cache, transport, no clamping — the
# server enforces its own limits); only the model name needs completing
# into a full URI.
YANDEX_BASE_URL = "https://llm.api.cloud.yandex.net/v1"


def _get_openai(
    api_key: str | None = None, base_url: str | None = None
) -> openai.AsyncOpenAI:
    key = _cache_key("openai", api_key, base_url)
    client = _cache_get(key)
    if client is None:
        # A tenant-supplied base_url must NEVER fall back to the platform
        # key: the key would be sent as a Bearer token to an arbitrary
        # host. Local OpenAI-compatible servers usually run without auth,
        # but the SDK insists on a non-empty key.
        effective_key = api_key or (
            "not-needed" if base_url else settings.openai_api_key
        )
        # HRP-505 request-time SSRF layer: on saas a tenant-supplied
        # base_url gets a client that re-validates DNS and pins the public
        # IP on every request, with redirects disabled (the record may
        # have changed since save-time validation). None → SDK default
        # (onprem, platform endpoint, operator allowlist). The hardcoded
        # Yandex platform endpoint is not tenant-supplied: it keeps the
        # SDK transport and its retries like every other platform provider.
        http_client: httpx.AsyncClient | None = None
        if base_url is not None and base_url != YANDEX_BASE_URL:
            http_client = url_guard.tenant_endpoint_http_client(
                base_url,
                error_code="llm_base_url_not_public",
                timeout=httpx.Timeout(600.0, connect=30.0),
            )
        # A guarded client rejects a blocked endpoint deterministically —
        # the SDK's default 3 retries would only re-resolve and re-reject
        # it (4 DNS lookups, ~3 s) while burying the guard's AppError under
        # an opaque APIConnectionError. One attempt; transient upstream
        # retries on a tenant endpoint are the caller's concern (HRP-505).
        max_retries = 0 if http_client is not None else 3
        client = openai.AsyncOpenAI(
            api_key=effective_key,
            base_url=base_url,
            max_retries=max_retries,
            timeout=httpx.Timeout(600.0, connect=30.0),
            http_client=http_client,
        )
        _cache_put(key, client)
    return client


def _get_anthropic(api_key: str | None = None) -> anthropic.AsyncAnthropic:
    key = _cache_key("anthropic", api_key, None)
    client = _cache_get(key)
    if client is None:
        client = anthropic.AsyncAnthropic(
            api_key=api_key or settings.anthropic_api_key,
            max_retries=3,
            timeout=httpx.Timeout(600.0, connect=30.0),
        )
        _cache_put(key, client)
    return client


def _get_gemini(api_key: str | None = None) -> genai.Client:
    key = _cache_key("gemini", api_key, None)
    client = _cache_get(key)
    if client is None:
        client = genai.Client(api_key=api_key or settings.gemini_api_key)
        _cache_put(key, client)
    return client


async def generate(
    prompt: str,
    system: str | Sequence[str] | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 8192,
    tenant_settings: TenantAISettings | None = None,
    *,
    top_p: float | None = None,
    seed: int | None = None,
    db: AsyncSession | None = None,
    tenant_id: uuid.UUID | None = None,
    credentials: providers.GenerationTarget | None = None,
) -> str:
    """Send a prompt to LLM and return the text response.

    Explicit `model` / `temperature` arguments always win. When omitted,
    `tenant_settings` (if provided) supplies the effective values via
    `app.modules.ai_settings.service`.

    HRP-1005: a `credentials` target with `forced_model=True` overrides
    that — the tenant's processor list replaced the requested model with
    an allowed substitute, so `target.model` is dispatched even when the
    caller passed a `model` of its own.

    HRP-951 — `system` may be a list of blocks: the first is a pipeline's
    static prefix, the same bytes on every call, and Anthropic is asked to
    cache it; the blocks after it vary per call. Every other provider gets
    the blocks joined with a blank line — one system message, as before.

    HRP-921 — `top_p` / `seed` pin the sampling where the provider takes
    them (OpenAI, Gemini). Anthropic has no seed and rejects `top_p` next
    to `temperature`, so neither reaches it.

    HRP-465 — per-tenant credentials: pass `db` (+ `tenant_id`, defaulted
    from `tenant_settings`) to resolve the tenant's BYOK key or local
    OpenAI-compatible endpoint, which win over the platform env keys.
    Sync Celery callers resolve up front via
    `providers.resolve_generation_target_sync` and pass `credentials`
    directly. With neither, the platform env keys apply as before.
    """
    if tenant_settings is not None:
        from app.modules.ai_settings import service as ai_settings_service

        if model is None:
            # HRP-500: with a session, resolve through the catalog so a
            # model the platform admin disabled is not dispatched to
            # tenants that never pinned one (effort presets).
            model = (
                await ai_settings_service.get_effective_model_async(db, tenant_settings)
                if db is not None
                else ai_settings_service.get_effective_model(tenant_settings)
            )
        if temperature is None:
            temperature = ai_settings_service.get_effective_temperature(tenant_settings)
        if tenant_id is None:
            tenant_id = tenant_settings.tenant_id

    if temperature is None:
        temperature = 0.7

    target = credentials
    if target is None and db is not None and tenant_id is not None:
        target = await providers.resolve_generation_target(db, tenant_id, model)

    if target is not None and target.model and (model is None or target.forced_model):
        # The caller picked no model (recruitment pipeline) — the tenant's
        # BYOK/local config supplies both the credentials and the model.
        # HRP-1005: or the tenant's processor list replaced the model the
        # caller asked for.
        model = target.model

    # Model first, then provider: the default-model lookup falls back to
    # OpenAI when the configured provider has no key, and the provider must
    # follow that model instead of dispatching it to the keyless vendor
    # (HRP-599 review).
    model = model or _get_default_model()
    provider = _resolve_provider(model)

    api_key: str | None = None
    base_url: str | None = None
    if target is not None:
        api_key = target.api_key
        base_url = target.base_url
        if target.provider == "anthropic":
            provider = "claude"
        elif target.provider in ("gemini", "yandex"):
            provider = target.provider
        else:  # openai / openai_compatible
            provider = "openai"

    # A block list is the Anthropic caching layout; every other provider
    # takes one system message.
    system_text = (
        system if system is None or isinstance(system, str) else "\n\n".join(system)
    )

    provider_code, credential_source = _provenance(provider, target)
    started = time.perf_counter()
    try:
        if provider == "claude":
            text, usage = await _generate_anthropic(
                prompt, system, model, temperature, max_tokens, api_key=api_key
            )
        elif provider == "gemini":
            text, usage = await _generate_gemini(
                prompt,
                system_text,
                model,
                temperature,
                max_tokens,
                api_key=api_key,
                top_p=top_p,
                seed=seed,
            )
        elif provider == "yandex":
            text, usage = await _generate_yandex(
                prompt,
                system_text,
                model,
                temperature,
                max_tokens,
                api_key=api_key,
                base_url=base_url,
            )
        else:
            text, usage = await _generate_openai(
                prompt,
                system_text,
                model,
                temperature,
                max_tokens,
                api_key=api_key,
                base_url=base_url,
                top_p=top_p,
                seed=seed,
            )
    except LLMOutputTruncatedError as exc:
        logger.warning("LLM output truncated (provider=%s, model=%s)", provider, model)
        await _record(
            "generate", provider_code, model, credential_source, started,
            "truncated", usage=exc.usage, error_code="output_truncated",
        )
        raise
    except Exception as exc:
        logger.exception(
            "LLM generation failed (provider=%s, model=%s)", provider, model
        )
        await _record(
            "generate", provider_code, model, credential_source, started,
            "error", usage=getattr(exc, "usage", None), error_code=_error_code(exc),
        )
        raise
    await _record("generate", provider_code, model, credential_source, started, "ok", usage=usage)
    return text


async def generate_json(
    prompt: str,
    system: str | Sequence[str] | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tenant_settings: TenantAISettings | None = None,
    schema: type[BaseModel] | None = None,
    *,
    top_p: float | None = None,
    seed: int | None = None,
    db: AsyncSession | None = None,
    tenant_id: uuid.UUID | None = None,
    credentials: providers.GenerationTarget | None = None,
) -> dict | list | BaseModel:
    """Generate and parse JSON from LLM response.

    When `schema` is supplied, its JSON Schema is appended to the system
    prompt (so the model knows the contract) and the parsed payload is
    validated through `schema.model_validate(...)` — the function then
    returns an instance of `schema`, not a raw dict. Without `schema`, the
    behaviour matches the original loose JSON path.

    `max_tokens` overrides the per-call output budget. Without it the
    underlying `generate()` keeps its 8192 default — fine for small
    structured outputs, too small for large tree-shaped payloads. Callers
    that ship JSON-Schema-constrained outputs (HRP-122: competence
    generation) should bump this to keep the LLM from truncating mid-JSON.

    Validation errors propagate to the caller (Pydantic `ValidationError`
    or `json.JSONDecodeError`); retry budgeting is the caller's concern.
    """
    if temperature is None and tenant_settings is None:
        temperature = 0.3

    if schema is not None:
        schema_block = (
            "Return JSON that strictly conforms to this JSON Schema. "
            "Do not add fields outside the schema. Do not include comments "
            "or trailing prose:\n"
            f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
        )
        if system is None or isinstance(system, str):
            system = f"{system}\n\n{schema_block}" if system else schema_block
        else:
            # After the cached prefix: the schema differs by call shape.
            system = [*system, schema_block]

    generate_kwargs: dict[str, Any] = {
        "system": system,
        "model": model,
        "temperature": temperature,
        "top_p": top_p,
        "seed": seed,
        "tenant_settings": tenant_settings,
        "db": db,
        "tenant_id": tenant_id,
        "credentials": credentials,
    }
    if max_tokens is not None:
        generate_kwargs["max_tokens"] = max_tokens

    raw = await generate(prompt, **generate_kwargs)

    # Extract JSON from markdown code blocks if present
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0]

    parsed = json.loads(raw.strip())

    if schema is not None:
        return schema.model_validate(parsed)
    return parsed


async def get_embedding(text: str, model: str | None = None) -> list[float]:
    """Generate embedding vector for text."""
    model = model or _get_embedding_model()
    client = _get_openai()
    started = time.perf_counter()
    try:
        response = await client.embeddings.create(model=model, input=[text])
    except Exception as exc:
        await _record("embedding", "openai", model, "platform", started, "error", error_code=_error_code(exc))
        raise
    await _record("embedding", "openai", model, "platform", started, "ok", usage=_openai_usage(response))
    return response.data[0].embedding


async def get_embeddings_batch(
    texts: list[str], model: str | None = None
) -> list[list[float]]:
    """Generate embeddings for multiple texts."""
    model = model or _get_embedding_model()
    client = _get_openai()
    started = time.perf_counter()
    try:
        response = await client.embeddings.create(model=model, input=texts)
    except Exception as exc:
        await _record("embedding", "openai", model, "platform", started, "error", error_code=_error_code(exc))
        raise
    await _record("embedding", "openai", model, "platform", started, "ok", usage=_openai_usage(response))
    return [item.embedding for item in response.data]


# -- Private helpers --


async def _generate_openai(
    prompt: str,
    system: str | None,
    model: str,
    temperature: float,
    max_tokens: int,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    top_p: float | None = None,
    seed: int | None = None,
) -> tuple[str, _Usage]:
    client = _get_openai(api_key, base_url)
    messages: list[dict[str, str]] = []
    if system:
        if base_url is None and not model_registry.openai_accepts_system_role(model):
            # HRP-500 review: o1-mini/o1-preview reject a `system` message
            # with HTTP 400. The standard workaround is to fold it into the
            # first user turn — dropping it would silently lose the whole
            # JSON-schema contract generate_json appends there.
            prompt = f"{system}\n\n{prompt}"
        else:
            messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # HRP-134: gpt-4o family rejects max_tokens > 16384 with HTTP 400 —
    # clamp like the Anthropic path so callers can request one generous
    # budget across providers. A server behind a base_url (local
    # OpenAI-compatible, YandexGPT) gets one fixed cap instead (HRP-997).
    if base_url is None:
        max_tokens = _clamp_openai_max_tokens(model, max_tokens)
    else:
        max_tokens = min(max_tokens, model_registry.COMPATIBLE_OUTPUT_CAP)
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if base_url is None and model_registry.openai_is_reasoning_model(model):
        # HRP-500: o-series models reject `temperature` and `max_tokens`
        # with HTTP 400 — the budget goes in `max_completion_tokens` (it
        # also covers the hidden reasoning tokens) and sampling is fixed.
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["temperature"] = temperature
        kwargs["max_tokens"] = max_tokens
        # HRP-921: pinned sampling where the API takes it; the o-series
        # branch above rejects every sampling parameter.
        if top_p is not None:
            kwargs["top_p"] = top_p
        if seed is not None:
            kwargs["seed"] = seed
    try:
        response = await client.chat.completions.create(**kwargs)
    except openai.APIConnectionError as exc:
        # The request-time SSRF guard raises AppError from inside the
        # transport; the SDK wraps any send-time exception as a connection
        # error. Surface the guard's code so the tenant sees why the call
        # was refused instead of an opaque "Connection error" (HRP-505).
        if isinstance(exc.__cause__, AppError):
            raise exc.__cause__ from exc
        raise
    choice = response.choices[0]
    usage = _openai_usage(response)
    if choice.finish_reason == "length":
        raise LLMOutputTruncatedError(model, max_tokens, usage)
    return choice.message.content or "", usage


def _clamp_openai_max_tokens(model: str, requested: int) -> int:
    # Longest matching prefix wins: "o1-mini" carries its own ceiling and
    # must not inherit the wider "o1" one just because that key comes first
    # in the map (first-match made the table order load-bearing).
    cap = model_registry.OPENAI_DEFAULT_OUTPUT_CAP
    matched = -1
    for prefix, value in model_registry.OPENAI_OUTPUT_CAPS.items():
        if len(prefix) > matched and model.startswith(prefix):
            matched, cap = len(prefix), value
    return min(requested, cap)


def _yandex_model_uri(model: str) -> str:
    """Complete a short model name into a gpt://<folder>/<model> URI.

    Scheme-carrying ids pass verbatim: gpt:// URIs bring their own folder,
    and tuned models come as ds:// URIs that must not be nested inside a
    gpt:// one. Short names (registry presets: "yandexgpt",
    "yandexgpt-lite") need the installation's folder id — without one the
    request cannot be formed, and a clear config error beats a
    provider-side 404.
    """
    if "://" in model:
        return model
    folder = settings.yandex_folder_id
    if not folder:
        raise AppError(
            "llm_yandex_folder_missing", status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    suffix = "" if "/" in model else "/latest"
    return f"gpt://{folder}/{model}{suffix}"


async def _generate_yandex(
    prompt: str,
    system: str | None,
    model: str,
    temperature: float,
    max_tokens: int,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> tuple[str, _Usage]:
    # Key semantics mirror the OpenAI factory: the platform key applies
    # only on the platform endpoint — a tenant base_url (gateway/proxy row)
    # keeps the tenant's own key or none at all, never the platform one.
    # Model-URI expansion is also endpoint-scoped: only the official
    # Yandex endpoint needs gpt://<folder>/… ids. A gateway row (alias-era
    # openai_compatible) serves whatever model name it was saved with —
    # expanding it would 422 on installs without YANDEX_FOLDER_ID or leak
    # the operator's folder id to a tenant-controlled endpoint.
    if base_url is None:
        base_url = YANDEX_BASE_URL
        api_key = api_key or settings.yandex_api_key
        if not api_key:
            raise AppError(
                "llm_yandex_key_missing", status.HTTP_422_UNPROCESSABLE_CONTENT
            )
        model = _yandex_model_uri(model)
    return await _generate_openai(
        prompt,
        system,
        model,
        temperature,
        max_tokens,
        api_key=api_key,
        base_url=base_url,
    )


def _anthropic_system(system: str | Sequence[str]) -> str | list[dict[str, Any]]:
    """A plain string goes as it is. A block list is the pipeline's static
    prefix first, marked for prompt caching (HRP-951: the breakdown's rules,
    catalog and examples are 6-7k tokens repeated on both calls of a session
    and on every reclassification), then the per-call blocks after the cache
    breakpoint. Below the provider's minimum (1024 tokens on Sonnet, 2048
    on Haiku) the mark is accepted and ignored."""
    if isinstance(system, str):
        return system
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text} for text in system]
    blocks[0]["cache_control"] = {"type": "ephemeral"}
    return blocks


async def _generate_anthropic(
    prompt: str,
    system: str | Sequence[str] | None,
    model: str,
    temperature: float,
    max_tokens: int,
    *,
    api_key: str | None = None,
) -> tuple[str, _Usage]:
    client = _get_anthropic(api_key)
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        # HRP-122: Anthropic models cap standard output per family — Haiku 4.5
        # rejects max_tokens > 8192 with HTTP 400 unless the extended-output
        # beta header is set. Clamp here so callers can ask for a generous
        # budget without breaking the cheapest preset.
        "max_tokens": _clamp_anthropic_max_tokens(model, max_tokens),
    }
    # Opus 4.7+/Sonnet 5/Fable 5 reject `temperature` with HTTP 400 — send it
    # only to models that still accept sampling params.
    if model_registry.anthropic_accepts_temperature(model):
        kwargs["temperature"] = temperature
    if system:
        kwargs["system"] = _anthropic_system(system)

    if kwargs["max_tokens"] > _ANTHROPIC_STREAM_THRESHOLD_TOKENS:
        # HRP-432: budgets above the proven non-streaming ceiling (tree
        # scopes at the 64k sonnet cap) exceed the SDK's non-streaming
        # request-time limits, so they stream; the outer bound replaces
        # the whole-response read timeout that streaming turns into a
        # per-chunk one. Smaller budgets keep the plain create() call —
        # there the SDK auto-retries mid-response transport failures,
        # which streaming only does for the initial connection.
        async with asyncio.timeout(_ANTHROPIC_STREAM_TIMEOUT_S):
            async with client.messages.stream(**kwargs) as stream:
                response = await stream.get_final_message()
    else:
        response = await client.messages.create(**kwargs)
    usage = _anthropic_usage(response)
    if response.stop_reason == "max_tokens":
        raise LLMOutputTruncatedError(model, kwargs["max_tokens"], usage)
    if not response.content:
        raise _with_usage(
            ValueError(
                f"Anthropic returned no content blocks (stop_reason={response.stop_reason})"
            ),
            usage,
        )
    # HRP-509: thinking-capable models (balanced/thorough catalog tiers)
    # emit a ThinkingBlock before the text — return the first text block,
    # not the first block.
    for block in response.content:
        text = getattr(block, "text", None)
        if text is not None:
            return text, usage
    block_types = ", ".join(type(block).__name__ for block in response.content)
    raise _with_usage(
        ValueError(
            f"Anthropic returned no text content block "
            f"(stop_reason={response.stop_reason}, blocks={block_types})"
        ),
        usage,
    )


def _with_usage(exc: Exception, usage: Any) -> Exception:
    """The tokens of an answer that came back unusable were billed all the
    same: ``generate`` journals them with the error (HRP-964)."""
    exc.usage = usage  # type: ignore[attr-defined]
    return exc


# HRP-432: 32768 is the largest budget proven to work through the
# non-streaming API in production (recruitment vacancy profiles); anything
# above it streams.
_ANTHROPIC_STREAM_THRESHOLD_TOKENS = 32768
_ANTHROPIC_STREAM_TIMEOUT_S = 1800


def _clamp_anthropic_max_tokens(model: str, requested: int) -> int:
    for prefix, cap in model_registry.ANTHROPIC_OUTPUT_CAPS.items():
        if model.startswith(prefix):
            return min(requested, cap)
    return min(requested, 8192)


async def _generate_gemini(
    prompt: str,
    system: str | None,
    model: str,
    temperature: float,
    max_tokens: int,
    *,
    api_key: str | None = None,
    top_p: float | None = None,
    seed: int | None = None,
) -> tuple[str, _Usage]:
    client = _get_gemini(api_key)
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    max_tokens = _clamp_gemini_max_tokens(model, max_tokens)

    config: genai.types.GenerateContentConfigDict = {
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }
    if top_p is not None:
        config["top_p"] = top_p
    if seed is not None:
        config["seed"] = seed
    response = await client.aio.models.generate_content(
        model=model, contents=full_prompt, config=config
    )
    candidates = response.candidates or []
    finish_reason = (
        getattr(candidates[0], "finish_reason", None) if candidates else None
    )
    usage = _gemini_usage(response)
    if finish_reason is not None and "MAX_TOKENS" in str(finish_reason):
        raise LLMOutputTruncatedError(model, max_tokens, usage)
    return response.text or "", usage


def _clamp_gemini_max_tokens(model: str, requested: int) -> int:
    for prefix, cap in model_registry.GEMINI_OUTPUT_CAPS.items():
        if model.startswith(prefix):
            return min(requested, cap)
    return min(requested, model_registry.GEMINI_DEFAULT_OUTPUT_CAP)


def _resolve_provider(model: str | None) -> str:
    """Determine provider from explicit model name or settings.

    Returns the legacy dispatch names ("claude"/"gemini"/"openai"); the
    prefix knowledge itself lives in ``providers.PROVIDERS`` (HRP-465).
    """
    if model:
        canonical = providers.classify_model(model)
        if canonical == "anthropic":
            return "claude"
        if canonical in ("gemini", "yandex"):
            return canonical
        return "openai"
    # No model: canonicalize the configured provider — LLM_PROVIDER accepts
    # both legacy ("claude") and canonical ("anthropic") names.
    canonical = providers.resolve_provider_name(settings.llm_provider)
    if canonical == "anthropic":
        return "claude"
    if canonical in ("gemini", "yandex"):
        return canonical
    return "openai"


def _get_default_model() -> str:
    # Mirrors `ai_settings.service.EFFORT_PRESETS["balanced"].models` (both read
    # `model_registry.BALANCED_MODELS`) so a caller without a `tenant_settings`
    # row gets the same model as the default tenant preset.
    # Canonical names so LLM_PROVIDER=anthropic (legal everywhere else)
    # does not silently fall through to the OpenAI model (HRP-599 review).
    provider = providers.resolve_provider_name(settings.llm_provider)
    if provider == "anthropic" and settings.anthropic_api_key:
        return model_registry.BALANCED_MODELS["anthropic"]
    if provider == "gemini" and settings.gemini_api_key:
        return model_registry.BALANCED_MODELS["gemini"]
    if provider == "yandex" and settings.yandex_api_key:
        return model_registry.BALANCED_MODELS["yandex"]
    return model_registry.BALANCED_MODELS["openai"]


def _get_embedding_model() -> str:
    return model_registry.EMBEDDING_MODEL
