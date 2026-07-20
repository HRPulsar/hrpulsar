"""HRP-285: per-tenant active/inactive override for origin dictionary items.

Adds ``dictionary_item_tenant_overrides`` so a tenant can deactivate or
reactivate a System (origin) dictionary entry without mutating the
shared origin row. Absence of an override row means the tenant inherits
the origin ``is_active``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp285dictoverride"
down_revision: str | None = "hrp305demoguard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dictionary_item_tenant_overrides",
        sa.Column(
            "item_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dictionary_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.PrimaryKeyConstraint(
            "item_id", "tenant_id", name="pk_dict_item_tenant_override"
        ),
    )
    op.create_index(
        "ix_dict_item_tenant_override_tenant_id",
        "dictionary_item_tenant_overrides",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dict_item_tenant_override_tenant_id",
        table_name="dictionary_item_tenant_overrides",
    )
    op.drop_table("dictionary_item_tenant_overrides")
