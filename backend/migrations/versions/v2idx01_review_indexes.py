"""HRP-746 pre-release review: the three foreign keys the 2.0 chain created
without an index behind them.

``work_steps.executor_employee_id`` / ``accountable_employee_id``
(``v2work06``) and ``ai_agent_primitives.primitive_id`` (``v2agnt01``) are
all read the other way round from the constraint that covers them: the
step list filters by assignee, the unique constraint on
``ai_agent_primitives`` leads with ``agent_id``. Every delete of an
employee (ON DELETE SET NULL) and every RESTRICT check on a retiring
primitive scans the whole table without these.

The two ``work_steps`` indexes carry the names SQLAlchemy's ``index=True``
would generate, so declaring them on ``WorkStep`` later is a no-op for the
database and closes the entry in ``ALLOWED_DRIFT``
(``tests/unit/test_schema_drift.py``).

Revision ID: v2idx01
Revises: v2work08
Create Date: 2026-09-16

"""

from collections.abc import Sequence

from alembic import op

revision: str = "v2idx01"
down_revision: str | Sequence[str] | None = "v2work08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = (
    ("ix_work_steps_executor_employee_id", "work_steps", "executor_employee_id"),
    ("ix_work_steps_accountable_employee_id", "work_steps", "accountable_employee_id"),
    ("ix_agent_prim_primitive_id", "ai_agent_primitives", "primitive_id"),
)


def upgrade() -> None:
    for name, table, column in INDEXES:
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _column in reversed(INDEXES):
        op.drop_index(name, table_name=table)
