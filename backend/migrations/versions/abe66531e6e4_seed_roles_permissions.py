"""seed_roles_permissions

Revision ID: abe66531e6e4
Revises: ab6347d21c01
Create Date: 2026-04-14 21:29:13.589241
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "abe66531e6e4"
down_revision: str | None = "ab6347d21c01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # System roles
    op.execute("""
        INSERT INTO roles (id, name, code, description, is_system, tenant_id, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'Admin', 'admin', 'Full system access', true, NULL, now(), now()),
            (gen_random_uuid(), 'Manager', 'manager', 'Department management access', true, NULL, now(), now()),
            (gen_random_uuid(), 'Employee', 'employee', 'Basic employee access', true, NULL, now(), now())
    """)

    # Permissions
    op.execute("""
        INSERT INTO permissions (id, codename, description, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'company.read', 'View company settings', now(), now()),
            (gen_random_uuid(), 'company.write', 'Edit company settings', now(), now()),
            (gen_random_uuid(), 'divisions.read', 'View divisions', now(), now()),
            (gen_random_uuid(), 'divisions.write', 'Create/edit divisions', now(), now()),
            (gen_random_uuid(), 'divisions.delete', 'Delete divisions', now(), now()),
            (gen_random_uuid(), 'employees.read', 'View employees', now(), now()),
            (gen_random_uuid(), 'employees.write', 'Create/edit employees', now(), now()),
            (gen_random_uuid(), 'employees.delete', 'Delete employees', now(), now()),
            (gen_random_uuid(), 'roles.read', 'View roles', now(), now()),
            (gen_random_uuid(), 'roles.write', 'Create/edit roles', now(), now()),
            (gen_random_uuid(), 'roles.delete', 'Delete roles', now(), now())
    """)

    # Admin gets all permissions
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.code = 'admin'
    """)

    # Manager gets read + write (no delete)
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.code = 'manager'
          AND p.codename NOT LIKE '%%.delete'
          AND p.codename NOT IN ('company.write', 'roles.write')
    """)

    # Employee gets read-only
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.code = 'employee'
          AND p.codename LIKE '%%.read'
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions")
    op.execute("DELETE FROM permissions")
    op.execute("DELETE FROM roles WHERE is_system = true")
