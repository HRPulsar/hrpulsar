"""HRP-457: record the platform-admin moderator on signup requests.

Moderation gets a second channel — the platform-admin UI — alongside the
Slack buttons. The Slack path keeps writing moderated_by_slack_user_id;
the admin path records the acting platform admin's user id here.

Revision ID: hrp457adminmod
Revises: c47fc6f13693
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "hrp457adminmod"
down_revision = "c47fc6f13693"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signup_requests",
        sa.Column(
            "moderated_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("signup_requests", "moderated_by_user_id")
