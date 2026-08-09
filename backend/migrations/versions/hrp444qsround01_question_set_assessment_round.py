"""Bind a question set to the assessment round it prepares (HRP-444).

``question_sets.round_id`` already existed but points at ``interviews``
— the recording a dynamic_next set was derived *from*. The round a set
is *for* lives in the Manager assessments block
(``recruitment_assessment_rounds``), which is a different table, so
"one question set per round" had nothing to key off and New set kept
generating another Pre-interview set.

Additive and nullable: existing sets stay unbound.

Revision ID: hrp444qsround01
Revises: hrp442qslinks01
Create Date: 2026-08-05 17:25:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp444qsround01"
down_revision: str | None = "hrp442qslinks01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "question_sets",
        sa.Column("assessment_round_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_question_sets_assessment_round_id",
        "question_sets",
        ["assessment_round_id"],
    )
    op.create_foreign_key(
        "fk_question_sets_assessment_round",
        "question_sets",
        "recruitment_assessment_rounds",
        ["assessment_round_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_question_sets_assessment_round", "question_sets", type_="foreignkey"
    )
    op.drop_index("ix_question_sets_assessment_round_id", table_name="question_sets")
    op.drop_column("question_sets", "assessment_round_id")
