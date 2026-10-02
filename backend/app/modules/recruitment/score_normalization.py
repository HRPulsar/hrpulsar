"""HRP-274 — rebase the canonical raw AI score onto the tenant's scale.

The canonical raw AI score scale is ``0..1``. Both analysis prompts
(interview/full and resume-only) explicitly instruct the LLM to emit
every numeric competence score on a ``0..1`` scale, and parsed values
are clamped to that window at ingestion (``clamp_unit_score`` backs the
schema validators in ``prompts_interview``). ``cv.ai_score`` therefore
always stores the raw ``0..1`` mean.

``compute_normalized_ai_score`` rebases that raw value onto the tenant's
active ``ScaleConfig.max_value`` so it can sit next to ``manager_score``
(which lives on the tenant assessment scale):

* Tenant with scale ``1..10`` and ``raw=0.5`` → ``5.0``
* Tenant with scale ``0..5`` and ``raw=0.8`` → ``4.0``

When the tenant has no active ScaleConfig — or a misconfigured one with
``max_value <= 0`` — the helper falls back to the identity mapping
(scale max ``1.0``), so the normalized column is never inert: it simply
equals the raw ``0..1`` value.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any


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


# ---------------------------------------------------------------------------
# HRP-774 — one "% of scale" for a manager's level
# ---------------------------------------------------------------------------


def weighted_levels(levels: Iterable[Any]) -> list[tuple[float, float]]:
    """``(value, weight)`` pairs from scale-level dicts.

    Accepts the vacancy's frozen ``assessment_scale_snapshot["levels"]``
    and the serialized ``AssessmentScale`` levels alike — both carry
    ``value`` and ``weight``. Entries missing either are skipped.
    """
    return [
        (float(lvl["value"]), float(lvl["weight"]))
        for lvl in levels
        if isinstance(lvl, dict)
        and lvl.get("value") is not None
        and lvl.get("weight") is not None
    ]


def scale_percent(
    level: float | None, levels: Sequence[tuple[float, float]]
) -> float | None:
    """Canonical "% of scale" for a level on an assessment scale (HRP-774).

    A scale level is worth its ``weight`` — the 0..100 figure the scale
    builder asks for next to every level (``AssessmentScaleLevel.weight``;
    "Standard 1-4" ships 0 / 33 / 66 / 100). A fractional level, which is
    what every average is, sits proportionally between its two neighbours:
    3.5 on that scale is 83, not the nearest level's 66. Levels outside the
    scale are clamped to the end weights. A scale that has no weights of
    its own (the legacy tenant ``ScaleConfig``) is described as the two
    points ``(min, 0), (max, 100)``, which makes it linear from floor to
    ceiling.

    This is the *only* level → percent conversion in the product: the
    saved ``candidate_vacancies.manager_score_weight``, the round header's
    "% of scale", the assessment matrix cells and per-candidate % match,
    the canvas Percent toggle and the canvas export all read it. Level /
    max — 3 on 1-4 as 75 % — ignored the weights the tenant configured and
    disagreed with the round header for the very same score.

    Returns ``None`` for a missing level or an empty scale; the value is
    not rounded, callers round for display.
    """
    if level is None or not levels:
        return None
    points = sorted((float(v), float(w)) for v, w in levels)
    x = float(level)
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (v0, w0), (v1, w1) in zip(points, points[1:], strict=False):
        if v0 <= x <= v1:
            return w1 if v1 == v0 else w0 + (w1 - w0) * (x - v0) / (v1 - v0)
    return None  # pragma: no cover — the scan above always brackets ``x``
