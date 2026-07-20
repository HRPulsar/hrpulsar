"""R2b: human_assessments — support invited evaluators

Revision ID: r2b1c2d3e4f5
Revises: r2a1b2c3d4e5
Create Date: 2026-05-07 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r2b1c2d3e4f5"
down_revision: str | None = "r2a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "human_assessments",
        "evaluator_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.add_column(
        "human_assessments",
        sa.Column("evaluator_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "human_assessments",
        sa.Column(
            "invite_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_human_assessments_invite_id",
        "human_assessments",
        "assessment_invites",
        ["invite_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_human_assessments_invite_id",
        "human_assessments",
        ["invite_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_human_assessments_invite_id", table_name="human_assessments")
    op.drop_constraint(
        "fk_human_assessments_invite_id", "human_assessments", type_="foreignkey"
    )
    op.drop_column("human_assessments", "invite_id")
    op.drop_column("human_assessments", "evaluator_name")
    op.alter_column(
        "human_assessments",
        "evaluator_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
