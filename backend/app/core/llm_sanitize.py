"""HRP-163: defence-in-depth sanitiser for user-supplied LLM prompts.

The tenant's own AI generations are low-risk — there is no other tenant
on the other side to influence — but we still strip the obvious prompt-
injection markers so a careless paste of a hostile string can't reshape
our system prompt. Currently applied to user-typed refinement/note
fields in competence material generation and the AI competence-
generation worker (including the matrix wizard's six free-form
fields); other LLM entry points (`app.modules.ai.service`) are
already constrained by short max-lengths and remain a follow-up.

The regex set is intentionally narrow:

* ``</?\\s*(system|assistant|human|user)\\s*>`` — generic role-tag wrappers
  used by Claude / OpenAI / others; chat templates render these as
  control tokens, so we don't want them appearing inside user content.
* ``ignore (all )?previous`` / ``disregard (all )?previous`` — the most
  common opening phrase for jailbreak payloads. We drop the trigger; the
  remainder of the user message stays so the LLM can still see the
  legitimate refinement attempt.

After stripping, the result is truncated to ``MAX_REFINEMENT_CHARS`` so a
copy-paste of a giant doc can't push token cost wildly off-target.
"""

from __future__ import annotations

import re

MAX_REFINEMENT_CHARS = 4000

_ROLE_TAG_RE = re.compile(
    r"</?\s*(system|assistant|human|user)\s*>",
    re.IGNORECASE,
)
_IGNORE_PREVIOUS_RE = re.compile(
    r"(?:ignore|disregard|forget)\s+(?:all\s+|the\s+|any\s+)?previous"
    r"(?:\s+instructions?)?",
    re.IGNORECASE,
)


def sanitize_user_refinement(text: str | None) -> str | None:
    """Strip role-tag injections + truncate. Returns ``None`` on empty.

    ``text`` is whatever the user typed (or ``None``). The function:

    1. Returns ``None`` for ``None`` / blank-after-strip inputs.
    2. Removes any HTML-like role tags (``<system>``, ``</user>`` …).
    3. Neutralises ``"ignore previous instructions"``-style triggers.
    4. Collapses the runs of whitespace this leaves behind.
    5. Truncates to ``MAX_REFINEMENT_CHARS``.

    The function is intentionally idempotent — calling it twice yields
    the same result as calling it once.
    """
    if text is None:
        return None
    stripped = text.strip()
    if not stripped:
        return None

    cleaned = _ROLE_TAG_RE.sub(" ", stripped)
    cleaned = _IGNORE_PREVIOUS_RE.sub(" ", cleaned)
    # Collapse the gaps the substitutions leave behind so the prompt
    # doesn't end up with weird "  " runs that change tokenisation.
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_REFINEMENT_CHARS:
        cleaned = cleaned[:MAX_REFINEMENT_CHARS].rstrip()
    return cleaned
