"""R2: Add purpose/priority/is_manual to candidate_questions + assessment_invites evaluator_name

Revision ID: r2a1b2c3d4e5
Revises: r1a2b3c4d5e6
Create Date: 2026-04-24 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r2a1b2c3d4e5"
down_revision: str | None = "r1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # candidate_questions: add purpose, priority, is_manual
    op.add_column(
        "candidate_questions",
        sa.Column(
            "purpose",
            sa.String(50),
            nullable=False,
            server_default="clarification",
        ),
    )
    op.add_column(
        "candidate_questions",
        sa.Column(
            "priority",
            sa.String(50),
            nullable=False,
            server_default="should",
        ),
    )
    op.add_column(
        "candidate_questions",
        sa.Column(
            "is_manual",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    # assessment_invites: add evaluator_name for display
    op.add_column(
        "assessment_invites",
        sa.Column("evaluator_name", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assessment_invites", "evaluator_name")
    op.drop_column("candidate_questions", "is_manual")
    op.drop_column("candidate_questions", "priority")
    op.drop_column("candidate_questions", "purpose")
