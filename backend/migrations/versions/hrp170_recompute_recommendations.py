"""HRP-170: invalidate Recommended grade cache for legacy assessments.

The chart formula and visibility rules changed:

* The chart is now built for ``target_position`` AND ``current_positions``
  assessments (previously only ``target_position``).
* The match % per grade is computed as the mean of competence match %
  values; each competence's match % is the mean of skill-level percents
  from Basic up to the grade's required level (the old formula averaged
  per-indicator scores directly).
* The chart unlocks at On Review (was Done only) and stays available for
  cancellations that crossed On Review.

This migration drops the cached payload so the old numbers never show up
to operators. The actual recompute is driven by
``scripts/recompute_recommendations.py`` — running it during deploy
backfills every eligible assessment in one pass. The script is
idempotent; subsequent status transitions also refresh the cache, so
even an unattended deploy converges as users interact with the data.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "hrp170recompute01"
down_revision: str | None = "tm4a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        text(
            "UPDATE assessments SET recommendation_payload = NULL, "
            "recommended_grade_id = NULL"
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            "UPDATE assessments SET recommendation_payload = NULL, "
            "recommended_grade_id = NULL"
        )
    )
