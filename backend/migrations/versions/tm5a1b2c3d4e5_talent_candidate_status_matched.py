"""HRP-214: rename TalentCandidate.status `nominated` → `matched`.

The status column used to carry one of ``nominated`` / ``appointed`` —
nominated covered both auto-pool picks and manual picks regardless of
whether the employee actually cleared the card's threshold. HRP-214
splits the non-appointed bucket into ``matched`` (employee qualifies)
and ``not_matched`` (manual pick that doesn't currently qualify), and
the Candidates table renders the new values directly.

Historic ``nominated`` rows were only ever created when the employee
qualified at the time of the recompute — convert them to ``matched``
so the next ``_auto_populate_candidates`` run (which now also handles
``not_matched`` promotions) stays accurate without a full backfill.
Also flip the column default from ``nominated`` to ``not_matched`` so
ad-hoc inserts (e.g. fixtures) get the safer default.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tm5a1b2c3d4e5"
down_revision: str | None = "hrp170redo01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE talent_candidates SET status = 'matched' WHERE status = 'nominated'"
    )
    op.alter_column(
        "talent_candidates",
        "status",
        server_default="not_matched",
        existing_type=sa.String(length=50),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Lossy by design: pre-HRP-214 only knew ``nominated``, so we collapse
    # both new buckets back. After a real production cycle this loses the
    # matched-vs-manual-pick distinction — only run in emergency rollback
    # and re-derive with ``_auto_populate_candidates`` afterwards.
    op.alter_column(
        "talent_candidates",
        "status",
        server_default="nominated",
        existing_type=sa.String(length=50),
        existing_nullable=False,
    )
    op.execute(
        "UPDATE talent_candidates SET status = 'nominated' "
        "WHERE status IN ('matched', 'not_matched')"
    )
