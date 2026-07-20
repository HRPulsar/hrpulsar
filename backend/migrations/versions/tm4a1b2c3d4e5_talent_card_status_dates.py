"""HRP-92 REDO: split closed_at into completed_at / cancelled_at.

The original implementation reused a single ``closed_at`` column for both
the Complete and Cancel transitions, then prefixed the label with
"Closed:" in the UI. The REDO comment asks for assessment-style labels:

* terminal Completed → "Completed: yyyy-mm-dd"
* terminal Cancelled → "Cancelled: yyyy-mm-dd"

To do that the backend has to know which transition fired the
terminal-date stamp, so we add two dedicated columns. ``closed_at``
remains in the schema for backwards compatibility — any historic row
that was Cancelled via the old Complete transition keeps its date until
a tenant deliberately re-stamps it. The new transitions write the new
columns going forward.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tm4a1b2c3d4e5"
down_revision: str | None = "hrp163reap001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "talent_cards",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "talent_cards",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill: historic rows that are already terminal carried their
    # transition timestamp in ``closed_at``. Copy it into the new column
    # that matches the row's status so the list-and-detail labels render
    # correctly on day one.
    op.execute(
        "UPDATE talent_cards SET completed_at = closed_at "
        "WHERE status IN ('completed', 'closed') AND closed_at IS NOT NULL"
    )
    op.execute(
        "UPDATE talent_cards SET cancelled_at = closed_at "
        "WHERE status = 'cancelled' AND closed_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("talent_cards", "cancelled_at")
    op.drop_column("talent_cards", "completed_at")
