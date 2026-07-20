"""Passing score per grade + assessment recommendation snapshot

Revision ID: e7a8b9c0d1e2
Revises: d1e2f3a4b5c6
Create Date: 2026-04-29 14:00:00.000000

Adds the passing-score threshold to grade specializations, mass-assessment
groups and individual assessments. The grade-specialization column is the
authoritative reference value (default 75% backfilled for legacy rows);
``assessment_groups`` and ``assessments`` keep ``NULL`` for legacy rows so the
recommendation engine treats them as "no threshold configured". Each
assessment also gets ``recommended_grade_id`` + ``recommendation_payload``
slots for the cached recommendation result computed on transition to ``done``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7a8b9c0d1e2"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # grade_specializations: default threshold (75% backfilled for existing rows)
    op.add_column(
        "grade_specializations",
        sa.Column(
            "passing_score",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("75"),
        ),
    )
    op.execute(
        "UPDATE grade_specializations SET passing_score = 75 WHERE passing_score IS NULL"
    )
    op.create_check_constraint(
        "ck_grade_spec_passing_score_range",
        "grade_specializations",
        "passing_score IS NULL OR passing_score BETWEEN 0 AND 100",
    )

    # assessment_groups: per-group threshold (NULL = no recommendation for legacy)
    op.add_column(
        "assessment_groups",
        sa.Column("passing_score", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_assessment_group_passing_score_range",
        "assessment_groups",
        "passing_score IS NULL OR passing_score BETWEEN 0 AND 100",
    )

    # assessments: snapshot of threshold at criteria-set time + cached recommendation
    op.add_column(
        "assessments",
        sa.Column("passing_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "assessments",
        sa.Column(
            "recommended_grade_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dictionary_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "assessments",
        sa.Column(
            "recommendation_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_assessment_passing_score_range",
        "assessments",
        "passing_score IS NULL OR passing_score BETWEEN 0 AND 100",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_assessment_passing_score_range", "assessments", type_="check"
    )
    op.drop_column("assessments", "recommendation_payload")
    op.drop_column("assessments", "recommended_grade_id")
    op.drop_column("assessments", "passing_score")

    op.drop_constraint(
        "ck_assessment_group_passing_score_range", "assessment_groups", type_="check"
    )
    op.drop_column("assessment_groups", "passing_score")

    op.drop_constraint(
        "ck_grade_spec_passing_score_range",
        "grade_specializations",
        type_="check",
    )
    op.drop_column("grade_specializations", "passing_score")
