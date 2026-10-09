"""phase5_ai_embeddings — gutted.

HRP-1042 dropped the embeddings table and the pgvector dependency. The
revision id must survive so deployed databases keep a valid alembic chain,
but a fresh install must not require the pgvector extension or package —
so both upgrade and downgrade are no-ops.

Revision ID: ae00712520d5
Revises: fc66707e4d5b
"""

from collections.abc import Sequence

revision: str = "ae00712520d5"
down_revision: str | Sequence[str] | None = "fc66707e4d5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
