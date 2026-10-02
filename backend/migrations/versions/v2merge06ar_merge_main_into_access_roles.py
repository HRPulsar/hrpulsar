"""merge main into access-roles

Revision ID: v2merge06ar
Revises: v2sec02, hrp379714tplcopy
Create Date: 2026-09-29 00:00:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "v2merge06ar"
down_revision: str | Sequence[str] | None = ("v2sec02", "hrp379714tplcopy")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
