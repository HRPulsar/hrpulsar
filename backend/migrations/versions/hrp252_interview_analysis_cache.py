"""HRP-252 (D4): interview analysis cache table.

Stores the JSON snapshot of an Interview AI analysis keyed by
sha256(transcript + vacancy_profile.id + profile.version). A subsequent
``POST /recruitment/interviews/{id}/analyze`` against the same input
short-circuits to the cached payload and skips both the LLM call and
the credit deduction. Scoped per-tenant — two tenants on the same
transcript do not share rows.

Revision ID: hrp252cache
Revises: hrp249demo
Create Date: 2026-06-13 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp252cache"
down_revision: str | None = "hrp249demo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_analysis_cache",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("analysis_data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "assessments",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
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
        sa.UniqueConstraint(
            "tenant_id", "cache_key", name="uq_interview_analysis_cache_key"
        ),
    )
    # No standalone indexes: every lookup is ``WHERE tenant_id=:t AND
    # cache_key=:k`` and is fully covered by the (tenant_id, cache_key)
    # UNIQUE btree above.


def downgrade() -> None:
    op.drop_table("interview_analysis_cache")
