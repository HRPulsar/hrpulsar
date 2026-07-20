"""HRP-259 (M1): signup_requests for moderated onboarding.

Replaces the public waitlist as the entry point on the landing. A
visitor fills out a four-field form (email, name, company, role); we
email a verification link; once they click it, the row flips to
``pending_moderation`` and a Slack message asks any team member to
approve or reject. On approve we atomically create the real Tenant +
User pair and email a one-time magic-login link.

Revision ID: hrp259signup_requests
Revises: hrp265matrix
Create Date: 2026-06-16 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp259signup_requests"
down_revision: str | None = "hrp265matrix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_STATUSES = (
    "pending_email_verify",
    "pending_moderation",
    "approved",
    "rejected",
    "expired",
)

_SOURCES = ("landing", "demo")


def upgrade() -> None:
    op.create_table(
        "signup_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("role", sa.String(100), nullable=True),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default="pending_email_verify",
        ),
        sa.Column(
            "source",
            sa.String(20),
            nullable=False,
            server_default="landing",
        ),
        sa.Column(
            "email_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "moderated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "moderated_by_slack_user_id",
            sa.String(50),
            nullable=True,
        ),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("slack_message_ts", sa.String(40), nullable=True),
        # Snapshot of the originating demo tenant id (source='demo' only).
        # Stored for telemetry — handoff is currently out of scope (the
        # approve flow always provisions a fresh empty Tenant).
        sa.Column(
            "demo_tenant_id_snapshot",
            postgresql.UUID(as_uuid=True),
            nullable=True,
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
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _STATUSES) + ")",
            name="ck_signup_requests_status",
        ),
        sa.CheckConstraint(
            "source IN (" + ", ".join(f"'{s}'" for s in _SOURCES) + ")",
            name="ck_signup_requests_source",
        ),
    )
    # Case-insensitive uniqueness on email. We do NOT want two parallel
    # signup requests for the same address — a re-submit should either
    # reuse the existing row (if still pending) or 409 (if already
    # approved/rejected).
    op.create_index(
        "uq_signup_requests_email_lower",
        "signup_requests",
        [sa.text("lower(email)")],
        unique=True,
    )
    op.create_index(
        "ix_signup_requests_status",
        "signup_requests",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_signup_requests_status", table_name="signup_requests")
    op.drop_index(
        "uq_signup_requests_email_lower", table_name="signup_requests"
    )
    op.drop_table("signup_requests")
