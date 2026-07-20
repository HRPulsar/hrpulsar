"""R4b: settings hub additions, audit log, GDPR tables

Adds:
- ``tenants.recruitment_branding`` (JSONB) for SCR-95 branding overrides.
- ``recruitment_retention_configs`` (SCR-96) — per-tenant retention windows.
- ``recruitment_audit_log`` (FR-28) — append-only audit trail.
- ``gdpr_export_requests`` and ``gdpr_erasure_log`` (§9.2).

Revision ID: r4b1b2c3d4e5
Revises: r4a1b2c3d4e5
Create Date: 2026-05-09 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "r4b1b2c3d4e5"
down_revision: str | None = "r4a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── tenants.recruitment_branding ───────────────────────────────────
    op.add_column(
        "tenants",
        sa.Column(
            "recruitment_branding",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # ── scale_configs.is_active (was missing in R1; needed for SCR-90) ──
    op.add_column(
        "scale_configs",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # ── recruitment_retention_configs ──────────────────────────────────
    op.create_table(
        "recruitment_retention_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interviews_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("resumes_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("consents_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("reports_days", sa.Integer(), nullable=False, server_default="365"),
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
    op.create_index(
        "ix_recruitment_retention_configs_tenant_unique",
        "recruitment_retention_configs",
        ["tenant_id"],
        unique=True,
    )

    # ── recruitment_audit_log ──────────────────────────────────────────
    op.create_table(
        "recruitment_audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "payload_diff",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
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
    op.create_index(
        "ix_recruitment_audit_log_tenant_created",
        "recruitment_audit_log",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_recruitment_audit_log_entity",
        "recruitment_audit_log",
        ["tenant_id", "entity_type", "entity_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_recruitment_audit_log_user_id",
        "recruitment_audit_log",
        ["user_id"],
    )

    # ── gdpr_export_requests ───────────────────────────────────────────
    op.create_table(
        "gdpr_export_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject_type", sa.String(length=50), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
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
    op.create_index(
        "ix_gdpr_export_requests_tenant",
        "gdpr_export_requests",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_gdpr_export_requests_subject",
        "gdpr_export_requests",
        ["tenant_id", "subject_type", "subject_id"],
    )

    # ── gdpr_erasure_log ───────────────────────────────────────────────
    op.create_table(
        "gdpr_erasure_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject_type", sa.String(length=50), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "affected",
            postgresql.JSONB(astext_type=sa.Text()),
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
    )
    op.create_index(
        "ix_gdpr_erasure_log_tenant",
        "gdpr_erasure_log",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_gdpr_erasure_log_subject",
        "gdpr_erasure_log",
        ["tenant_id", "subject_type", "subject_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_gdpr_erasure_log_subject", table_name="gdpr_erasure_log")
    op.drop_index("ix_gdpr_erasure_log_tenant", table_name="gdpr_erasure_log")
    op.drop_table("gdpr_erasure_log")

    op.drop_index(
        "ix_gdpr_export_requests_subject", table_name="gdpr_export_requests"
    )
    op.drop_index(
        "ix_gdpr_export_requests_tenant", table_name="gdpr_export_requests"
    )
    op.drop_table("gdpr_export_requests")

    op.drop_index(
        "ix_recruitment_audit_log_user_id", table_name="recruitment_audit_log"
    )
    op.drop_index(
        "ix_recruitment_audit_log_entity", table_name="recruitment_audit_log"
    )
    op.drop_index(
        "ix_recruitment_audit_log_tenant_created",
        table_name="recruitment_audit_log",
    )
    op.drop_table("recruitment_audit_log")

    op.drop_index(
        "ix_recruitment_retention_configs_tenant_unique",
        table_name="recruitment_retention_configs",
    )
    op.drop_table("recruitment_retention_configs")

    op.drop_column("scale_configs", "is_active")
    op.drop_column("tenants", "recruitment_branding")
