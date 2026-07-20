"""HRP-242: add talent_cards.last_matched_at.

Stamps when the Candidates auto-pool was last recomputed for the card so
the UI can render "today / yesterday / Month dd" in the Candidates block
header. Updated on the auto-populate path, on Change-candidates picker
mutations, and on the explicit refresh button this ticket introduces.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tm6hrp242"
down_revision: str | None = "hrp181redo04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "talent_cards",
        sa.Column("last_matched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("talent_cards", "last_matched_at")
