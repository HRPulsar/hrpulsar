"""merge main into access-roles

Revision ID: v2merge07ar
Revises: v2comp01, v2merge05
Create Date: 2026-10-01 00:00:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "v2merge07ar"
down_revision: str | Sequence[str] | None = ("v2comp01", "v2merge05")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
