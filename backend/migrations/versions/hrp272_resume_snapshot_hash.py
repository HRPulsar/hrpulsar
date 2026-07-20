"""HRP-272: resume_snapshot_hash on ai_analysis_runs.

A 64-char SHA256 over the candidate's parsed_resume JSON at the time the
run was enqueued. Used by ``serialize_run_for_read`` to flag an active
resume-only run as outdated when the candidate has uploaded a fresh
resume since — the UI shows a "Resume updated — re-analyze" banner that
re-runs the existing resume-only billable entry point.

Nullable so legacy rows created before this revision keep working: a
NULL stored hash means we cannot decide outdated-ness and the banner
stays hidden.

Revision ID: hrp272resumehash
Revises: hrp270aiprogress
Create Date: 2026-06-18 13:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp272resumehash"
down_revision: str | None = "hrp270aiprogress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_analysis_runs",
        sa.Column("resume_snapshot_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_analysis_runs", "resume_snapshot_hash")
