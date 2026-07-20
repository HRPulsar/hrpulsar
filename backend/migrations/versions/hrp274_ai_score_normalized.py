"""HRP-274: add candidate_vacancies.ai_score_normalized.

Mirrors ``ai_score`` (LLM-raw) but rebased onto ``[0..1]`` against the
tenant's active ``ScaleConfig.max_value``. Lets the candidates table
compare cross-tenant scores in a single window and gives the recruiter
a toggle between raw and normalized.

Revision ID: hrp274ainormalized
Revises: hrp305demoguard
Create Date: 2026-06-30
"""

import sqlalchemy as sa
from alembic import op

revision = "hrp274ainormalized"
down_revision = "hrp305demoguard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_vacancies",
        sa.Column("ai_score_normalized", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_vacancies", "ai_score_normalized")
