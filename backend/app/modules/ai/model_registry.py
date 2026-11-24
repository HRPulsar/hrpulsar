"""Canonical LLM model identifiers — single source of truth.

Both ``ai_settings.service.EFFORT_PRESETS`` and ``ai.llm_client`` reference the
constants below so a model rename lands in exactly one place. This module is a
leaf (imports nothing from ``app.modules``) to stay cycle-free.
"""

from __future__ import annotations

# --- Anthropic ---------------------------------------------------------------
ANTHROPIC_FAST = "claude-haiku-5-5"
ANTHROPIC_BALANCED = "claude-sonnet-5-5"
ANTHROPIC_THOROUGH = "claude-opus-5-5"
# Optional pickable flagship — never a tier default (long always-thinking
# turns, stricter refusal semantics and the premium price make it a
# deliberate, opt-in choice).
ANTHROPIC_FABLE = "claude-fable-5-2"

# --- OpenAI ------------------------------------------------------------------
# HRP-1240: the split OpenAI's model-selection guide recommends (Luna for
# small repeatable tasks, Sol as the default, Astra for demanding analysis).
OPENAI_FAST = "gpt-6-luna"
OPENAI_BALANCED = "gpt-6.2-sol"
OPENAI_THOROUGH = "gpt-6.2-astra"

# --- Gemini ------------------------------------------------------------------
# HRP-1240: stable ids; gemini-2.5-* is routed to 3.x models from 2026-12-01.
GEMINI_FAST = "gemini-3.5-flash-lite"
GEMINI_BALANCED = "gemini-4-hydrogen"
GEMINI_THOROUGH = "gemini-4-neon"

# --- Yandex ------------------------------------------------------------------
# Short names; the dispatch completes them into gpt://<folder>/<name>/latest
# URIs from ``settings.yandex_folder_id`` (HRP-599).
YANDEX_FAST = "yandexgpt-lite"
YANDEX_BALANCED = "yandexgpt"
YANDEX_THOROUGH = "yandexgpt"

# --- Decision provider (HRP-936) ---------------------------------------------
# Pinned version, never the ``jev-latest`` alias: per-code thresholds are
# tuned against one version, and an alias moves under them. Bumping it is a
# task of its own with a re-run of the HRP-937/938 measurements.
JEV_MODEL = "jev-1.13.0"
# Input tokens only; Jev output is free (docs.typesafe.ai/models, 23.09.2026).
JEV_USD_PER_MTOK_INPUT = 0.042

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

# HRP-1240: the tier models before the 2026-11 refresh — (provider, model,
# tier). Still served, still priced in credits.yaml and still pinned by
# tenants who picked one, so the catalog keeps seeding them, with the tier
# they held: an installation seeded before the refresh carries exactly
# these rows, a fresh one gets the same, and a disabled tier model falls
# back to its predecessor. The current tier model outranks them in a tier
# pick (``model_catalog_service._pick_tier_row``).
PREVIOUS_MODELS: tuple[tuple[str, str, str | None], ...] = (
    ("anthropic", "claude-haiku-4-5-20251001", "fast"),
    ("anthropic", "claude-sonnet-5", "balanced"),
    ("anthropic", "claude-opus-4-8", "thorough"),
    ("anthropic", "claude-fable-5", None),
    ("openai", "gpt-4o-mini", "fast"),
    ("openai", "gpt-4o", "balanced"),
    ("gemini", "gemini-2.5-flash", "fast"),
    ("gemini", "gemini-2.5-pro", "balanced"),
)


def output_cap(caps: dict[str, int], model: str, default: int) -> int:
    """Output ceiling of ``model``: the longest matching prefix wins.

    HRP-1240: first-match over overlapping prefixes ("claude-sonnet-5" /
    "claude-sonnet-5-5", "o1" / "o1-mini") made the dict order load-bearing.
    """
    cap, matched = default, -1
    for prefix, value in caps.items():
        if len(prefix) > matched and model.startswith(prefix):
            cap, matched = value, len(prefix)
    return cap


# HRP-1240: the tier models think or reason before they answer, out of the
# same output budget, while callers sized their budgets for the visible
# answer (4096 for learning materials, the 8192 default) — HRP-995 saw that
# cut a thinking model off. Reasoning models get at least this ceiling; it
# is only a ceiling, billed as used, and stays under the Anthropic
# non-streaming threshold (32768).
REASONING_MIN_OUTPUT_TOKENS = 16000

