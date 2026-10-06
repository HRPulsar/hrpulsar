"""A public check remembers it was dictated, review 2.2 D3

Revision ID: rf3d_pc_dictated
Revises: rf3c_pc_check_confirm
Create Date: 2026-10-05 12:00:00.000000

* ``public_checks.dictated`` - the description was dictated by voice
  (HRP-947); ``CheckRead`` hands it to "try again", so the new check's model
  is told so as well. Existing checks read as typed.

Additive.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "rf3d_pc_dictated"
down_revision: str | Sequence[str] | None = "rf3c_pc_check_confirm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "public_checks",
        sa.Column("dictated", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("public_checks", "dictated")
