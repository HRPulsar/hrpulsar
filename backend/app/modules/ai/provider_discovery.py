"""Provider model-list discovery adapters (HRP-466) — pure core.

One async function per provider, each returning ``[{model_id, label}]``.
Called by the daily ``refresh_model_catalog_task`` for every provider with
a configured platform key (``providers.global_key``). Failures propagate to
the task, which try/excepts per provider so one provider outage never
touches the others' catalog rows.

Filtering contract: only chat-generation models may pass — on community
installs a discovered model is auto-approved and immediately pickable, so
letting a TTS/embedding/image id through breaks generation for any tenant
that picks it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.ai import llm_client

# OpenAI lists every account-visible model. Prefixes come from the provider
# registry (``providers.PROVIDERS["openai"].classify_prefixes``); these
# markers then drop the non-chat variants that share the gpt-/o* prefixes
# (gpt-image-1, gpt-4o-audio-preview, gpt-4o-realtime-*, -transcribe/-tts,
# -instruct legacy completions, embeddings/moderation/search helpers).
_OPENAI_NON_CHAT_MARKERS: tuple[str, ...] = (
    "audio",
    "realtime",
    "transcribe",
    "tts",
    "image",
    "instruct",
    "embedding",
    "moderation",
    "search",
    "dall-e",
    "whisper",
)


async def discover_anthropic(api_key: str) -> list[dict[str, str]]:
    client = llm_client._get_anthropic(api_key)
    out: list[dict[str, str]] = []
    async for model in client.models.list():
        display = getattr(model, "display_name", None)
        out.append({"model_id": model.id, "label": display or model.id})
    return out


async def discover_openai(api_key: str) -> list[dict[str, str]]:
    from app.modules.ai import providers

    prefixes = providers.PROVIDERS["openai"].classify_prefixes
    client = llm_client._get_openai(api_key)
    out: list[dict[str, str]] = []
    async for model in client.models.list():
        if not model.id.startswith(prefixes):
            continue
        if any(marker in model.id for marker in _OPENAI_NON_CHAT_MARKERS):
            continue
        out.append({"model_id": model.id, "label": model.id})
    return out


async def discover_gemini(api_key: str) -> list[dict[str, str]]:
    client = llm_client._get_gemini(api_key)
    out: list[dict[str, str]] = []
    async for model in await client.aio.models.list():
        # Names come namespaced ("models/gemini-2.5-pro").
        raw: str = model.name or ""
        model_id = raw.removeprefix("models/")
        if not model_id.startswith("gemini"):
            continue
        # The listing carries every modality (embeddings, imagen bridges,
        # TTS) — only models that support generateContent can be dispatched
        # by the generation path.
        actions = getattr(model, "supported_actions", None) or []
        if "generateContent" not in actions:
            continue
        display = getattr(model, "display_name", None)
        out.append({"model_id": model_id, "label": display or model_id})
    return out


DISCOVERERS: dict[str, Callable[[str], Awaitable[list[dict[str, str]]]]] = {
    "anthropic": discover_anthropic,
    "openai": discover_openai,
    "gemini": discover_gemini,
}


def discoverable_providers() -> list[tuple[str, str]]:
    """(provider, api_key) pairs for providers with a configured global key.

    Iterates the provider registry (single source of truth) — providers
    without a discovery adapter (local OpenAI-compatible servers) or
    without a configured global key are skipped.
    """
    from app.modules.ai import providers

    out: list[tuple[str, str]] = []
    for name in providers.PROVIDERS:
        if name not in DISCOVERERS:
            continue
        key = providers.global_key(name)
        if key:
            out.append((name, key))
    return out


async def discover(provider: str, api_key: str) -> list[dict[str, Any]]:
    return await DISCOVERERS[provider](api_key)
