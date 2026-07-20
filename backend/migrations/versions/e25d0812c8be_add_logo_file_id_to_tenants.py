"""add logo_file_id to tenants

Revision ID: e25d0812c8be
Revises: 00f8552f63fd
Create Date: 2026-04-20 11:13:25.201287
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e25d0812c8be"
down_revision: str | None = "00f8552f63fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("logo_file_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_tenants_logo_file_id",
        "tenants",
        "files",
        ["logo_file_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tenants_logo_file_id", "tenants", type_="foreignkey")
    op.drop_column("tenants", "logo_file_id")
