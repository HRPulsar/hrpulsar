"""Add criteria_type to assessments and groups, skill_level_id to assessment_competences

Revision ID: c9d3f1b2a4e5
Revises: b8c4d2f1a9e3
Create Date: 2026-04-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d3f1b2a4e5"
down_revision: str | None = "b8c4d2f1a9e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assessments",
        sa.Column("criteria_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "assessment_competences",
        sa.Column(
            "skill_level_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill_levels.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.add_column(
        "assessment_groups",
        sa.Column("criteria_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "assessment_groups",
        sa.Column(
            "specialization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dictionary_items.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "assessment_groups",
        sa.Column(
            "grade_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dictionary_items.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("assessment_groups", "grade_id")
    op.drop_column("assessment_groups", "specialization_id")
    op.drop_column("assessment_groups", "criteria_type")
    op.drop_column("assessment_competences", "skill_level_id")
    op.drop_column("assessments", "criteria_type")
