"""HRP-202 REDO: interviews.auto_process flag for upload -> transcribe -> analyze chain.

Revision ID: hrp202redo01
Revises: hrp205redo01
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from alembic import op

revision: str = "hrp202redo01"
down_revision: str | None = "hrp205redo01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "interviews",
        sa.Column(
            "auto_process",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("interviews", "auto_process")
