"""hrp151_employment_division_position

Revision ID: hrp151empl001
Revises: r4c1b2c3d4e5
Create Date: 2026-05-22 12:00:00.000000

Reframe work_experiences as the Current Employment block: add
division_id / position_id FKs that drive the form defaults and the
duration display, and relax the legacy title NOT NULL so new rows
created from the rebuilt UI don't need a project-style title.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp151empl001"
down_revision: str | None = "r4c1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_experiences",
        sa.Column("division_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "work_experiences",
        sa.Column("position_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_work_experiences_division_id",
        "work_experiences",
        "divisions",
        ["division_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_work_experiences_position_id",
        "work_experiences",
        "positions",
        ["position_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_work_experiences_division_id"),
        "work_experiences",
        ["division_id"],
    )
    op.create_index(
        op.f("ix_work_experiences_position_id"),
        "work_experiences",
        ["position_id"],
    )
    op.alter_column(
        "work_experiences", "title", existing_type=sa.String(length=255), nullable=True
    )


def downgrade() -> None:
    # HRP-163 review: the rebuilt UI shipped under upgrade() writes rows
    # with NULL title. A naive alter_column nullable=False would raise a
    # constraint violation on those rows, leaving the downgrade half-
    # applied. Backfill before reapplying NOT NULL so the migration is
    # safe to run on any environment that already accepted the upgrade.
    op.execute(
        "UPDATE work_experiences SET title = 'Untitled' WHERE title IS NULL"
    )
    op.alter_column(
        "work_experiences", "title", existing_type=sa.String(length=255), nullable=False
    )
    op.drop_index(
        op.f("ix_work_experiences_position_id"), table_name="work_experiences"
    )
    op.drop_index(
        op.f("ix_work_experiences_division_id"), table_name="work_experiences"
    )
    op.drop_constraint(
        "fk_work_experiences_position_id", "work_experiences", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_work_experiences_division_id", "work_experiences", type_="foreignkey"
    )
    op.drop_column("work_experiences", "position_id")
    op.drop_column("work_experiences", "division_id")
