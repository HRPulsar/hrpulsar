"""Canonical LLM model identifiers — single source of truth.

Both ``ai_settings.service.EFFORT_PRESETS`` and ``ai.llm_client`` reference the
constants below so a model rename lands in exactly one place. This module is a
leaf (imports nothing from ``app.modules``) to stay cycle-free.
"""

from __future__ import annotations

# --- Anthropic ---------------------------------------------------------------
ANTHROPIC_FAST = "claude-haiku-4-5-20251001"
ANTHROPIC_BALANCED = "claude-sonnet-4-6"
ANTHROPIC_THOROUGH = "claude-opus-4-7"

# --- OpenAI ------------------------------------------------------------------
OPENAI_FAST = "gpt-4o-mini"
OPENAI_BALANCED = "gpt-4o"
OPENAI_THOROUGH = "gpt-4o"

# --- Gemini ------------------------------------------------------------------
GEMINI_FAST = "gemini-2.5-flash"
GEMINI_BALANCED = "gemini-2.5-pro"
GEMINI_THOROUGH = "gemini-2.5-pro"

# --- Embeddings --------------------------------------------------------------
EMBEDDING_MODEL = "text-embedding-3-small"

# Per-effort provider -> model maps consumed by ``EFFORT_PRESETS``.
FAST_MODELS: dict[str, str] = {
    "anthropic": ANTHROPIC_FAST,
    "openai": OPENAI_FAST,
    "gemini": GEMINI_FAST,
}
BALANCED_MODELS: dict[str, str] = {
    "anthropic": ANTHROPIC_BALANCED,
    "openai": OPENAI_BALANCED,
    "gemini": GEMINI_BALANCED,
}
THOROUGH_MODELS: dict[str, str] = {
    "anthropic": ANTHROPIC_THOROUGH,
    "openai": OPENAI_THOROUGH,
    "gemini": GEMINI_THOROUGH,
}

# HRP-122: per-model standard-API output ceilings, keyed by model-name prefix.
# ``claude-haiku-4-5`` is a prefix of ``ANTHROPIC_FAST`` (matched via startswith).
ANTHROPIC_OUTPUT_CAPS: dict[str, int] = {
    "claude-haiku-4-5": 8192,
    ANTHROPIC_BALANCED: 64000,
    ANTHROPIC_THOROUGH: 32000,
}

# HRP-134: OpenAI chat-completions output ceilings. gpt-4o rejects
# max_tokens above 16384 with HTTP 400, so callers asking for a bigger
# budget (vacancy profiles on Cyrillic tenants) must be clamped the same
# way Anthropic models are. Unknown OpenAI models fall back to 16384.
OPENAI_OUTPUT_CAPS: dict[str, int] = {
    "gpt-4o-mini": 16384,
    "gpt-4o": 16384,
}
OPENAI_DEFAULT_OUTPUT_CAP = 16384
