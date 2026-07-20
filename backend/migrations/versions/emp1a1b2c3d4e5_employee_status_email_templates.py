"""Phase EMP1: seed employee status email templates

Revision ID: emp1a1b2c3d4e5
Revises: inv1a1b2c3d4e5
Create Date: 2026-05-05 13:00:00.000000

Seeds notification templates fired when an employee's `status` flips:
- employee_terminated   — active/inactive/on_leave -> terminated
- employee_inactive     — active/on_leave -> inactive
- employee_reactivated  — terminated/inactive -> active
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "emp1a1b2c3d4e5"
down_revision: str | None = "inv1a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO notification_templates
            (id, code, subject_template, body_template, notification_type,
             created_at, updated_at)
        VALUES
            (gen_random_uuid(),
             'employee_terminated',
             'Your employment has been terminated',
             '<p>Hi {{ employee_name }},</p>'
             '<p>Your employment has been marked as <b>terminated</b>. '
             'You no longer have access to the system.</p>'
             '<p>If you believe this is a mistake, contact your administrator.</p>',
             'email', now(), now()),
            (gen_random_uuid(),
             'employee_inactive',
             'Your account has been deactivated',
             '<p>Hi {{ employee_name }},</p>'
             '<p>Your account has been marked as <b>inactive</b>. '
             'Sign-in is disabled while this status is in effect.</p>'
             '<p>Contact your administrator with any questions.</p>',
             'email', now(), now()),
            (gen_random_uuid(),
             'employee_reactivated',
             'Your account has been reactivated',
             '<p>Hi {{ employee_name }},</p>'
             '<p>Your account is <b>active</b> again — you can sign in '
             'and resume working in the system.</p>',
             'email', now(), now())
        ON CONFLICT (code) DO NOTHING
        """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM notification_templates WHERE code IN "
        "('employee_terminated','employee_inactive','employee_reactivated')"
    )
