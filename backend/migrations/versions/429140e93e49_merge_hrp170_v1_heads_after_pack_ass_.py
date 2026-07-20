"""Merge hrp170 + v1 heads after pack-ass/pack-rec

Revision ID: 429140e93e49
Revises: hrp170recompute01, v1a1b2c3d4e5
Create Date: 2026-05-30 10:32:02.812938

"""

from collections.abc import Sequence

revision: str = "429140e93e49"
down_revision: tuple[str, str] = ("hrp170recompute01", "v1a1b2c3d4e5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
