"""Sanitize user-controlled text before composing an LLM prompt.

The system prompt instructs the model to ignore any directives inside
``<user_input>...</user_input>``. The helpers here:

1. Escape closing tags so adversarial input cannot break out of the
   wrapped block.
2. Strip control characters that can confuse tokenization or hide
   instructions in copy-paste.
3. Truncate to a safe upper bound so a pathological resume / transcript
   cannot blow out the token budget.

See RECRUITING_MODULE.md §9.4 (prompt injection sanitization).
"""

from __future__ import annotations

import re

MAX_USER_INPUT_CHARS = 80_000

_CLOSE_TAG = re.compile(r"</\s*user_input\s*>", re.IGNORECASE)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def sanitize_inline(text: str | None) -> str:
    """Escape and strip control chars, but do not wrap.

    Use this when you need to splice user text into a longer narrative
    section of the prompt rather than into a dedicated block.
    """

    if not text:
        return ""

    cleaned = _CLOSE_TAG.sub("<\\/user_input>", text)
    cleaned = _CONTROL_CHARS.sub("", cleaned)
    if len(cleaned) > MAX_USER_INPUT_CHARS:
        cleaned = cleaned[:MAX_USER_INPUT_CHARS] + "\n[...truncated]"
    return cleaned


def wrap_user_input(text: str | None) -> str:
    """Return the safe ``<user_input>...</user_input>`` block."""

    inner = sanitize_inline(text)
    return f"<user_input>\n{inner}\n</user_input>"


__all__ = ["wrap_user_input", "sanitize_inline", "MAX_USER_INPUT_CHARS"]
