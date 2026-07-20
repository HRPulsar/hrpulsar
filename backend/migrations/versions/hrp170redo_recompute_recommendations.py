"""HRP-170 redo: re-invalidate Recommended grade cache after grade filter.

The recommendation engine learned to drop grades whose required skill
levels sit above what the assessment actually answered (e.g. a Middle
assessment used to render a Senior bar fed only by Basic + Intermediate
data). Legacy cached payloads still carry those phantom grades, so the
chart looks wrong until the engine recomputes — drop the cache here and
let ``scripts/recompute_recommendations.py`` backfill in one pass during
deploy. The script stays idempotent; subsequent status transitions also
refresh the cache, so an unattended deploy still converges.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "hrp170redo01"
down_revision: str | None = "8e638d035083"
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
    # Symmetric cache-bust by design: downgrade just clears the cache
    # again so the previous (pre-redo) engine re-populates the payload
    # on its next status transition. Not a copy-paste error.
    op.execute(
        text(
            "UPDATE assessments SET recommendation_payload = NULL, "
            "recommended_grade_id = NULL"
        )
    )
