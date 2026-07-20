"""HRP-360: vacancies.hiring_manager_id.

The responsible hiring manager (admin-tier user), separate from
``owner_id`` which records who created the vacancy. Backfill existing
rows from ``owner_id`` so active vacancies get a sensible default —
but only when the owner is an active admin-tier user, because the API
validates exactly that invariant on every explicit assignment and the
picker only offers such users (``platform_admin`` is inert in community
installs — the role simply has no members there).

Revision ID: hrp360hiringmgr
Revises: hrp328answeruniq
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "hrp360hiringmgr"
down_revision: str | None = "hrp328answeruniq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vacancies",
        sa.Column("hiring_manager_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_vacancies_hiring_manager_id",
        "vacancies",
        "users",
        ["hiring_manager_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_vacancies_hiring_manager_id", "vacancies", ["hiring_manager_id"]
    )
    op.execute("""
        UPDATE vacancies v
        SET hiring_manager_id = v.owner_id
        FROM users u
        WHERE u.id = v.owner_id
          AND u.is_active
          AND EXISTS (
            SELECT 1
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = u.id
              AND r.code IN ('admin', 'platform_admin')
          )
        """)


def downgrade() -> None:
    op.drop_index("ix_vacancies_hiring_manager_id", table_name="vacancies")
    op.drop_constraint(
        "fk_vacancies_hiring_manager_id", "vacancies", type_="foreignkey"
    )
    op.drop_column("vacancies", "hiring_manager_id")
