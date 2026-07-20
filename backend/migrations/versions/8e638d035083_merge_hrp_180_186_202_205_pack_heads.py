"""merge HRP-180/186/202/205 pack heads

Revision ID: 8e638d035083
Revises: hrp180vacancyposlink, hrp186managerassess, hrp202inthr01, hrp205indqs01
Create Date: 2026-06-02 20:58:33.283722
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "8e638d035083"
down_revision: tuple[str, ...] | None = (
    "hrp180vacancyposlink",
    "hrp186managerassess",
    "hrp202inthr01",
    "hrp205indqs01",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
