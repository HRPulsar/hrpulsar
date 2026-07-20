"""Phase CR10b: tenant AI settings table

Revision ID: cr10b1a2b3c4d5
Revises: cr1a0b1c2d3e4
Create Date: 2026-05-01 12:00:00.000000

Adds `tenant_ai_settings` — per-tenant overrides for content language,
effort tier, custom model, temperature, retries, and company context.
Consumed by every AI generation task (competences, indicators, PDP,
positions) and by the upcoming CR11 generation sessions.

`content_language` is intentionally locked to `'en'` for now; Phase F
(i18n) will expand the CHECK via ALTER once the prompts and validation
layer support more languages.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cr10b1a2b3c4d5"
down_revision: str | None = "cr1a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_ai_settings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "content_language",
            sa.String(length=10),
            nullable=False,
            server_default="en",
        ),
        sa.Column(
            "effort_level",
            sa.String(length=20),
            nullable=False,
            server_default="balanced",
        ),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("company_context", sa.String(length=2000), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_ai_settings_tenant_id"),
        sa.CheckConstraint(
            "content_language IN ('en')",
            name="ck_tenant_ai_settings_content_language",
        ),
        sa.CheckConstraint(
            "effort_level IN ('fast','balanced','thorough','custom')",
            name="ck_tenant_ai_settings_effort_level",
        ),
        sa.CheckConstraint(
            "temperature >= 0 AND temperature <= 1",
            name="ck_tenant_ai_settings_temperature_range",
        ),
        sa.CheckConstraint(
            "max_retries >= 1 AND max_retries <= 10",
            name="ck_tenant_ai_settings_max_retries_range",
        ),
        sa.CheckConstraint(
            "company_context IS NULL OR length(company_context) <= 2000",
            name="ck_tenant_ai_settings_company_context_length",
        ),
    )
    op.create_index(
        "ix_tenant_ai_settings_tenant_id",
        "tenant_ai_settings",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_ai_settings_tenant_id", table_name="tenant_ai_settings")
    op.drop_table("tenant_ai_settings")
