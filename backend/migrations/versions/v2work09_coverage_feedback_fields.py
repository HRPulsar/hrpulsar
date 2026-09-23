"""HRP-858 (Coverage feedback wave): the columns the wave's tasks share, in
one revision so the parallel branches of the wave never grow two heads.

``work_steps``:

- ``review_human_share`` (HRP-861) - percent of a reviewed step's hours that
  stays with the person who checks the agent's work; null is the default
  share;
- ``manual_mode`` / ``manual_pack_code`` (HRP-863) - the company's override of
  the computed automation mode and of the matched agent pack;
- ``hourly_rate`` (HRP-868) - the step's own rate in the tenant's currency;
  null falls back to ``tenants.hourly_rate``.

``work_containers.coverage_summary`` (HRP-862) - the figures the list page
shows, written whenever coverage is computed.

All nullable, no backfill: a null in every one of them is today's behaviour.

Revision ID: v2work09
Revises: v2idx01
Create Date: 2026-09-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v2work09"
down_revision: str | Sequence[str] | None = "v2idx01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_steps", sa.Column("review_human_share", sa.SmallInteger(), nullable=True)
    )
    op.add_column("work_steps", sa.Column("manual_mode", sa.String(20), nullable=True))
    op.add_column(
        "work_steps", sa.Column("manual_pack_code", sa.String(50), nullable=True)
    )
    op.add_column(
        "work_steps", sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=True)
    )
    op.create_check_constraint(
        "ck_work_steps_review_human_share",
        "work_steps",
        "review_human_share IS NULL OR "
        "(review_human_share >= 0 AND review_human_share <= 100)",
    )
    op.create_check_constraint(
        "ck_work_steps_manual_mode",
        "work_steps",
        "manual_mode IS NULL OR manual_mode IN ('automatable', 'draft_then_review', "
        "'review_required', 'blocked_judgment', 'blocked_physical')",
    )
    op.add_column(
        "work_containers",
        sa.Column("coverage_summary", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_containers", "coverage_summary")
    op.drop_constraint("ck_work_steps_manual_mode", "work_steps", type_="check")
    op.drop_constraint("ck_work_steps_review_human_share", "work_steps", type_="check")
    op.drop_column("work_steps", "hourly_rate")
    op.drop_column("work_steps", "manual_pack_code")
    op.drop_column("work_steps", "manual_mode")
    op.drop_column("work_steps", "review_human_share")
