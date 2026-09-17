"""W6 (decision 2026-09-11): the step's yearly hours replace the ordinal
frequency / effort scales - ``hours_per_run`` and ``runs_per_year``, the
model's estimate the company corrects - and the tenant gets an hourly
rate for the ROI in money.

Backfill of the scales before they are dropped: ``low / medium / high``
-> 0.5 / 2 / 8 hours and 12 / 52 / 250 runs. Defaults, not a measure; the
next regeneration replaces them with the model's estimate.

The upper bound on ``runs_per_year`` is deliberately far above any human
process (an emergency department triages tens of thousands of patients a
year): it exists to catch a hallucinated digit run, not to cap reality.

Eighth revision of the HRPulsar 2.0 chain (epic HRP-746).
Downgrade order: ``v2work05 -> v2work04 -> v2work03 -> ...``.

Revision ID: v2work05
Revises: v2work04
Create Date: 2026-09-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v2work05"
down_revision: str | Sequence[str] | None = "v2work04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_steps", sa.Column("hours_per_run", sa.Numeric(6, 2), nullable=True)
    )
    op.add_column("work_steps", sa.Column("runs_per_year", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_work_steps_hours_per_run",
        "work_steps",
        "hours_per_run IS NULL OR (hours_per_run >= 0.01 AND hours_per_run <= 200)",
    )
    op.create_check_constraint(
        "ck_work_steps_runs_per_year",
        "work_steps",
        "runs_per_year IS NULL OR (runs_per_year >= 1 AND runs_per_year <= 1000000)",
    )
    op.execute(
        """
        UPDATE work_steps SET
            hours_per_run = CASE effort
                WHEN 'low' THEN 0.5 WHEN 'medium' THEN 2 WHEN 'high' THEN 8 END,
            runs_per_year = CASE frequency
                WHEN 'low' THEN 12 WHEN 'medium' THEN 52 WHEN 'high' THEN 250 END
        """
    )
    op.drop_constraint("ck_work_steps_frequency", "work_steps", type_="check")
    op.drop_constraint("ck_work_steps_effort", "work_steps", type_="check")
    op.drop_column("work_steps", "frequency")
    op.drop_column("work_steps", "effort")

    op.add_column("tenants", sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=True))
    op.add_column(
        "tenants", sa.Column("hourly_rate_currency", sa.String(10), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("tenants", "hourly_rate_currency")
    op.drop_column("tenants", "hourly_rate")

    op.add_column(
        "work_steps", sa.Column("frequency", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "work_steps", sa.Column("effort", sa.String(length=10), nullable=True)
    )
    # The inverse of the backfill's thresholds, not of its exact values.
    op.execute(
        """
        UPDATE work_steps SET
            effort = CASE
                WHEN hours_per_run IS NULL THEN NULL
                WHEN hours_per_run < 1 THEN 'low'
                WHEN hours_per_run < 4 THEN 'medium' ELSE 'high' END,
            frequency = CASE
                WHEN runs_per_year IS NULL THEN NULL
                WHEN runs_per_year <= 12 THEN 'low'
                WHEN runs_per_year <= 52 THEN 'medium' ELSE 'high' END
        """
    )
    op.create_check_constraint(
        "ck_work_steps_frequency",
        "work_steps",
        "frequency IS NULL OR frequency IN ('high', 'medium', 'low')",
    )
    op.create_check_constraint(
        "ck_work_steps_effort",
        "work_steps",
        "effort IS NULL OR effort IN ('high', 'medium', 'low')",
    )
    op.drop_constraint("ck_work_steps_runs_per_year", "work_steps", type_="check")
    op.drop_constraint("ck_work_steps_hours_per_run", "work_steps", type_="check")
    op.drop_column("work_steps", "runs_per_year")
    op.drop_column("work_steps", "hours_per_run")
