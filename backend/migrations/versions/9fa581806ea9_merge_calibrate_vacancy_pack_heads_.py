"""Merge calibrate + vacancy pack heads (round 2)

Revision ID: 9fa581806ea9
Revises: 429140e93e49, hrp185calibrate01, v2a1b2c3d4e5
Create Date: 2026-05-30 19:28:52.682049

"""

from collections.abc import Sequence

revision: str = "9fa581806ea9"
down_revision: tuple[str, str, str] = (
    "429140e93e49",
    "hrp185calibrate01",
    "v2a1b2c3d4e5",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
