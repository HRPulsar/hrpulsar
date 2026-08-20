"""Canonical LLM model identifiers — single source of truth.

Both ``ai_settings.service.EFFORT_PRESETS`` and ``ai.llm_client`` reference the
constants below so a model rename lands in exactly one place. This module is a
leaf (imports nothing from ``app.modules``) to stay cycle-free.
"""

from __future__ import annotations

# --- Anthropic ---------------------------------------------------------------
ANTHROPIC_FAST = "claude-haiku-4-5-20251001"
ANTHROPIC_BALANCED = "claude-sonnet-5"
ANTHROPIC_THOROUGH = "claude-opus-4-8"
# Optional pickable flagship — never a tier default (always-on thinking and
# stricter refusal semantics make it a deliberate, opt-in choice).
ANTHROPIC_FABLE = "claude-fable-5"

# --- OpenAI ------------------------------------------------------------------
OPENAI_FAST = "gpt-4o-mini"
OPENAI_BALANCED = "gpt-4o"
OPENAI_THOROUGH = "gpt-4o"

# --- Gemini ------------------------------------------------------------------
GEMINI_FAST = "gemini-2.5-flash"
GEMINI_BALANCED = "gemini-2.5-pro"
GEMINI_THOROUGH = "gemini-2.5-pro"

# --- Yandex ------------------------------------------------------------------
# Short names; the dispatch completes them into gpt://<folder>/<name>/latest
# URIs from ``settings.yandex_folder_id`` (HRP-599).
YANDEX_FAST = "yandexgpt-lite"
YANDEX_BALANCED = "yandexgpt"
YANDEX_THOROUGH = "yandexgpt"

# --- Embeddings --------------------------------------------------------------
EMBEDDING_MODEL = "text-embedding-3-small"

# Per-effort provider -> model maps consumed by ``EFFORT_PRESETS``.
FAST_MODELS: dict[str, str] = {
    "anthropic": ANTHROPIC_FAST,
    "openai": OPENAI_FAST,
    "gemini": GEMINI_FAST,
    "yandex": YANDEX_FAST,
}
BALANCED_MODELS: dict[str, str] = {
    "anthropic": ANTHROPIC_BALANCED,
    "openai": OPENAI_BALANCED,
    "gemini": GEMINI_BALANCED,
    "yandex": YANDEX_BALANCED,
}
THOROUGH_MODELS: dict[str, str] = {
    "anthropic": ANTHROPIC_THOROUGH,
    "openai": OPENAI_THOROUGH,
    "gemini": GEMINI_THOROUGH,
    "yandex": YANDEX_THOROUGH,
}

# HRP-122: per-model standard-API output ceilings, keyed by model-name prefix.
# ``claude-haiku-4-5`` is a prefix of ``ANTHROPIC_FAST`` (matched via startswith).
ANTHROPIC_OUTPUT_CAPS: dict[str, int] = {
    "claude-haiku-4-5": 8192,
    ANTHROPIC_BALANCED: 64000,
    ANTHROPIC_THOROUGH: 32000,
    # Fable budgets above the 32768 non-streaming threshold stream, which
    # suits its long always-thinking turns.
    ANTHROPIC_FABLE: 64000,
    # HRP-500 (review #7): the previous generation is still served by
    # Anthropic and still reachable through BYOK rows saved before the
    # rename. Dropping them from this map silently clamped their budget to
    # the 8192 fallback, so competence generation (64000) and recruitment
    # (32768) truncated mid-JSON instead of returning.
    "claude-sonnet-4-6": 64000,
    "claude-opus-4-7": 32000,
}

# Anthropic removed sampling params on newer models: Opus 4.7+, Sonnet 5, and
# Fable 5 reject ``temperature``/``top_p``/``top_k`` with HTTP 400. Families
# listed here still accept ``temperature``; unknown or future models default
# to omitting it, which is always safe (the server-side default applies).
_ANTHROPIC_TEMPERATURE_OK_PREFIXES: tuple[str, ...] = (
    "claude-haiku-4-5",
    "claude-sonnet-4-",
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-opus-4-0",
    "claude-3",
)


def anthropic_accepts_temperature(model: str) -> bool:
    """True when this Anthropic model still accepts the ``temperature`` param."""
    return model.startswith(_ANTHROPIC_TEMPERATURE_OK_PREFIXES)


# HRP-134: OpenAI chat-completions output ceilings. gpt-4o rejects
# max_tokens above 16384 with HTTP 400, so callers asking for a bigger
# budget (vacancy profiles on Cyrillic tenants) must be clamped the same
# way Anthropic models are. Unknown OpenAI models fall back to 16384.
OPENAI_OUTPUT_CAPS: dict[str, int] = {
    "gpt-4o-mini": 16384,
    "gpt-4o": 16384,
    # Reasoning models bill hidden reasoning tokens against the same
    # budget, so their ceiling is an order of magnitude higher than the
    # chat families'. The first o-series generation is the exception: both
    # preview variants ship a much smaller completion window than the
    # 100k the family default suggests, and asking for more is an HTTP
    # 400. Matching is longest-prefix (``_clamp_openai_max_tokens``), so
    # these win over the bare "o1" entry.
    "o1-mini": 65536,
    "o1-preview": 32768,
    "o1": 100000,
    "o3": 100000,
    "o4": 100000,
}
OPENAI_DEFAULT_OUTPUT_CAP = 16384

# HRP-500 (review #9): the o-series reasoning models reject `temperature`
# and take their output budget as `max_completion_tokens`; sending the
# chat-completions shape returns HTTP 400 for every AI action. Discovery
# legitimately lists them (they are chat-capable), so the dispatch has to
# know the difference.
_OPENAI_REASONING_PREFIXES: tuple[str, ...] = ("o1", "o3", "o4")


def openai_is_reasoning_model(model: str) -> bool:
    """True for OpenAI o-series reasoning models."""
    return model.startswith(_OPENAI_REASONING_PREFIXES)


# The first o-series generation predates the `developer` role and rejects a
# `system` message outright ("Unsupported value: 'messages[0].role'"). Later
# reasoning models (o1, o3, o4-mini) accept one, so the carve-out stays
# narrow: only these two need the system prompt folded into the user turn.
_OPENAI_NO_SYSTEM_ROLE_PREFIXES: tuple[str, ...] = ("o1-mini", "o1-preview")


def openai_accepts_system_role(model: str) -> bool:
    """False for OpenAI models that reject a `system` message with HTTP 400."""
    return not model.startswith(_OPENAI_NO_SYSTEM_ROLE_PREFIXES)


# HRP-432: Gemini output ceilings, keyed by model-name prefix like the
# maps above. The 2.5 family accepts 65536 output tokens; older or
# unknown Gemini models fall back to a conservative 8192 so an over-cap
# request surfaces as an honest truncation instead of an HTTP 400.
GEMINI_OUTPUT_CAPS: dict[str, int] = {
    "gemini-2.5": 65536,
}
GEMINI_DEFAULT_OUTPUT_CAP = 8192
