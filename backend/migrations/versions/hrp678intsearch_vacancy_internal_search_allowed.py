"""Per-vacancy internal-search switch (HRP-678)

Internal matching is part of the employment relationship, so the whole
workspace should not have to choose between "always" and "never". The
recruiter who owns a requisition gets one switch on it, and the talent
market bridge refuses to post while the switch is off.

``server_default true``: every vacancy that already exists stays
available to the internal search — the column records an opt-out, not a
new consent to collect.

Revision ID: hrp678intsearch
Revises: hrp667tmbridge
Create Date: 2026-09-01 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp678intsearch"
down_revision: str | None = "hrp667tmbridge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vacancies",
        sa.Column(
            "internal_search_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("vacancies", "internal_search_allowed")
