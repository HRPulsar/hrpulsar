"""HRP-221: widen compensations.amount to BIGINT.

The column stores money in minor units (cents). INT32_MAX is roughly
$21.4M, which a single bonus or annual gross can exceed once an operator
enters figures denominated in JPY/IDR/COP or simply pays out shares. The
asyncpg encoder raises OverflowError before the INSERT ever reaches
PostgreSQL, surfacing as a 500 with no friendly message.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp221amount01"
down_revision: str | None = "hrp170redo01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "compensations",
        "amount",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Forward-only in practice. PostgreSQL refuses BIGINT→INTEGER on rows
    # whose value exceeds INT32_MAX (~$21.4M in minor units); if the
    # upgrade has been live long enough to attract one such payout,
    # downgrade requires either deleting/clamping those rows by hand or
    # restoring from backup. Kept here so alembic graph stays bidirectional.
    op.alter_column(
        "compensations",
        "amount",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
