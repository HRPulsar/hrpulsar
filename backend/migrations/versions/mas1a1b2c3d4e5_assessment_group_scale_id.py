"""Phase MAS1: assessment_groups.scale_id (HRP-34)

Revision ID: mas1a1b2c3d4e5
Revises: emp1a1b2c3d4e5
Create Date: 2026-05-07 13:10:00.000000

Stores the rating scale on the AssessmentGroup itself so the mass-assessment
page can show and edit it. Backfills from any non-snapshot child Assessment
that already has a scale_id (children sharing one value — typical case after
mass create).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "mas1a1b2c3d4e5"
down_revision = "emp1a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assessment_groups",
        sa.Column("scale_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_assessment_groups_scale_id",
        "assessment_groups",
        "answer_scales",
        ["scale_id"],
        ["id"],
    )

    # Backfill from children where every non-terminal child shares the same
    # scale_id; otherwise leave NULL (admin will pick one in UI).
    op.execute("""
        WITH per_group AS (
            SELECT
                a.group_id,
                MIN(a.scale_id::text) AS first_scale,
                COUNT(DISTINCT a.scale_id) AS scale_count
            FROM assessments a
            WHERE a.group_id IS NOT NULL
              AND a.scale_id IS NOT NULL
            GROUP BY a.group_id
        )
        UPDATE assessment_groups g
           SET scale_id = per_group.first_scale::uuid
          FROM per_group
         WHERE g.id = per_group.group_id
           AND per_group.scale_count = 1
    """)


def downgrade() -> None:
    op.drop_constraint(
        "fk_assessment_groups_scale_id",
        "assessment_groups",
        type_="foreignkey",
    )
    op.drop_column("assessment_groups", "scale_id")
