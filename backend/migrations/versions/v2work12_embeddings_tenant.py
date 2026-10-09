"""HRP-954 embeddings tenant scoping — gutted (HRP-1042 dropped the table).

The revision id must survive so deployed databases keep a valid alembic
chain; both upgrade and downgrade are no-ops.

Revision ID: v2work12
Revises: v2work11
"""

from collections.abc import Sequence

revision: str = "v2work12"
down_revision: str | Sequence[str] | None = "v2work11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
