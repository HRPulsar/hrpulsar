"""compgen: track celery_task_id for cancel/revoke

Revision ID: cgr1a1b2c3d4e5
Revises: mas1a1b2c3d4e5
Create Date: 2026-05-07 19:30:00.000000

Adds `celery_task_id` to `competence_generation_sessions`. Captured at
enqueue time so `cancel_session` can call `celery.control.revoke(...)`
to drop a queued/running job from the worker instead of merely flipping
the DB status to `cancelled` while the LLM call keeps burning tokens.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cgr1a1b2c3d4e5"
down_revision: str | None = "mas1a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "competence_generation_sessions",
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("competence_generation_sessions", "celery_task_id")
