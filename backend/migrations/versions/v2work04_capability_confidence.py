"""HRP-776: evidence and confidence per capability of a step - the
model's confidence and the fragment of the description it quotes, and
when the company confirmed the code (decision 2026-09-10 and its
clarification: the outcome is recorded on the step-to-code link, the
original proposal stays in the session payload).

Seventh revision of the HRPulsar 2.0 chain (epic HRP-746). Additive,
nullable, no backfill: links written before this revision carry no
confidence and are never tentative on that account.
Downgrade order: ``v2work04 -> v2work03 -> v2merge01 -> ...``.

Revision ID: v2work04
Revises: v2work03
Create Date: 2026-09-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v2work04"
down_revision: str | Sequence[str] | None = "v2work03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_step_primitives", sa.Column("confidence", sa.Float(), nullable=True)
    )
    op.add_column("work_step_primitives", sa.Column("quote", sa.Text(), nullable=True))
    op.add_column(
        "work_step_primitives",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_work_step_prim_confidence",
        "work_step_primitives",
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_work_step_prim_confidence", "work_step_primitives", type_="check"
    )
    op.drop_column("work_step_primitives", "confirmed_at")
    op.drop_column("work_step_primitives", "quote")
    op.drop_column("work_step_primitives", "confidence")
