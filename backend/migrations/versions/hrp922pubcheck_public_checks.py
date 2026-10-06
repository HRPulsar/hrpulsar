"""The anonymous process check, HRP-922

Revision ID: hrp922pubcheck
Revises: hrp984aiownerneeded
Create Date: 2026-10-02 20:00:00.000000

One table, ``public_checks``: a visitor's process check on the public
service (epic HRP-918) with its frozen result. It belongs to no tenant;
the sandbox company the analysis runs in is created by the application on
first use, not here. Additive.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp922pubcheck"
down_revision: str | Sequence[str] | None = "hrp984aiownerneeded"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "public_checks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "answers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("locale", sa.String(length=5), nullable=False),
        sa.Column("utm", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("container_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        sa.ForeignKeyConstraint(
            ["container_id"], ["work_containers.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["work_decomposition_sessions.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'ready', 'error')",
            name="ck_public_checks_status",
        ),
    )
    op.create_index("ix_public_checks_expires_at", "public_checks", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_public_checks_expires_at", table_name="public_checks")
    op.drop_table("public_checks")
