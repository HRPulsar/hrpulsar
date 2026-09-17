"""HRP-746 pre-release review: index ``latest_session``.

The editor asks for a container's newest decomposition run on every open
and while one is polling. The existing partial index covers only the
active statuses, so a container whose newest run is ``applied`` or
``cancelled`` — every container that has ever been decomposed — answered
that query with a sequential scan of the table.

Revision ID: v2work08
Revises: v2work07
Create Date: 2026-09-16

"""

from collections.abc import Sequence

from alembic import op

revision: str = "v2work08"
down_revision: str | Sequence[str] | None = "v2work07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_workdecomp_container_created"
TABLE = "work_decomposition_sessions"


def upgrade() -> None:
    op.create_index(INDEX, TABLE, ["container_id", "created_at"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
