"""gf4_external_reviewers

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-17 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # GF4: External Reviewers table
    op.create_table(
        "external_reviewers",
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["assessments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index(
        op.f("ix_external_reviewers_token"),
        "external_reviewers",
        ["token"],
        unique=True,
    )
    op.create_index(
        op.f("ix_external_reviewers_assessment_id"),
        "external_reviewers",
        ["assessment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_reviewers_tenant_id"),
        "external_reviewers",
        ["tenant_id"],
        unique=False,
    )

    # Make assessment_participants.user_id nullable + add external_reviewer_id FK
    op.alter_column("assessment_participants", "user_id", nullable=True)
    op.add_column(
        "assessment_participants",
        sa.Column("external_reviewer_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_participant_external_reviewer",
        "assessment_participants",
        "external_reviewers",
        ["external_reviewer_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_participant_external_reviewer",
        "assessment_participants",
        type_="foreignkey",
    )
    op.drop_column("assessment_participants", "external_reviewer_id")
    op.alter_column("assessment_participants", "user_id", nullable=False)
    op.drop_table("external_reviewers")
