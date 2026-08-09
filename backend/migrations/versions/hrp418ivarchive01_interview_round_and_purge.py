"""HRP-386/418: interview round link, purge stamp, archived AI-score flag.

* ``interviews.round_id`` — optional link to the Manager-assessment round
  the interview belongs to (Schedule modal "Round" field). Cleared on
  archive.
* ``interviews.purged_at`` — set by the retention sweeper once the 90-day
  restore window elapsed and the recording was dropped from S3.
* ``ai_assessments.source_archived`` — the interview the scores came from
  has been archived; the rows stay for the historical record.

Revision ID: hrp418ivarchive01
Revises: 933b005f65e8
Create Date: 2026-08-07 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp418ivarchive01"
down_revision: str | None = "933b005f65e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interviews",
        sa.Column("round_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_interviews_round_id", "interviews", ["round_id"], unique=False)
    op.create_foreign_key(
        "fk_interviews_round_id",
        "interviews",
        "recruitment_assessment_rounds",
        ["round_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "interviews",
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ai_assessments",
        sa.Column(
            "source_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_assessments", "source_archived")
    op.drop_column("interviews", "purged_at")
    op.drop_constraint("fk_interviews_round_id", "interviews", type_="foreignkey")
    op.drop_index("ix_interviews_round_id", table_name="interviews")
    op.drop_column("interviews", "round_id")
