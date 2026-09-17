"""HRP-775: the phase of a decomposition run (``splitting`` /
``classifying``) - a breakdown is two LLM calls since ``v2work.v5``, and
the banner names the one in flight.

Sixth revision of the HRPulsar 2.0 chain (epic HRP-746), on top of the
merge with main. Additive, nullable, no backfill.
Downgrade order: ``v2work03 -> v2merge01 -> v2work02 -> ...``.

Revision ID: v2work03
Revises: v2merge01
Create Date: 2026-09-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v2work03"
down_revision: str | Sequence[str] | None = "v2merge01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_decomposition_sessions",
        sa.Column("phase", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_workdecomp_phase",
        "work_decomposition_sessions",
        "phase IS NULL OR phase IN ('splitting', 'classifying')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_workdecomp_phase", "work_decomposition_sessions", type_="check"
    )
    op.drop_column("work_decomposition_sessions", "phase")
