"""R4b.1: enforce one-active-scale-per-tenant invariant in the DB

The ``settings_service._deactivate_other_scales`` helper guarantees at
most one ``ScaleConfig`` row has ``is_active = TRUE`` per tenant, but a
concurrent create+update race could still slip two through. A partial
unique index closes the gap.

Revision ID: r4b2c3d4e5f6
Revises: r4b1b2c3d4e5
Create Date: 2026-05-11 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "r4b2c3d4e5f6"
down_revision: str | None = "r4b1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Cleanup: keep only the most recently updated active scale per tenant.
    # Anything older that is still flagged active gets demoted so the
    # partial unique index can be created without conflict.
    op.execute(
        """
        WITH ranked AS (
          SELECT id, tenant_id,
                 ROW_NUMBER() OVER (
                   PARTITION BY tenant_id
                   ORDER BY updated_at DESC, created_at DESC, id DESC
                 ) AS rn
          FROM scale_configs
          WHERE is_active
        )
        UPDATE scale_configs
        SET is_active = false
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    op.create_index(
        "ix_scale_configs_one_active_per_tenant",
        "scale_configs",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scale_configs_one_active_per_tenant", table_name="scale_configs"
    )
