"""merge pack-tm + pack-ass + main HRP-221 heads

Revision ID: b5479f096f8b
Revises: hrp194stitles, hrp221amount01, tm5a1b2c3d4e5
Create Date: 2026-06-04 23:13:44.249668
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "b5479f096f8b"
down_revision: tuple[str, ...] = ("hrp194stitles", "hrp221amount01", "tm5a1b2c3d4e5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
