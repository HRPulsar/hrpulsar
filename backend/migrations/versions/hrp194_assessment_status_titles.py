"""Rename Assessment status titles to use sentence case.

Revision ID: hrp194stitles
Revises: hrp170redo01
Create Date: 2026-06-04 10:00:00.000000

HRP-194: rename ``In Progress`` → ``In progress`` and ``On Review`` →
``On review`` so the badges/copy match the rest of the UI (Development
already uses ``In progress`` / ``Under review``). Codes stay the same.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "hrp194stitles"
down_revision: str | None = "hrp170redo01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("UPDATE assessment_statuses SET title = 'In progress' WHERE code = 'in_progress'")
    )
    bind.execute(
        text("UPDATE assessment_statuses SET title = 'On review' WHERE code = 'on_review'")
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("UPDATE assessment_statuses SET title = 'In Progress' WHERE code = 'in_progress'")
    )
    bind.execute(
        text("UPDATE assessment_statuses SET title = 'On Review' WHERE code = 'on_review'")
    )
