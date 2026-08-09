"""merge pack wave 2 heads

Revision ID: c47fc6f13693
Revises: hrp373evaltmpl01, hrp419ivmail01, hrp494ainotify01, hrp498llmprovmodel01
Create Date: 2026-08-07 12:51:11.920174
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c47fc6f13693"
down_revision: str | Sequence[str] | None = (
    "hrp373evaltmpl01",
    "hrp419ivmail01",
    "hrp494ainotify01",
    "hrp498llmprovmodel01",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
