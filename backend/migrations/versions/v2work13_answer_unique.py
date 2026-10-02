"""HRP-910: one answer per participant and question.

Two saves of the same question racing through ``record_answer`` both
inserted, and every later save failed on the pair - the survey could not
be finished. Repair the data first (keep the latest row per
``(participant_id, indicator_id)`` by ``updated_at``, then ``id``), then
make the duplicate impossible.

Revision ID: v2work13
Revises: v2work12
Create Date: 2026-09-28

"""

from collections.abc import Sequence

from alembic import op

revision: str = "v2work13"
down_revision: str | Sequence[str] | None = "v2work12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "uq_assessment_answers_participant_indicator"
TABLE = "assessment_answers"

# Deletes every duplicate that has a later sibling: the row with the
# greatest (updated_at, id) per (participant, indicator) survives.
DEDUPE_SQL = f"""
DELETE FROM {TABLE} a
USING {TABLE} b
WHERE a.participant_id = b.participant_id
  AND a.indicator_id = b.indicator_id
  AND (a.updated_at, a.id) < (b.updated_at, b.id)
"""


def upgrade() -> None:
    op.execute(DEDUPE_SQL)
    op.create_unique_constraint(CONSTRAINT, TABLE, ["participant_id", "indicator_id"])


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="unique")
