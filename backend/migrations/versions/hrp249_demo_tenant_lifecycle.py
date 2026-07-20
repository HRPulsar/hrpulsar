"""HRP-249: tenant lifecycle fields for the public demo sandbox.

Adds three nullable columns on ``tenants``:

- ``is_demo`` — flag marking a tenant as a throw-away demo sandbox.
- ``expires_at`` — hard TTL; once exceeded the cleanup beat task
  cascade-deletes the tenant.
- ``last_active_at`` — sliding inactivity timestamp; combined with
  ``DEMO_INACTIVITY_TTL_SECONDS`` it lets idle sessions die early so
  the concurrent-session cap stays honest.

A partial index on ``(expires_at)`` where ``is_demo = true`` keeps the
cleanup scan cheap without bloating writes on the much larger pool of
regular tenants.

Revision ID: hrp249demo
Revises: hrp246kpi
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp249demo"
down_revision: str | Sequence[str] | None = "hrp246kpi"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_tenants_demo_expires_at",
        "tenants",
        ["expires_at"],
        postgresql_where=sa.text("is_demo = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_tenants_demo_expires_at", table_name="tenants")
    op.drop_column("tenants", "last_active_at")
    op.drop_column("tenants", "expires_at")
    op.drop_column("tenants", "is_demo")
