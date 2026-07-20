"""HRP-358: assessment_invites.consent_accepted_at.

The invite status model now flips ``pending`` → ``opened`` on the first
link visit (not on consent accept), so the consent acknowledgment needs
its own persistent timestamp — the public page keeps showing the consent
gate until it is set. Backfill from ``opened_at``: every invite opened
before this migration got there through the consent button.

Revision ID: hrp358invconsent
Revises: hrp360hiringmgr
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from alembic import op

revision: str = "hrp358invconsent"
down_revision: str | None = "hrp360hiringmgr"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assessment_invites",
        sa.Column("consent_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE assessment_invites "
        "SET consent_accepted_at = opened_at "
        "WHERE opened_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("assessment_invites", "consent_accepted_at")
