"""merge the per-tenant AI processors branch (HRP-1005) into main

Revision ID: v2merge05
Revises: v2merge04, hrp1005aiproc01
Create Date: 2026-09-30 12:00:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "v2merge05"
down_revision: str | Sequence[str] | None = ("v2merge04", "hrp1005aiproc01")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
