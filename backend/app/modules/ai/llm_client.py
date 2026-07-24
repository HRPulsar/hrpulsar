"""Unified LLM client. Supports Claude, OpenAI, and Gemini."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, TypeVar

import anthropic
import httpx
import openai
from google import genai
from pydantic import BaseModel

from app.config import settings
from app.modules.ai import model_registry

if TYPE_CHECKING:
    from app.modules.ai_settings.models import TenantAISettings

SchemaT = TypeVar("SchemaT", bound=BaseModel)

logger = logging.getLogger(__name__)


class LLMOutputTruncatedError(RuntimeError):
    """The model stopped at the max_tokens ceiling — output is incomplete.

    Every production caller consumes JSON; letting a clipped response
    reach ``json.loads`` surfaces as an opaque ``Unterminated string``
    error, so the provider helpers raise this instead. Callers that hit
    it should retry with a larger ``max_tokens`` budget or trim the
    prompt.
    """

    def __init__(self, model: str, max_tokens: int) -> None:
        super().__init__(
            f"LLM output truncated: {model} stopped at the max_tokens "
            f"ceiling ({max_tokens}); increase the max_tokens budget or "
            "reduce the requested output size"
        )


# Provider clients (lazy init)
_openai_client: openai.AsyncOpenAI | None = None
_anthropic_client: anthropic.AsyncAnthropic | None = None
_gemini_client: genai.Client | None = None


def _get_openai() -> openai.AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = openai.AsyncOpenAI(
            api_key=settings.openai_api_key,
            max_retries=3,
            timeout=httpx.Timeout(600.0, connect=30.0),
        )
    return _openai_client


def _get_anthropic() -> anthropic.AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            max_retries=3,
            timeout=httpx.Timeout(600.0, connect=30.0),
        )
    return _anthropic_client


def _get_gemini() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=settings.gemini_api_key)
    return _gemini_client


async def generate(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 8192,
    tenant_settings: TenantAISettings | None = None,
) -> str:
    """Send a prompt to LLM and return the text response.

    Explicit `model` / `temperature` arguments always win. When omitted,
    `tenant_settings` (if provided) supplies the effective values via
    `app.modules.ai_settings.service`.
    """
    if tenant_settings is not None:
        from app.modules.ai_settings import service as ai_settings_service

        if model is None:
            model = ai_settings_service.get_effective_model(tenant_settings)
        if temperature is None:
            temperature = ai_settings_service.get_effective_temperature(tenant_settings)

    if temperature is None:
        temperature = 0.7

    provider = _resolve_provider(model)
    model = model or _get_default_model()

    try:
        if provider == "claude":
            return await _generate_anthropic(
                prompt, system, model, temperature, max_tokens
            )
        if provider == "gemini":
            return await _generate_gemini(
                prompt, system, model, temperature, max_tokens
            )
        return await _generate_openai(prompt, system, model, temperature, max_tokens)
    except Exception:
        logger.exception(
            "LLM generation failed (provider=%s, model=%s)", provider, model
        )
        raise


async def generate_json(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tenant_settings: TenantAISettings | None = None,
    schema: type[BaseModel] | None = None,
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
        system = f"{system}\n\n{schema_block}" if system else schema_block

    generate_kwargs: dict[str, Any] = {
        "system": system,
        "model": model,
        "temperature": temperature,
        "tenant_settings": tenant_settings,
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

    response = await client.embeddings.create(model=model, input=[text])
    return response.data[0].embedding


async def get_embeddings_batch(
    texts: list[str], model: str | None = None
) -> list[list[float]]:
    """Generate embeddings for multiple texts."""
    model = model or _get_embedding_model()
    client = _get_openai()

    response = await client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


# -- Private helpers --


async def _generate_openai(
    prompt: str, system: str | None, model: str, temperature: float, max_tokens: int
) -> str:
    client = _get_openai()
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # HRP-134: gpt-4o family rejects max_tokens > 16384 with HTTP 400 —
    # clamp like the Anthropic path so callers can request one generous
    # budget across providers.
    max_tokens = _clamp_openai_max_tokens(model, max_tokens)
    response = await client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,  # type: ignore[arg-type]
    )
    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise LLMOutputTruncatedError(model, max_tokens)
    return choice.message.content or ""


def _clamp_openai_max_tokens(model: str, requested: int) -> int:
    for prefix, cap in model_registry.OPENAI_OUTPUT_CAPS.items():
        if model.startswith(prefix):
            return min(requested, cap)
    return min(requested, model_registry.OPENAI_DEFAULT_OUTPUT_CAP)


async def _generate_anthropic(
    prompt: str, system: str | None, model: str, temperature: float, max_tokens: int
) -> str:
    client = _get_anthropic()
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        # HRP-122: Anthropic models cap standard output per family — Haiku 4.5
        # rejects max_tokens > 8192 with HTTP 400 unless the extended-output
        # beta header is set. Clamp here so callers can ask for a generous
        # budget without breaking the cheapest preset.
        "max_tokens": _clamp_anthropic_max_tokens(model, max_tokens),
    }
    if system:
        kwargs["system"] = system

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
    if response.stop_reason == "max_tokens":
        raise LLMOutputTruncatedError(model, kwargs["max_tokens"])
    if not response.content:
        raise ValueError(
            f"Anthropic returned no content blocks (stop_reason={response.stop_reason})"
        )
    block = response.content[0]
    text = getattr(block, "text", None)
    if text is None:
        raise ValueError(
            f"Anthropic first content block has no text ({type(block).__name__})"
        )
    return text


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
    prompt: str, system: str | None, model: str, temperature: float, max_tokens: int
) -> str:
    client = _get_gemini()
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    max_tokens = _clamp_gemini_max_tokens(model, max_tokens)

    response = await client.aio.models.generate_content(
        model=model,
        contents=full_prompt,
        config={
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        },
    )
    candidates = response.candidates or []
    finish_reason = (
        getattr(candidates[0], "finish_reason", None) if candidates else None
    )
    if finish_reason is not None and "MAX_TOKENS" in str(finish_reason):
        raise LLMOutputTruncatedError(model, max_tokens)
    return response.text or ""


def _clamp_gemini_max_tokens(model: str, requested: int) -> int:
    for prefix, cap in model_registry.GEMINI_OUTPUT_CAPS.items():
        if model.startswith(prefix):
            return min(requested, cap)
    return min(requested, model_registry.GEMINI_DEFAULT_OUTPUT_CAP)


def _resolve_provider(model: str | None) -> str:
    """Determine provider from explicit model name or settings."""
    if model:
        if model.startswith("claude"):
            return "claude"
        if model.startswith("gemini"):
            return "gemini"
        return "openai"
    return settings.llm_provider


def _get_default_model() -> str:
    # Mirrors `ai_settings.service.EFFORT_PRESETS["balanced"].models` (both read
    # `model_registry.BALANCED_MODELS`) so a caller without a `tenant_settings`
    # row gets the same model as the default tenant preset.
    provider = settings.llm_provider
    if provider == "claude" and settings.anthropic_api_key:
        return model_registry.BALANCED_MODELS["anthropic"]
    if provider == "gemini" and settings.gemini_api_key:
        return model_registry.BALANCED_MODELS["gemini"]
    return model_registry.BALANCED_MODELS["openai"]


def _get_embedding_model() -> str:
    return model_registry.EMBEDDING_MODEL
