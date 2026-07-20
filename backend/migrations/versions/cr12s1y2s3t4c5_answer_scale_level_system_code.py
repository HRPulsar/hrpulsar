"""Phase CR12s: i18n-ready system_code on answer_scale_levels

Revision ID: cr12s1y2s3t4c5
Revises: cr11a1b2c3d4e5f
Create Date: 2026-05-03 17:00:00.000000

Origin/seeded answer-scale levels become i18n-keyed: the row carries a
stable `system_code` and an empty `system_title`; the frontend renders
the localized label through an i18n dictionary keyed by `system_code`.
Tenant-custom levels keep `system_code IS NULL` and continue to use the
free-text `system_title` written by HR.

Backfill targets rows seeded by `d1e2f3a4b5c6` (English titles after
v1.5.0):

  | percent range | system_title (post v1.5.0)             | system_code         |
  |---------------|----------------------------------------|---------------------|
  | 0–50          | Below expectations                     | below_expectations  |
  | 51–75         | Meets expectations with growth areas   | meets_with_growth   |
  | 76–100        | Fully meets expectations               | fully_meets         |

For backfilled rows we also blank `system_title` to NULL — there is no
title fallback. A CHECK constraint enforces that every row has either
`system_code` or `system_title` set.

Snapshots created before this migration carry the same English titles;
they are backfilled by exact title + percent range so completed
assessments still render through i18n.

A partial unique index `ux_scale_level_code_per_scale` enforces one
(scale_id, system_code) pair so future seed code can use plain UPSERT.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cr12s1y2s3t4c5"
down_revision: str | None = "cr11a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "answer_scale_levels",
        sa.Column("system_code", sa.String(length=50), nullable=True),
    )
    # Make `system_title` nullable so seeded rows can drop their English
    # text and rely on `system_code` only.
    op.alter_column(
        "answer_scale_levels",
        "system_title",
        existing_type=sa.String(length=255),
        nullable=True,
    )

    # Backfill origin/default scale rows seeded by d1e2f3a4b5c6.
    op.execute("""
        UPDATE answer_scale_levels
        SET system_code = 'below_expectations', system_title = NULL
        WHERE system_title = 'Below expectations'
          AND scale_id IN (
              SELECT id FROM answer_scales
              WHERE tenant_id IS NULL AND is_default = true
          )
        """)
    op.execute("""
        UPDATE answer_scale_levels
        SET system_code = 'meets_with_growth', system_title = NULL
        WHERE system_title = 'Meets expectations with growth areas'
          AND scale_id IN (
              SELECT id FROM answer_scales
              WHERE tenant_id IS NULL AND is_default = true
          )
        """)
    op.execute("""
        UPDATE answer_scale_levels
        SET system_code = 'fully_meets', system_title = NULL
        WHERE system_title = 'Fully meets expectations'
          AND scale_id IN (
              SELECT id FROM answer_scales
              WHERE tenant_id IS NULL AND is_default = true
          )
        """)

    # Snapshots created from the origin default scale before this migration
    # carry the same English titles. Backfill by exact title + percent range
    # so live and historical assessments share the i18n key.
    op.execute("""
        UPDATE answer_scale_levels l
        SET system_code = 'below_expectations', system_title = NULL
        FROM answer_scales s
        WHERE l.scale_id = s.id
          AND s.is_snapshot = true
          AND l.system_title = 'Below expectations'
          AND l.percent_from = 0 AND l.percent_to = 50
          AND l.system_code IS NULL
        """)
    op.execute("""
        UPDATE answer_scale_levels l
        SET system_code = 'meets_with_growth', system_title = NULL
        FROM answer_scales s
        WHERE l.scale_id = s.id
          AND s.is_snapshot = true
          AND l.system_title = 'Meets expectations with growth areas'
          AND l.percent_from = 51 AND l.percent_to = 75
          AND l.system_code IS NULL
        """)
    op.execute("""
        UPDATE answer_scale_levels l
        SET system_code = 'fully_meets', system_title = NULL
        FROM answer_scales s
        WHERE l.scale_id = s.id
          AND s.is_snapshot = true
          AND l.system_title = 'Fully meets expectations'
          AND l.percent_from = 76 AND l.percent_to = 100
          AND l.system_code IS NULL
        """)

    # Every row now has either an i18n key or a tenant-authored title.
    op.create_check_constraint(
        "ck_scale_level_code_or_title",
        "answer_scale_levels",
        "system_code IS NOT NULL OR system_title IS NOT NULL",
    )

    op.create_index(
        "ux_scale_level_code_per_scale",
        "answer_scale_levels",
        ["scale_id", "system_code"],
        unique=True,
        postgresql_where=sa.text("system_code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_scale_level_code_per_scale", table_name="answer_scale_levels")
    op.drop_constraint(
        "ck_scale_level_code_or_title", "answer_scale_levels", type_="check"
    )
    # Restore English titles on rows that lost them in upgrade(), so the
    # NOT NULL constraint can come back.
    op.execute("""
        UPDATE answer_scale_levels SET system_title = 'Below expectations'
        WHERE system_code = 'below_expectations' AND system_title IS NULL
        """)
    op.execute("""
        UPDATE answer_scale_levels
        SET system_title = 'Meets expectations with growth areas'
        WHERE system_code = 'meets_with_growth' AND system_title IS NULL
        """)
    op.execute("""
        UPDATE answer_scale_levels SET system_title = 'Fully meets expectations'
        WHERE system_code = 'fully_meets' AND system_title IS NULL
        """)
    op.alter_column(
        "answer_scale_levels",
        "system_title",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.drop_column("answer_scale_levels", "system_code")
