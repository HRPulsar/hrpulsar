"""merge question-round and report-template heads after pack wave

Revision ID: 933b005f65e8
Revises: hrp444qsround01, hrp521droprepttpl01
Create Date: 2026-08-06 21:38:56.858272
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "933b005f65e8"
down_revision: str | Sequence[str] | None = ("hrp444qsround01", "hrp521droprepttpl01")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
