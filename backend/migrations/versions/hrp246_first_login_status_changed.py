"""HRP-246: add users.first_login_at and employees.status_changed_at.

Powers the Employee profile header KPI tiles:

- ``users.first_login_at`` — stamped on the first successful auth so
  the Tenure tile can render "joined {first auth date}" and the Status
  tile sub-line can fall back to it for accounts that never had their
  status edited.
- ``employees.status_changed_at`` — stamped every time the employee
  status mutates so the Status tile can render
  "since {date of last status change}" instead of the create timestamp.

Both columns are nullable on purpose: existing rows backfill to NULL,
and the readers fall back to ``employees.created_at`` /
``employees.hire_date`` when the column is empty.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp246kpi"
down_revision: str | Sequence[str] | None = "tm6hrp242"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("first_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employees",
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("employees", "status_changed_at")
    op.drop_column("users", "first_login_at")
