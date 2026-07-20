"""HRP-260 (M2): drop the waitlist table after sunset.

Replaced by ``signup_requests`` (HRP-259). The contacts have been
exported to a Resend audience by ``scripts/export_waitlist_to_resend.py``
before this migration is applied.

Revision ID: hrp260drop_waitlist
Revises: hrp259signup_requests
Create Date: 2026-06-16 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp260drop_waitlist"
down_revision: str | None = "hrp259signup_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``waitlist_signups`` may or may not exist on a brand-new install
    # because we never rebased the chain after dropping the create-table
    # migration of the same table — guard with ``IF EXISTS`` so a fresh
    # ``alembic upgrade heads`` against an empty database stays a no-op.
    op.execute("DROP TABLE IF EXISTS waitlist_signups CASCADE")


def downgrade() -> None:
    op.create_table(
        "waitlist_signups",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("interest", sa.String(50), nullable=True),
        sa.Column("role", sa.String(100), nullable=True),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column(
            "invited_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
