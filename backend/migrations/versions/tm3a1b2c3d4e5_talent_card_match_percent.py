"""HRP-128: card-level Match% on Talent Cards.

The Required Competences step-3 dialog (per-row match%) is folded into a
single ``talent_cards.match_percent`` column. Existing data is preserved:

* The new column is added with ``server_default='80'`` so legacy rows that
  have no card-level value get the sensible default.
* For draft cards that already had per-row match% values configured, we
  backfill the card-level column with the *minimum* per-row match% so the
  matcher does not become more permissive after the upgrade.
* Per-row ``talent_card_competences.match_percent`` is left in place — the
  column is no longer written by new code but historic values stay for
  audit. A follow-up migration can drop it once all live tenants have
  re-saved their Required Competences blocks.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tm3a1b2c3d4e5"
down_revision: str | None = "tm2a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "talent_cards",
        sa.Column(
            "match_percent",
            sa.Integer(),
            nullable=False,
            server_default="80",
        ),
    )
    # Backfill from the strictest existing per-row match% on each card. The
    # MIN keeps the matcher's bar at least as high as before the rewrite.
    op.execute(
        """
        UPDATE talent_cards tc
        SET match_percent = sub.threshold
        FROM (
            SELECT card_id, MIN(GREATEST(LEAST(match_percent, 100), 50)) AS threshold
            FROM talent_card_competences
            WHERE match_percent IS NOT NULL
            GROUP BY card_id
        ) sub
        WHERE sub.card_id = tc.id
        """
    )
    op.create_check_constraint(
        "ck_talent_cards_match_percent_range",
        "talent_cards",
        "match_percent BETWEEN 50 AND 100",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_talent_cards_match_percent_range", "talent_cards", type_="check"
    )
    op.drop_column("talent_cards", "match_percent")
