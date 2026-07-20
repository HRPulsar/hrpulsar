"""HRP-16: simplify PDP status model.

Drops three statuses from the PDP graph:

- ``on_approval`` → folds back to ``review`` so the plan is once again
  awaiting admin sign-off (which is now the same step as completion).
- ``approved``    → folds forward to ``done``; in the new graph admin
  closes the plan straight from ``review``.
- ``expired``     → folds to ``cancelled`` (terminal-to-terminal). The
  red overdue cue is now a pure UI affordance, not a server status.

There is no schema change — ``pdps.status`` stays a free-form ``VARCHAR``
column and the application keeps an in-memory enum. The downgrade is a
no-op because the original values are not reconstructible (the new graph
collapses three states into two existing ones).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "pdp2a2b3c4d5e6"
down_revision: str | None = "pdp1a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE pdps SET status = 'review' WHERE status = 'on_approval'")
    op.execute("UPDATE pdps SET status = 'done' WHERE status = 'approved'")
    op.execute("UPDATE pdps SET status = 'cancelled' WHERE status = 'expired'")
    # Apply the same mapping to ``pdp_versions.status`` so analytics or
    # history UIs filtering by status string don't trip over orphaned
    # values that the application no longer produces.
    op.execute(
        "UPDATE pdp_versions SET status = 'review' WHERE status = 'on_approval'"
    )
    op.execute("UPDATE pdp_versions SET status = 'done' WHERE status = 'approved'")
    op.execute(
        "UPDATE pdp_versions SET status = 'cancelled' WHERE status = 'expired'"
    )


def downgrade() -> None:
    # The mapping is lossy: review ← {review, on_approval}, done ← {approved, done},
    # cancelled ← {cancelled, expired}. Leaving the data as-is on downgrade
    # avoids guessing which rows belonged to which original state.
    pass
