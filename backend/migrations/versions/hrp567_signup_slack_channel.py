"""Store the Slack channel id of the signup moderation card (HRP-567).

``chat.update`` requires a channel *id* (a ``#name`` reference answers
``channel_not_found``), so ``slack_message_ts`` alone cannot finalise
the card when the decision happens in the platform-admin UI — the Bolt
path gets the id from its action payload, the admin path has only the
row. Nullable: rows created before this column simply keep the
threaded-reply fallback.

Revision ID: hrp567slackchan
Revises: hrp515brandtpl
Create Date: 2026-08-12 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp567slackchan"
down_revision: str | None = "hrp515brandtpl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "signup_requests",
        sa.Column("slack_channel_id", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("signup_requests", "slack_channel_id")
