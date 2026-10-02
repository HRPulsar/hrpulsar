"""HRP-820: the tenant's section x role access matrix - deviations from the
defaults only, plus a change log. Nothing is seeded: empty tables are
today's behaviour.

Revision ID: v2sec01
Revises: v2idx01
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v2sec01"
down_revision: str | Sequence[str] | None = "v2idx01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SETTINGS = "tenant_section_settings"
ACCESS = "tenant_section_access"
LOG = "tenant_section_access_log"


def _uuid(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        SETTINGS,
        _uuid("tenant_id"),
        sa.Column("section", sa.String(length=32), nullable=False),
        sa.Column("hidden", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "section"),
    )
    op.create_table(
        ACCESS,
        _uuid("tenant_id"),
        sa.Column("section", sa.String(length=32), nullable=False),
        sa.Column("role_code", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "section", "role_code"),
    )
    op.create_table(
        LOG,
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        _uuid("tenant_id"),
        _uuid("changed_by_id", nullable=True),
        sa.Column("diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(f"ix_{LOG}_tenant_id", LOG, ["tenant_id"])


def downgrade() -> None:
    op.drop_index(f"ix_{LOG}_tenant_id", table_name=LOG)
    op.drop_table(LOG)
    op.drop_table(ACCESS)
    op.drop_table(SETTINGS)
