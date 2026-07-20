"""HRP-274 follow-up: backfill candidate_vacancies.ai_score_normalized.

The initial HRP-274 code divided the raw LLM score by the tenant scale
max, but raw scores are on the 0..1 contract — existing rows therefore
hold tiny wrong values (e.g. 0.16 instead of 4.0 on a 0..5 scale).
Recompute every row as ``clamp(raw, 0..1) * scale_max`` with an identity
fallback (scale max 1.0) when the tenant has no active scale, matching
the fixed ``compute_normalized_ai_score``.

Revision ID: hrp274backfillnorm
Revises: addusertokenversion
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "hrp274backfillnorm"
down_revision = "addusertokenversion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE candidate_vacancies cv
            SET ai_score_normalized =
                LEAST(GREATEST(cv.ai_score, 0.0), 1.0) * COALESCE(
                    (
                        SELECT sc.max_value
                        FROM scale_configs sc
                        WHERE sc.tenant_id = cv.tenant_id
                          AND sc.is_active
                          AND sc.max_value > 0
                        LIMIT 1
                    ),
                    1.0
                )
            WHERE cv.ai_score IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    # Data-only backfill of previously incorrect values; nothing to restore.
    pass
