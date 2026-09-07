"""HRP-684: consent_requests.last_sent_at

Records when the consent magic link was last emailed, so the Resend
confirmation can name the real last attempt. Existing rows are
backfilled from ``created_at`` — that is when their link went out.

Revision ID: hrp684consentresend
Revises: pdp1itemspinned
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp684consentresend"
down_revision: str | Sequence[str] | None = "pdp1itemspinned"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "consent_requests",
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE consent_requests SET last_sent_at = created_at")


def downgrade() -> None:
    op.drop_column("consent_requests", "last_sent_at")
