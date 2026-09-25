"""HRP-944: ``work_steps.classified_at`` - when the step's codes were last
decided, by the model or by the company, an empty set included. Null marks a
step typed in with no codes that nobody has classified: coverage shows it as
``unclassified`` instead of «needs no capability».

Backfill: every existing step counts as classified except a step still
``tenant_edited``, without a single code and not created by an applied AI
session. That is the shape of a step typed in by hand and never
classified - and also, indistinguishably, of a company's empty answer given
before this revision (every chip removed, an empty reclassification, the
picker saved empty). Such a step reads «not classified» until the company
saves the picker empty or reclassifies it again: asking once more is
preferred to hiding a step nobody classified. An accepted breakdown and the
demo data keep today's verdicts.

Revision ID: v2work10
Revises: v2work09
Create Date: 2026-09-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v2work10"
down_revision: str | Sequence[str] | None = "v2work09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_steps",
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE work_steps AS s SET classified_at = s.updated_at
        WHERE NOT (
            s.state = 'tenant_edited'
            AND NOT EXISTS (
                SELECT 1 FROM work_step_primitives p WHERE p.step_id = s.id
            )
            AND NOT EXISTS (
                SELECT 1 FROM work_decomposition_sessions d
                WHERE d.container_id = s.container_id
                  AND d.status = 'applied'
                  AND d.applied_result -> 'created_steps' ? s.id::text
            )
        )
        """
    )
    # Set after the backfill, so the backfill decides the existing rows; from
    # here on a writer that does not know the column (the old backend still
    # serving during a deploy) marks its steps classified.
    op.alter_column("work_steps", "classified_at", server_default=sa.text("now()"))


def downgrade() -> None:
    op.drop_column("work_steps", "classified_at")
