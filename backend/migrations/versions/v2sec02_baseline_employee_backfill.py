"""HRP-832: every account holds the ``employee`` baseline.

HRP-619 backfilled accounts that held no role at all and left the
creation paths as they were: signup granted ``admin`` alone, accepting an
invitation granted the invited role alone, and setting a role replaced
every tenant role with the one requested. The code grants the baseline on
each of those paths now; this revision adds it to every account created
in between. Idempotent.

Revision ID: v2sec02
Revises: v2merge05ar
Create Date: 2026-09-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "v2sec02"
down_revision: str | Sequence[str] | None = "v2merge05ar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO user_roles (user_id, role_id)
        SELECT u.id, r.id
        FROM users u
        CROSS JOIN (
            SELECT id FROM roles WHERE code = 'employee' AND is_system LIMIT 1
        ) r
        WHERE NOT EXISTS (
            SELECT 1 FROM user_roles ur
            WHERE ur.user_id = u.id AND ur.role_id = r.id
        )
    """)


def downgrade() -> None:
    # Not reversible: the backfilled rows are indistinguishable from the
    # baseline the product grants on every new account.
    pass
