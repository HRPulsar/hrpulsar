"""HRP-270: per-stage progress + cancel bookkeeping on ai_analysis_runs.

Adds:

* ``current_stage`` — slug from
  ``app.modules.recruitment.ai_analysis_stages.ALL_STAGES``. NULL while
  the run is still ``pending``.
* ``celery_task_id`` — captured at enqueue time so the cancel endpoint
  can ``celery.control.revoke(terminate=True)``. NULL for cache-hit
  full-mode runs (no task is dispatched).
* ``cancelled_at`` / ``cancelled_by_id`` — audit trail for the
  cancel-flow added in this revision.

The ``status`` column itself stays a plain ``String(20)``; adding
``"cancelled"`` to the accepted vocabulary needs no migration since
no CHECK constraint enforces the enum.

Revision ID: hrp270aiprogress
Revises: hrp275dropcacheidx
Create Date: 2026-06-18 12:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp270aiprogress"
down_revision: str | None = "hrp275dropcacheidx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_analysis_runs",
        sa.Column("current_stage", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "ai_analysis_runs",
        sa.Column("celery_task_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "ai_analysis_runs",
        sa.Column(
            "cancelled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "ai_analysis_runs",
        sa.Column(
            "cancelled_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # The HRP-204 revision shipped a CHECK constraint that pins the
    # ``status`` vocabulary to the four pre-HRP-270 values. Cancel
    # writes ``status='cancelled'`` and would 23514 in production
    # without dropping + recreating the constraint here. Tests pass
    # without this because pytest uses ``Base.metadata.create_all``
    # which does NOT carry CheckConstraint declarations.
    op.drop_constraint(
        "ck_ai_analysis_runs_status",
        "ai_analysis_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_analysis_runs_status",
        "ai_analysis_runs",
        "status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ai_analysis_runs_status",
        "ai_analysis_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_analysis_runs_status",
        "ai_analysis_runs",
        "status IN ('pending', 'processing', 'completed', 'failed')",
    )
    op.drop_column("ai_analysis_runs", "cancelled_by_id")
    op.drop_column("ai_analysis_runs", "cancelled_at")
    op.drop_column("ai_analysis_runs", "celery_task_id")
    op.drop_column("ai_analysis_runs", "current_stage")
