"""Merge tm3a + hrp151 heads after pack release

Revision ID: 6162d7ab9e32
Revises: hrp151empl001, tm3a1b2c3d4e5
Create Date: 2026-05-22 18:20:09.906759
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "6162d7ab9e32"
down_revision: tuple[str, str] = ("hrp151empl001", "tm3a1b2c3d4e5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
