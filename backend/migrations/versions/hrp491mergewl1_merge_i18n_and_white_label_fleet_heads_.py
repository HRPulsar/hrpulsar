"""Merge i18n and white-label-fleet heads (HRP-491)

Revision ID: hrp491mergewl1
Revises: hrp480ailang01, aim1a2b3c4d5
Create Date: 2026-07-30 13:30:00.098974

"""

from collections.abc import Sequence

revision: str = "hrp491mergewl1"
down_revision: tuple[str, str] = ("hrp480ailang01", "aim1a2b3c4d5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
