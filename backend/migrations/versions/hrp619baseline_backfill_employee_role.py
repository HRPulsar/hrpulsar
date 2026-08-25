"""Backfill the baseline ``employee`` role (HRP-619)

Nothing guaranteed the baseline role on user creation, so accounts made
before the invitation flow — and every demo-seeded user — carried an
empty role list. Permissions still resolved ("own data only" is the
fallback), but the UI had no role to render and role-gated menus made
their own guesses.

Revision ID: hrp619baseline
Revises: hrp617seedhr
Create Date: 2026-08-21 11:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "hrp619baseline"
down_revision: str | None = "hrp617seedhr"
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
            SELECT 1 FROM user_roles ur WHERE ur.user_id = u.id
        )
    """)


def downgrade() -> None:
    # Not reversible: the backfilled rows are indistinguishable from the
    # baseline roles the product grants on every new account.
    pass
