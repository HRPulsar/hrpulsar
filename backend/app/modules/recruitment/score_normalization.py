"""HRP-274 — rebase the canonical raw AI score onto the tenant's scale.

The canonical raw AI score scale is ``0..1``. Both analysis prompts
(interview/full and resume-only) explicitly instruct the LLM to emit
every numeric competence score on a ``0..1`` scale, and parsed values
are clamped to that window at ingestion (``clamp_unit_score`` backs the
schema validators in ``prompts_interview``). ``cv.ai_score`` therefore
always stores the raw ``0..1`` mean.

``compute_normalized_ai_score`` rebases that raw value onto the tenant's
active ``ScaleConfig.max_value`` so it can sit next to ``manager_score``
(which lives on the tenant assessment scale) and feed
``compute_score_divergence``:

* Tenant with scale ``1..10`` and ``raw=0.5`` → ``5.0``
* Tenant with scale ``0..5`` and ``raw=0.8`` → ``4.0``

When the tenant has no active ScaleConfig — or a misconfigured one with
``max_value <= 0`` — the helper falls back to the identity mapping
(scale max ``1.0``), so the normalized column is never inert: it simply
equals the raw ``0..1`` value.
"""

from __future__ import annotations


def clamp_unit_score(raw_score: float | None) -> float | None:
    """Clamp a raw LLM score to the canonical ``[0..1]`` window.

    The prompts pin the ``0..1`` contract, but an LLM occasionally
    overshoots (``1.2``) or emits a stray value on another scale. Clamp
    instead of raising so one bad number never fails a whole analysis
    run. ``None`` (competence not assessed) propagates through.
    """
    if raw_score is None:
        return None
    return min(1.0, max(0.0, float(raw_score)))


def compute_normalized_ai_score(
    raw_score: float | None,
    scale_max: float | None,
) -> float | None:
    """Return the canonical ``0..1`` ``raw_score`` rebased onto the
    tenant scale (``raw × scale_max``).

    ``None`` raw propagates through unchanged so the caller can store a
    NULL column when there is no AI opinion yet. A missing scale
    (``None`` — the tenant never created an active ScaleConfig) or a
    misconfigured one (``scale_max <= 0``) falls back to the identity
    scale max ``1.0``: the normalized value then equals the raw score,
    so the raw/normalized toggle is never inert. The raw input is
    clamped to ``[0..1]`` first so a stray out-of-range LLM answer never
    poisons the candidate row.
    """
    if raw_score is None:
        return None
    if scale_max is None or scale_max <= 0:
        scale_max = 1.0
    clamped = min(1.0, max(0.0, float(raw_score)))
    return clamped * float(scale_max)
