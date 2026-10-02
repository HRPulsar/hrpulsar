"""merge main into access-roles

Revision ID: v2merge04ar
Revises: v2sec01, v2work09
Create Date: 2026-09-24 00:00:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "v2merge04ar"
down_revision: str | Sequence[str] | None = ("v2sec01", "v2work09")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
