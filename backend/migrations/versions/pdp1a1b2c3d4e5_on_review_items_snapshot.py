"""HRP-24: PDP on-review items snapshot.

Add a JSON column on ``pdps`` that captures the items+materials state at the
moment the plan enters status ``review``. While the plan stays in ``review``
the assigned employee sees the snapshot rather than live items (so admin edits
made during review are hidden until the plan is returned). The column is
cleared when the plan transitions out of ``review``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "pdp1a1b2c3d4e5"
down_revision: str | None = "asr1a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pdps",
        sa.Column(
            "on_review_items_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("pdps", "on_review_items_snapshot")
