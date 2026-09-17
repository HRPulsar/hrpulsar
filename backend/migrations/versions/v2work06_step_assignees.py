"""HRP-809: a step can name the person who does it and the person who
checks and signs it - ``executor_employee_id`` and
``accountable_employee_id``. Both optional; a deleted employee clears the
assignment, a terminated one is ignored by the coverage read.

Tenth revision of the HRPulsar 2.0 chain (epic HRP-746).
Downgrade order: ``v2work06 -> v2agnt02 -> v2merge02 -> ...``.

Revision ID: v2work06
Revises: v2agnt02
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v2work06"
down_revision: str | Sequence[str] | None = "v2agnt02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("executor_employee_id", "accountable_employee_id")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column(
            "work_steps",
            sa.Column(
                name,
                UUID(as_uuid=True),
                sa.ForeignKey("employees.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    for name in COLUMNS:
        op.drop_column("work_steps", name)
