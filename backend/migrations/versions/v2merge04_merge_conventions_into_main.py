"""merge the conventions branch (HRP-961) into main

Revision ID: v2merge04
Revises: hrp379714tplcopy, v2prim03
Create Date: 2026-09-29 12:00:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "v2merge04"
down_revision: str | Sequence[str] | None = ("hrp379714tplcopy", "v2prim03")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
