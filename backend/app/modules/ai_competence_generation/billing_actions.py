"""Billing-action key resolution for AI generation sessions.

Pure functions: scope → action key. Kept in its own module so the Celery
task can import them without pulling the full `service` graph (the cycle
risk that drove this split: tasks → service → models → tasks).
"""

from __future__ import annotations


def start_action_for_scope(scope: str) -> str:
    """Map session scope → start-action key.

    `specialization_matrix` has its own pricing category
    (`ai_specialization_matrix`); other scopes share the
    `ai_competence_generation` namespace.
    """
    if scope == "specialization_matrix":
        return "ai_specialization_matrix.start"
    return f"ai_competence_generation.start_{scope}"


def refine_action_for_scope(scope: str) -> str:
    """Map session scope → refine-action key."""
    if scope == "specialization_matrix":
        return "ai_specialization_matrix.refine"
    return "ai_competence_generation.refine"
