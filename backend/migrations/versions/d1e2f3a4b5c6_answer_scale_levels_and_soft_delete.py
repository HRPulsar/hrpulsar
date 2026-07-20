"""Answer scale levels, soft-delete, snapshots, neutral options, result percent/level

Revision ID: d1e2f3a4b5c6
Revises: c9d3f1b2a4e5
Create Date: 2026-04-29 12:00:00.000000

Post-release block of the rating scale customization feature:

  * Custom scales become editable/deletable via soft-delete + snapshot.
    `answer_scales.deleted_at` hides scales from the picker without
    breaking running assessments. `is_snapshot=true` rows are frozen
    copies created when an assessment leaves draft.
  * `answer_options.weight` becomes nullable so a "don't know" option
    (`is_neutral=true`) can be flagged as excluded from result math.
  * `answer_scale_levels` stores 1..100 percent ranges per scale; the
    default scale is seeded with three ranges per spec (0-50, 51-75,
    76-100). `assessment_results` gains `percent` + `level_id` so the
    UI can show e.g. "67% — Meets expectations with growth areas".
  * A partial unique index guards the singleton global default scale
    (`tenant_id IS NULL AND is_default=true AND deleted_at IS NULL`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c9d3f1b2a4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # answer_scales: soft-delete + snapshot flag
    op.add_column(
        "answer_scales",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "answer_scales",
        sa.Column(
            "is_snapshot",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_answer_scales_active",
        "answer_scales",
        ["tenant_id"],
        postgresql_where=sa.text("deleted_at IS NULL AND is_snapshot = false"),
    )
    op.create_index(
        "uq_answer_scales_global_default",
        "answer_scales",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text(
            "tenant_id IS NULL AND is_default = true AND deleted_at IS NULL"
        ),
    )

    # answer_options: neutral flag + nullable weight
    op.add_column(
        "answer_options",
        sa.Column(
            "is_neutral",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column("answer_options", "weight", nullable=True)

    # answer_scale_levels — new table
    op.create_table(
        "answer_scale_levels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "scale_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("answer_scales.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("percent_from", sa.Integer(), nullable=False),
        sa.Column("percent_to", sa.Integer(), nullable=False),
        sa.Column("system_title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column(
            "sort_index",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "percent_from BETWEEN 0 AND 100", name="ck_level_from_range"
        ),
        sa.CheckConstraint("percent_to BETWEEN 0 AND 100", name="ck_level_to_range"),
        sa.CheckConstraint("percent_from <= percent_to", name="ck_level_order"),
    )

    # assessment_results: percent + resolved level
    op.add_column(
        "assessment_results",
        sa.Column("percent", sa.Integer(), nullable=True),
    )
    op.add_column(
        "assessment_results",
        sa.Column(
            "level_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("answer_scale_levels.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Seed three default levels for the global default scale (per PDF).
    op.execute("""
        INSERT INTO answer_scale_levels (
            id, scale_id, percent_from, percent_to, system_title, description,
            sort_index, created_at, updated_at
        )
        SELECT gen_random_uuid(), s.id, 0, 50, 'Below expectations', NULL,
               0, now(), now()
        FROM answer_scales s
        WHERE s.tenant_id IS NULL AND s.is_default = true
        UNION ALL
        SELECT gen_random_uuid(), s.id, 51, 75,
               'Meets expectations with growth areas', NULL, 1, now(), now()
        FROM answer_scales s
        WHERE s.tenant_id IS NULL AND s.is_default = true
        UNION ALL
        SELECT gen_random_uuid(), s.id, 76, 100, 'Fully meets expectations',
               NULL, 2, now(), now()
        FROM answer_scales s
        WHERE s.tenant_id IS NULL AND s.is_default = true
        """)


def downgrade() -> None:
    op.drop_column("assessment_results", "level_id")
    op.drop_column("assessment_results", "percent")
    op.drop_table("answer_scale_levels")
    op.alter_column(
        "answer_options",
        "weight",
        nullable=False,
        existing_server_default=sa.text("0"),
    )
    op.drop_column("answer_options", "is_neutral")
    op.drop_index("uq_answer_scales_global_default", table_name="answer_scales")
    op.drop_index("ix_answer_scales_active", table_name="answer_scales")
    op.drop_column("answer_scales", "is_snapshot")
    op.drop_column("answer_scales", "deleted_at")
