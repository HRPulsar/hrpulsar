"""HRP-1197: a step done by people may name several executors -
``work_step_executors``, one row per (step, employee).

The table is the one source of truth from here on: every executor already
named in ``work_steps.executor_employee_id`` is copied in, and nothing
reads or writes that column any more. It is kept, not dropped - an
additive migration, and the previous release still reads it while a deploy
migrates ahead of the swap; a later migration drops it. A deleted step or
employee takes its rows with it, the way the column's ``SET NULL`` cleared
the assignment.

Downgrade writes each step's first executor back into the column, so the
release below keeps one of the people named since, and drops the table.

Revision ID: hrp1197executors
Revises: hrp801needcard
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "hrp1197executors"
down_revision: str | Sequence[str] | None = "hrp801needcard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_step_executors"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["work_steps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("step_id", "employee_id", name="uq_work_step_executor"),
    )
    op.create_index(f"ix_{TABLE}_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_work_step_executors_employee", TABLE, ["employee_id"])
    op.execute(
        f"INSERT INTO {TABLE} (tenant_id, step_id, employee_id) "
        "SELECT tenant_id, id, executor_employee_id FROM work_steps "
        "WHERE executor_employee_id IS NOT NULL "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE work_steps SET executor_employee_id = ("
        f"SELECT e.employee_id FROM {TABLE} e WHERE e.step_id = work_steps.id "
        "ORDER BY e.created_at, e.id LIMIT 1)"
    )
    op.drop_table(TABLE)
