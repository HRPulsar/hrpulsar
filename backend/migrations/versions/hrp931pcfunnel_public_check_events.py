"""Funnel counters of the public check, HRP-931

Revision ID: hrp931pcfunnel
Revises: hrp926pcsave
Create Date: 2026-10-04 10:00:00.000000

* ``public_check_events`` - one counter per UTC day, funnel step and
  normalised ``utm_source`` (see ``PublicCheckEvent``): the client steps of
  the page beacons, and the row-counted steps of checks the purge or a
  visitor's "delete my data" removed. No visitor data.

Additive.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp931pcfunnel"
down_revision: str | Sequence[str] | None = "hrp926pcsave"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "public_check_events",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("event", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("day", "event", "source"),
    )


def downgrade() -> None:
    op.drop_table("public_check_events")
