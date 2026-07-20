"""Phase INV1: required Name on invitations

Revision ID: inv1a1b2c3d4e5
Revises: pos5a1b2c3d4e5
Create Date: 2026-05-05 12:00:00.000000

Adds `invitations.name VARCHAR(200) NOT NULL`. Existing rows are
backfilled with the local part of the email so the NOT NULL constraint
holds without forcing operators to populate a recipient name for
historical pending invitations.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "inv1a1b2c3d4e5"
down_revision: str | None = "pos5a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invitations",
        sa.Column("name", sa.String(length=200), nullable=True),
    )
    op.execute(
        "UPDATE invitations SET name = split_part(email, '@', 1) " "WHERE name IS NULL"
    )
    op.alter_column("invitations", "name", nullable=False)


def downgrade() -> None:
    op.drop_column("invitations", "name")
