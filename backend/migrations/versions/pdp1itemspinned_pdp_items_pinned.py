"""PDP.items_pinned — protect explicit-competence plans (HRP-665 follow-up)

A plan built from an explicit competence list (the Talent Market gap
plan) owns its items; regenerating them from the (spec, grade) matrix on
a grade edit silently destroys the gap list, and ``PDPUpdate`` carries
no competence field to resupply it. The flag records where the items
came from so ``update_pdp`` can skip the matrix rebuild.

``server_default false``: every existing plan predates the explicit
list, so matrix regeneration stays their documented contract.

Revision ID: pdp1itemspinned
Revises: hrp678intsearch
Create Date: 2026-09-01 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "pdp1itemspinned"
down_revision: str | None = "hrp678intsearch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pdps",
        sa.Column(
            "items_pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("pdps", "items_pinned")