# HRP-122: per-model standard-API output ceilings, keyed by model-name prefix
# (longest match, ``output_cap``). Budgets above the 32768 non-streaming
# threshold stream. The 5.5 tier models think by default and their thinking
# spends the same budget, so every tier gets Sonnet's 64000.
ANTHROPIC_OUTPUT_CAPS: dict[str, int] = {
    ANTHROPIC_FAST: 64000,
    ANTHROPIC_BALANCED: 64000,
    ANTHROPIC_THOROUGH: 64000,
    ANTHROPIC_FABLE: 64000,
    # HRP-500 (review #7): the previous generations stay listed — Anthropic
    # still serves them and BYOK rows or custom picks saved before a rename
    # still reach them; a missing entry clamped competence generation
    # (64000) and recruitment (32768) to the fallback, truncated mid-JSON.
    "claude-haiku-4-5": 8192,
    "claude-sonnet-4-6": 64000,
    "claude-sonnet-5": 64000,
    "claude-opus-4-7": 32000,
    "claude-opus-4-8": 32000,
    "claude-opus-5": 64000,
    "claude-fable-5": 64000,
}
# HRP-1240: a family missing above (a model the nightly discovery found
# before this map knew it) used to fall back to 8192 and cut long answers.
# Every Anthropic model still served except Haiku 4.5 takes at least 32000
# (the 3.x models with smaller limits were all retired by 2026-04-20).
ANTHROPIC_DEFAULT_OUTPUT_CAP = 32000


def anthropic_thinks(model: str) -> bool:
    """True for the families that dropped sampling params: Sonnet 5+, Opus 5+,
    Haiku 5.5 and Fable think by default, out of the output budget. Opus
    4.7/4.8 are in the set too and do not — the reasoning floor is only a
    ceiling, so it costs them nothing."""
    return not anthropic_accepts_temperature(model)


# Anthropic removed sampling params on newer models: Opus 4.7+, Sonnet 5+,
# Haiku 5.5 and Fable 5+ reject ``temperature``/``top_p``/``top_k`` with HTTP
# 400. Families listed here still accept ``temperature``; unknown or future
# models default to omitting it, which is always safe (the server-side
# default applies).
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
    # HRP-1240: the API's own "supports at most N" on 2026-11-24.
    "gpt-4.1": 32768,
    "gpt-5": 128000,
    "gpt-6": 128000,
    # Reasoning models bill hidden reasoning tokens against the same
    # budget, so their ceiling is an order of magnitude higher than the
    # chat families'. The first o-series generation is the exception: both
    # preview variants ship a much smaller completion window than the
    # 100k the family default suggests, and asking for more is an HTTP
    # 400. Matching is longest-prefix (``output_cap``), so these win over
    # the bare "o1" entry.
    "o1-mini": 65536,
    "o1-preview": 32768,
    "o1": 100000,
    "o3": 100000,
    "o4": 100000,
}
OPENAI_DEFAULT_OUTPUT_CAP = 16384
# HRP-1240: the table holds the API limits; this is the path's. ponytail:
# the OpenAI path does not stream and its client times a silent response out
# at 600 s, so no request asks for more than 32768 — where the Anthropic path
# starts streaming (HRP-432). Stream it if a caller needs the full 128k.
OPENAI_NONSTREAMING_OUTPUT_CAP = 32768
# HRP-997: a server behind a base_url (a tenant's own OpenAI-compatible one,
# YandexGPT) serves models with limits we cannot look up. Requests above
# this cap are cut to it: a 32k-context server took the breakdown's 32768
# plus the prompt as a context overflow (HTTP 400) on every attempt.
# ponytail: one cap for every such server; a per-row limit on the
# provider config if a tenant's model needs more or less.
COMPATIBLE_OUTPUT_CAP = 16384

# HRP-500 (review #9): reasoning models reject `max_tokens` (HTTP 400 "Use
# 'max_completion_tokens' instead") and any non-default `temperature` or
# `top_p`; sending them the chat-completions shape fails every AI action.
# HRP-1240: every OpenAI model since GPT-5 is a reasoning model (OpenAI's
# model pages; probed 2026-11-24 from gpt-5 to gpt-6.2-sol), so the list is
# inverted: only the chat families named here keep the old shape, and an
# unknown or future model gets the reasoning one. A fine-tuned id
# ("ft:gpt-4o-mini:org::abc") is judged by its base model. "gpt-35" is
# Azure's spelling of gpt-3.5; gpt-oss is an open-weight chat model served
# by local servers (Ollama, llama.cpp), never by the OpenAI API.
_OPENAI_CHAT_SHAPE_PREFIXES: tuple[str, ...] = ("gpt-4", "gpt-3.5", "gpt-35", "gpt-oss")


def openai_is_reasoning_model(model: str) -> bool:
    """True unless the model is a chat family that takes sampling params."""
    return not model.removeprefix("ft:").startswith(_OPENAI_CHAT_SHAPE_PREFIXES)


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
    # HRP-1240: the 3.x and 4 families default to the same 65536 (thinking
    # tokens count against it).
    "gemini-3": 65536,
    "gemini-4": 65536,
}
GEMINI_DEFAULT_OUTPUT_CAP = 8192

# HRP-1240: from Gemini 3.6 / 3.5 Flash-Lite on, `temperature`, `top_p` and
# `top_k` are deprecated — ignored today, an HTTP 400 "in future model
# generations", and Google says to remove them from every request. Only the
# families listed here still get them; for 3.0/3.1 omitting temperature
# means its default 1.0, which Google recommended there anyway.
_GEMINI_SAMPLING_OK_PREFIXES: tuple[str, ...] = ("gemini-1", "gemini-2")


def gemini_accepts_sampling(model: str) -> bool:
    """True when this Gemini model still honours ``temperature``/``top_p``."""
    return model.startswith(_GEMINI_SAMPLING_OK_PREFIXES)
