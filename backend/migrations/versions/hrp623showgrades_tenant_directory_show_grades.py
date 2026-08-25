"""Tenant flag: show grades in the employee directory (HRP-623)

The directory hands rank-and-file employees a trimmed card. Grade is the
one field on it that some tenants treat as public and others as
compensation-adjacent, so it is opt-in per tenant rather than a product
decision. Plain column, not JSONB: it is read on every directory render
and has to be visible in the schema and the admin form.

Revision ID: hrp623showgrades
Revises: hrp619baseline
Create Date: 2026-08-22 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp623showgrades"
down_revision: str | None = "hrp619baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "directory_show_grades",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "directory_show_grades")
