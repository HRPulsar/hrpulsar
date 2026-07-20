"""Drop dead cost_credits column from competence_generation_sessions

Billing/credits are enterprise-only: core models must not carry credit
semantics. ``cost_credits`` was never written or read by anything and is not
surfaced in the frontend, so the enterprise-only column is removed from the
community schema.

Revision ID: dropaigencostcredits
Revises: 501b10d2b6f1
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "dropaigencostcredits"
down_revision: str | None = "501b10d2b6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("competence_generation_sessions", "cost_credits")


def downgrade() -> None:
    op.add_column(
        "competence_generation_sessions",
        sa.Column("cost_credits", sa.Integer(), nullable=True),
    )
