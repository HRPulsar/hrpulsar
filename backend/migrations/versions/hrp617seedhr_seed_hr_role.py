"""Seed the ``hr`` system role (HRP-617)

``hr`` is gated for across the product (recruitment reads, audit log,
invitations, ``ADMIN_ROLE_CODES``) but no such row ever existed in
``roles`` — every ``require_role(..., "hr")`` gate silently behaved as
admin-only. Seed it for real; the ``hrd`` code it replaces was never
seeded either, so there is nothing to migrate off.

Revision ID: hrp617seedhr
Revises: hrp612sortidx
Create Date: 2026-08-21 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "hrp617seedhr"
down_revision: str | None = "hrp612sortidx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO roles (id, name, code, description, is_system, tenant_id, created_at, updated_at)
        VALUES (
            gen_random_uuid(), 'HR', 'hr',
            'HR operations: employees, assessments, recruitment',
            true, NULL, now(), now()
        )
        ON CONFLICT (code) DO NOTHING
    """)

    # Same grant as ``manager`` in abe66531e6e4: read + write, no deletes
    # and no company/roles administration.
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.code = 'hr'
          AND p.codename NOT LIKE '%%.delete'
          AND p.codename NOT IN ('company.write', 'roles.write')
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM role_permissions
        WHERE role_id IN (SELECT id FROM roles WHERE code = 'hr')
    """)
    op.execute("DELETE FROM roles WHERE code = 'hr' AND is_system")
