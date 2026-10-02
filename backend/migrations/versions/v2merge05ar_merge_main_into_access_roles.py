"""merge main into access-roles

Revision ID: v2merge05ar
Revises: v2merge04ar, v2work11
Create Date: 2026-09-25 00:00:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "v2merge05ar"
down_revision: str | Sequence[str] | None = ("v2merge04ar", "v2work11")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
