"""Drop embeddings table and pgvector extension.

The semantic-search API was the only consumer and had none itself
(HRP-1042). IF EXISTS everywhere: a fresh database created after the
old revisions were gutted never had the table or the extension.

Revision ID: hrp1042dropemb
Revises: hrp1028wfowner
"""

from collections.abc import Sequence

from alembic import op

revision: str = "hrp1042dropemb"
down_revision: str | Sequence[str] | None = "hrp1028wfowner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS embeddings")
    # On managed installs the extension may be owned by a superuser, not the
    # app role (hrpulsar-ru deploy, 09.10). Nothing references it once the
    # table is gone, so leave it in place rather than fail the migration;
    # ops can drop it as a superuser at their leisure.
    op.execute(
        """
        DO $$
        BEGIN
            DROP EXTENSION IF EXISTS vector;
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE
                'pgvector extension left in place: not the owner, drop it as a superuser';
        END
        $$;
        """
    )


def downgrade() -> None:
    # Forward-only (project convention): recreating a derived-data table
    # nothing writes to would be dead code.
    pass
