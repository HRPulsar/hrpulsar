"""merge main into primitives-v2

Revision ID: v2merge02
Revises: hrp781stagei18n01, v2work05
Create Date: 2026-09-11 18:12:52.020971
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "v2merge02"
down_revision: str | Sequence[str] | None = ("hrp781stagei18n01", "v2work05")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
