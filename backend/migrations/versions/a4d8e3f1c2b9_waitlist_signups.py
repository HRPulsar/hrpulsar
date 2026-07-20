"""waitlist signups

Revision ID: a4d8e3f1c2b9
Revises: e6f7a8b9c0d1
Create Date: 2026-04-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4d8e3f1c2b9"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "waitlist_signups",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("interest", sa.String(length=50), nullable=True),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "ix_waitlist_signups_email",
        "waitlist_signups",
        ["email"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_waitlist_signups_email", table_name="waitlist_signups")
    op.drop_table("waitlist_signups")
