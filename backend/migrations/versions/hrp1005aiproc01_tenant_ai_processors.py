"""Per-tenant AI processor permissions (HRP-1005)

The platform admin adjusts the instance's AI processor list per tenant: a
delta on top of AI_PROCESSORS_DEFAULT, or a cut-off from platform keys.

Revision ID: hrp1005aiproc01
Revises: v2work11
Create Date: 2026-09-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp1005aiproc01"
down_revision: str | None = "v2work11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "ai_processor_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "ai_own_keys_only", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "ai_own_keys_only")
    op.drop_column("tenants", "ai_processor_overrides")
