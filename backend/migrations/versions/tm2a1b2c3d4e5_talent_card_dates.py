"""HRP-92: Talent Market start/end dates.

Adds the two date columns the Talent Card create/edit form now exposes:

* ``start_date`` — required date the card is "active from".
* ``end_date`` — optional end date; must be >= start_date when set.

`start_date` is non-null. Existing rows are backfilled with the row's
``created_at::date`` so the constraint can be applied without breaking
historic data.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tm2a1b2c3d4e5"
down_revision: str | None = "tm1a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "talent_cards",
        sa.Column("start_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "talent_cards",
        sa.Column("end_date", sa.Date(), nullable=True),
    )
    op.execute(
        "UPDATE talent_cards SET start_date = created_at::date WHERE start_date IS NULL"
    )
    op.alter_column("talent_cards", "start_date", nullable=False)


def downgrade() -> None:
    op.drop_column("talent_cards", "end_date")
    op.drop_column("talent_cards", "start_date")
