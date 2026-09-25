"""HRP-945: the company's last reclassification of a step -
``work_steps.classification_comment`` and ``work_steps.reclassified_at``.
Decision T13a of 2026-09-10 kept the comment in the prompt only; revised by
Maxim on 2026-09-24: it is the most informative signal of what the step
really is, and the statistics of edits must tell the model's second opinion
from the company's corrections.

Both nullable, no backfill: no earlier comment was stored anywhere.

Revision ID: v2work11
Revises: v2work10
Create Date: 2026-09-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v2work11"
down_revision: str | Sequence[str] | None = "v2work10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_steps", sa.Column("classification_comment", sa.Text(), nullable=True)
    )
    op.add_column(
        "work_steps",
        sa.Column("reclassified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_steps", "reclassified_at")
    op.drop_column("work_steps", "classification_comment")
