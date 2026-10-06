"""Drop the permissions tables, the HRP-832 contract step

Revision ID: hrp973droperms
Revises: hrp740genat01
Create Date: 2026-10-02 12:00:00.000000

HRP-973: HRP-832 removed the ``Permission`` model and the ``Role.permissions``
relationship in 2.2.0 but left ``permissions`` and ``role_permissions`` in
the database: the relationship was ``selectin``, so the previous release's
containers kept loading the tables while the deploy migrated ahead of the
swap. 2.2.0 runs everywhere now and nothing reads them, so they go.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp973droperms"
down_revision: str | Sequence[str] | None = "hrp740genat01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("role_permissions")
    op.drop_table("permissions")


def downgrade() -> None:
    # Back empty, as ab6347d21c01 created them: nothing read the rows.
    op.create_table(
        "permissions",
        sa.Column("codename", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
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
        sa.UniqueConstraint("codename"),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.UUID(), nullable=False),
        sa.Column("permission_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["permissions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )
