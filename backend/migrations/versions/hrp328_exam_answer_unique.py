"""HRP-328: unique (exam_id, question_id) on exam_answers.

The take sheet autosaves answers; the application-level upsert alone is
race-prone (two concurrent saves both pass the SELECT and both INSERT,
double-counting the question weight in finish_exam). Deduplicate the rows
the old append-only submit_answer left behind — keep the most recent one
per (exam, question) — then enforce uniqueness at the database level.

Revision ID: hrp328answeruniq
Revises: hrp202redo01
Create Date: 2026-07-10
"""

import sqlalchemy as sa
from alembic import op

revision: str = "hrp328answeruniq"
down_revision: str | None = "hrp202redo01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            DELETE FROM exam_answers a
            USING exam_answers b
            WHERE a.exam_id = b.exam_id
              AND a.question_id = b.question_id
              AND (a.created_at, a.id) < (b.created_at, b.id)
            """
        )
    )
    op.create_unique_constraint(
        "uq_exam_answer_exam_question",
        "exam_answers",
        ["exam_id", "question_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_exam_answer_exam_question", "exam_answers", type_="unique"
    )
