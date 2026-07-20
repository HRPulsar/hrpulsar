"""Add token_version to users for refresh-token revocation

Access/refresh JWTs carry a ``ver`` claim matched against ``users.token_version``.
Bumping the column (on password change/reset) invalidates every token issued
earlier — closing the window where a leaked refresh token stayed valid for its
full 7-day TTL after a password change (review P1-12).

Revision ID: addusertokenversion
Revises: dropaigencostcredits
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "addusertokenversion"
down_revision: str | None = "dropaigencostcredits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
