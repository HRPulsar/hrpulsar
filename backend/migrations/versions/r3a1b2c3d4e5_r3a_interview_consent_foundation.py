"""R3a: interview status fields, consent templates and consent requests

Adds the backend foundation for Phase R3 (interview, transcription and AI
analysis):

- Extends ``interviews`` with consent / transcription / analysis status
  columns plus an ``analysis_data`` JSONB blob for the AI verdict payload.
- Creates ``consent_templates`` (system-managed candidate consent
  templates, one active per tenant).
- Creates ``consent_requests`` (token-backed magic-link records used to
  capture candidate consent before audio/video uploads).

Revision ID: r3a1b2c3d4e5
Revises: r2c1d2e3f4a5
Create Date: 2026-05-08 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "r3a1b2c3d4e5"
down_revision: str | None = "r2c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── consent_templates ──────────────────────────────────────────────
    op.create_table(
        "consent_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "language",
            sa.String(10),
            nullable=False,
            server_default="en",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_consent_templates_tenant_id",
        "consent_templates",
        ["tenant_id"],
    )
    op.create_index(
        "ix_consent_templates_active_unique",
        "consent_templates",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    # ── consent_requests ───────────────────────────────────────────────
    op.create_table(
        "consent_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("consent_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token", sa.String(100), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_ip", sa.String(45), nullable=True),
        sa.Column("signed_user_agent", sa.String(500), nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_consent_requests_tenant_id",
        "consent_requests",
        ["tenant_id"],
    )
    op.create_index(
        "ix_consent_requests_candidate_id",
        "consent_requests",
        ["candidate_id"],
    )
    op.create_index(
        "ix_consent_requests_token",
        "consent_requests",
        ["token"],
        unique=True,
    )

    # ── interviews additions ───────────────────────────────────────────
    op.add_column(
        "interviews",
        sa.Column(
            "consent_signed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "consent_template_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_interviews_consent_template_id",
        "interviews",
        "consent_templates",
        ["consent_template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_interviews_consent_template_id",
        "interviews",
        ["consent_template_id"],
    )
    op.add_column(
        "interviews",
        sa.Column("transcription_provider", sa.String(50), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "transcription_status",
            sa.String(50),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "analysis_status",
            sa.String(50),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "interviews",
        sa.Column("transcription_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column("analysis_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column("analysis_data", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "ix_interviews_tenant_transcription_status",
        "interviews",
        ["tenant_id", "transcription_status"],
    )
    op.create_index(
        "ix_interviews_tenant_analysis_status",
        "interviews",
        ["tenant_id", "analysis_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interviews_tenant_analysis_status", table_name="interviews"
    )
    op.drop_index(
        "ix_interviews_tenant_transcription_status", table_name="interviews"
    )
    op.drop_column("interviews", "analysis_data")
    op.drop_column("interviews", "analysis_error")
    op.drop_column("interviews", "transcription_error")
    op.drop_column("interviews", "analysis_status")
    op.drop_column("interviews", "transcription_status")
    op.drop_column("interviews", "transcription_provider")
    op.drop_index("ix_interviews_consent_template_id", table_name="interviews")
    op.drop_constraint(
        "fk_interviews_consent_template_id",
        "interviews",
        type_="foreignkey",
    )
    op.drop_column("interviews", "consent_template_id")
    op.drop_column("interviews", "consent_signed_at")

    op.drop_index("ix_consent_requests_token", table_name="consent_requests")
    op.drop_index(
        "ix_consent_requests_candidate_id", table_name="consent_requests"
    )
    op.drop_index(
        "ix_consent_requests_tenant_id", table_name="consent_requests"
    )
    op.drop_table("consent_requests")

    op.drop_index(
        "ix_consent_templates_active_unique", table_name="consent_templates"
    )
    op.drop_index(
        "ix_consent_templates_tenant_id", table_name="consent_templates"
    )
    op.drop_table("consent_templates")
