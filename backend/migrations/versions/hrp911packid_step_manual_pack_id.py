"""A step's manual agent pack by id, HRP-911

Revision ID: hrp911packid
Revises: hrp922pubcheck
Create Date: 2026-10-02 22:00:00.000000

``work_steps.manual_pack_id`` replaces ``manual_pack_code`` (HRP-863): a code
cannot tell the tenant's own pack from a built-in one of the same code, and
the lookup by code always landed on the built-in one.

The backfill resolves each stored code among the packs the step's tenant
sees: an active pack before a deactivated one - what the code resolves to
today keeps resolving - then the tenant's own before the built-in one. A code
no visible pack carries any more leaves the id NULL: the step reads as
without an override, as it already did.

``ON DELETE SET NULL``: a deleted pack drops the override and the step goes
back to the computed match. Indexed, so that delete - a tenant purge deletes
its packs by cascade - finds the steps without scanning ``work_steps``.

``manual_pack_code`` stays for one release, unread and unwritten: the previous
release's containers still select it while the deploy migrates ahead of the
swap (the HRP-832 / HRP-973 pattern). The next migration drops it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "hrp911packid"
down_revision: str | Sequence[str] | None = "hrp922pubcheck"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL_SQL = """
UPDATE work_steps AS s
SET manual_pack_id = (
    SELECT p.id
    FROM ai_agent_packs AS p
    WHERE p.code = s.manual_pack_code
      AND (p.tenant_id = s.tenant_id OR p.tenant_id IS NULL)
    ORDER BY p.is_active DESC, p.tenant_id IS NULL
    LIMIT 1
)
WHERE s.manual_pack_code IS NOT NULL
"""

# Downgrade: the code of the pack the step names now - an override set or
# cleared after the upgrade never reached the old column.
RESTORE_SQL = """
UPDATE work_steps AS s
SET manual_pack_code = (
    SELECT p.code FROM ai_agent_packs AS p WHERE p.id = s.manual_pack_id
)
WHERE s.manual_pack_code IS NOT NULL OR s.manual_pack_id IS NOT NULL
"""


def upgrade() -> None:
    op.add_column(
        "work_steps",
        sa.Column(
            "manual_pack_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai_agent_packs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_work_steps_manual_pack_id", "work_steps", ["manual_pack_id"])
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    op.execute(RESTORE_SQL)
    op.drop_index("ix_work_steps_manual_pack_id", table_name="work_steps")
    op.drop_column("work_steps", "manual_pack_id")
