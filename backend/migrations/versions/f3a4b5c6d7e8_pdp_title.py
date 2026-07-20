"""PDP plan title

Revision ID: f3a4b5c6d7e8
Revises: e7a8b9c0d1e2
Create Date: 2026-04-29 16:00:00.000000

Adds ``pdps.title`` (NOT NULL VARCHAR(255)). Existing rows are backfilled with
``'Development Plan'`` so the column can be enforced NOT NULL without breaking
legacy plans. The server_default is dropped after the backfill — title is
required at the application layer (PDPCreate.title).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "e7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pdps",
        sa.Column(
            "title",
            sa.String(length=255),
            nullable=False,
            server_default="Development Plan",
        ),
    )
    op.execute("UPDATE pdps SET title = 'Development Plan' WHERE title = ''")
    op.alter_column("pdps", "title", server_default=None)


def downgrade() -> None:
    op.drop_column("pdps", "title")
