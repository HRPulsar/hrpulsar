"""merge main into primitives-v2

Revision ID: v2merge03
Revises: hrp808branding, v2work06
Create Date: 2026-09-14 12:00:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "v2merge03"
down_revision: str | Sequence[str] | None = ("hrp808branding", "v2work06")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
