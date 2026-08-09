"""HRP-521: drop report templates.

The Generate-report dialog now owns the sheet selection, so the
per-tenant ``report_templates`` surface (UI page, CRUD endpoints and
table) is removed. ``consolidated_reports.template_id`` was the only
referencing column and goes with it.

Revision ID: hrp521droprepttpl01
Revises: hrp518deproofread01
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "hrp521droprepttpl01"
down_revision: str | Sequence[str] | None = "hrp518deproofread01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("consolidated_reports", "template_id")
    op.drop_table("report_templates")


def downgrade() -> None:
    op.create_table(
        "report_templates",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("template_data", JSONB, nullable=False),
        sa.Column("sections", JSONB, nullable=True),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "consolidated_reports",
        sa.Column(
            "template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("report_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
