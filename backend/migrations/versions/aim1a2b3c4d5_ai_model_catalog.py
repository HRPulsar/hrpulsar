"""HRP-466: platform-wide AI model catalog.

Adds ``ai_model_catalog`` — the dynamic model list behind
``GET /admin/ai-settings/models``. Seeded from ``model_registry`` on first
read, extended by the daily ``refresh_model_catalog_task`` discovery sweep,
moderated in platform admin (SaaS).

Revision ID: aim1a2b3c4d5
Revises: hrp432trunc01
Create Date: 2026-07-27 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "aim1a2b3c4d5"
down_revision: str | None = "hrp432trunc01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_model_catalog",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="approved",
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("credit_multiplier", sa.Float(), nullable=True),
        sa.Column(
            "source", sa.String(length=20), nullable=False, server_default="seed"
        ),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
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
        sa.UniqueConstraint("provider", "model_id", name="uq_ai_model_catalog_model"),
    )
    # provider is covered by the unique constraint's leading column; the
    # pickability lookups (is_model_allowed / get_entry) filter by model_id.
    op.create_index("ix_ai_model_catalog_model_id", "ai_model_catalog", ["model_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_model_catalog_model_id", table_name="ai_model_catalog")
    op.drop_table("ai_model_catalog")
