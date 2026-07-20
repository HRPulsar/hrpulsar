"""HRP-270: stage taxonomy for AI analysis pipeline.

Frontend renders all six stages — resume-only mode greys out the two
interview-only ones (``process_findings`` + ``citations``) with the
``skipped`` reason. The Celery task writes ``AIAnalysisRun.current_stage``
to one of these slugs at the start of each step so the UI's polling
refresh can highlight the active row.

The cancel endpoint uses ``COSTLY_STAGES`` to decide between a full
credit refund (cancelled before the first LLM call) and no refund.
"""

from __future__ import annotations

from typing import Literal

#: Canonical ordering — must match the visual order on the frontend.
ALL_STAGES: tuple[str, ...] = (
    "pre_check",
    "competences",
    "blind_spots",
    "process_findings",
    "citations",
    "verdict",
)

#: Human-readable labels surfaced by the frontend. Kept here so a
#: future locale module can override the dict without touching the
#: pipeline.
STAGE_LABELS: dict[str, str] = {
    "pre_check": "Pre-check",
    "competences": "Competences",
    "blind_spots": "Blind spots",
    "process_findings": "Process analysis",
    "citations": "Citations",
    "verdict": "Verdict",
}

#: Stages skipped when ``mode='resume_only'`` — there is no interview
#: transcript to anchor citations or surface process findings against.
RESUME_ONLY_SKIPPED: frozenset[str] = frozenset(
    {"process_findings", "citations"}
)

#: The first LLM-spending stage. Cancelling BEFORE this stage starts
#: refunds 100% of the credits; cancelling at or after it refunds 0%
#: (the LLM call has already been billed to the upstream provider).
FIRST_LLM_STAGE: Literal["competences"] = "competences"


def is_skipped(stage: str, mode: str) -> bool:
    """Return True iff ``stage`` is skipped for the given analysis ``mode``."""
    return mode == "resume_only" and stage in RESUME_ONLY_SKIPPED


def stages_for_mode(mode: str) -> list[dict[str, object]]:
    """Return the ordered stage descriptor list a frontend can render.

    Each entry has the slug, the human label, and a ``skipped`` flag
    so the UI can grey it out without re-deriving the mode rules.
    """
    return [
        {
            "key": s,
            "label": STAGE_LABELS[s],
            "skipped": is_skipped(s, mode),
        }
        for s in ALL_STAGES
    ]


def is_pre_llm(stage: str | None) -> bool:
    """Has the run not yet reached the first LLM call?

    Cancel logic: True → refund 100%, False → refund 0%. ``None`` and
    ``'pre_check'`` count as pre-LLM (no provider call dispatched yet).
    An unknown stage (deploy mismatch, manual SQL fix-up, future
    pipeline step) fails safe to ``False`` — we do not refund money
    against a stage label we cannot reason about.
    """
    if stage is None:
        return True
    if stage not in ALL_STAGES:
        return False
    if stage == FIRST_LLM_STAGE:
        return False
    # Pre-check fires before competences in the canonical order.
    return ALL_STAGES.index(stage) < ALL_STAGES.index(FIRST_LLM_STAGE)
