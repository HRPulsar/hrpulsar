"""HRP-185: Calibrate Totals in Detailed results.

Adds:
* ``assessments.calibration_in_progress`` — locks participant submissions
  while a reviewer is editing per-indicator Totals.
* ``assessment_calibrated_totals`` — per-indicator answer-option override
  pinned by the reviewer; wiped on Cancel calibration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp185calibrate01"
down_revision: str | None = "hrp170recompute01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assessments",
        sa.Column(
            "calibration_in_progress",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "assessment_calibrated_totals",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "indicator_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("indicators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "answer_option_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("answer_options.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_assessment_calibrated_totals_assessment_id",
        "assessment_calibrated_totals",
        ["assessment_id"],
    )
    op.create_index(
        "uq_assessment_calibrated_indicator",
        "assessment_calibrated_totals",
        ["assessment_id", "indicator_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_assessment_calibrated_indicator",
        table_name="assessment_calibrated_totals",
    )
    op.drop_index(
        "ix_assessment_calibrated_totals_assessment_id",
        table_name="assessment_calibrated_totals",
    )
    op.drop_table("assessment_calibrated_totals")
    op.drop_column("assessments", "calibration_in_progress")
