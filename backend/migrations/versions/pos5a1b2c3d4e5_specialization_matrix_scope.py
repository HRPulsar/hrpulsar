"""Phase POS5: AI specialization matrix generation scope

Revision ID: pos5a1b2c3d4e5
Revises: pos1a1b2c3d4e5
Create Date: 2026-05-04 18:00:00.000000

Extends the `competence_generation_sessions.scope` CHECK constraint with
`specialization_matrix` so the existing AI generation infrastructure
(sessions, selection cascade, refine/regenerate, apply) can host the new
matrix-generation flow without a parallel table.

This migration is **enum-widening only** — every value the old constraint
accepted is still accepted, no data is rewritten, and any pending /
running / ready sessions on prod are unaffected. Downgrade rejects
`specialization_matrix` rows and will fail loudly if such rows exist.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "pos5a1b2c3d4e5"
down_revision: str | None = "pos1a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SCOPES = "('whole_base','group','competence_indicators')"
NEW_SCOPES = "('whole_base','group','competence_indicators','specialization_matrix')"


def upgrade() -> None:
    op.drop_constraint(
        "ck_compgen_scope",
        "competence_generation_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_compgen_scope",
        "competence_generation_sessions",
        f"scope IN {NEW_SCOPES}",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_compgen_scope",
        "competence_generation_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_compgen_scope",
        "competence_generation_sessions",
        f"scope IN {OLD_SCOPES}",
    )
