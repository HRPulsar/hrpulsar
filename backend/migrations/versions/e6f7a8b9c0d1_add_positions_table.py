"""add_positions_table

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-04-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create positions table
    op.create_table(
        "positions",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("specialization_id", sa.UUID(), nullable=True),
        sa.Column("grade_id", sa.UUID(), nullable=True),
        sa.Column("division_id", sa.UUID(), nullable=True),
        sa.Column("headcount", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "source", sa.String(length=20), server_default="manual", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["specialization_id"], ["dictionary_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["grade_id"], ["dictionary_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["division_id"], ["divisions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "title", name="uq_position_tenant_title"),
    )
    op.create_index(op.f("ix_positions_tenant_id"), "positions", ["tenant_id"])

    # 2. Add position_id to employees
    op.add_column("employees", sa.Column("position_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_employees_position_id"), "employees", ["position_id"])
    op.create_foreign_key(
        "fk_employees_position_id",
        "employees",
        "positions",
        ["position_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. Rename employees.position -> employees.position_title, make nullable
    op.alter_column(
        "employees", "position", new_column_name="position_title", nullable=True
    )

    # 4. Data migration: create Position records from distinct position_title values
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO positions (tenant_id, title, source)
        SELECT DISTINCT tenant_id, position_title, 'manual'
        FROM employees
        WHERE position_title IS NOT NULL AND position_title != ''
        ON CONFLICT (tenant_id, title) DO NOTHING
    """))

    # 5. Link employees to their positions
    conn.execute(sa.text("""
        UPDATE employees e
        SET position_id = p.id
        FROM positions p
        WHERE e.tenant_id = p.tenant_id
          AND e.position_title = p.title
          AND e.position_id IS NULL
    """))

    # 6. Add position_id to invitations, drop old position column
    op.add_column("invitations", sa.Column("position_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_invitations_position_id",
        "invitations",
        "positions",
        ["position_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_column("invitations", "position")


def downgrade() -> None:
    conn = op.get_bind()

    # Invitations: restore position text column
    op.add_column("invitations", sa.Column("position", sa.String(255), nullable=True))

    # Backfill invitation position text from positions table before dropping FK
    conn.execute(sa.text("""
        UPDATE invitations i
        SET position = p.title
        FROM positions p
        WHERE i.position_id = p.id
    """))

    op.drop_constraint("fk_invitations_position_id", "invitations", type_="foreignkey")
    op.drop_column("invitations", "position_id")

    # Employees: rename position_title back to position, drop position_id
    op.drop_constraint("fk_employees_position_id", "employees", type_="foreignkey")
    op.drop_index(op.f("ix_employees_position_id"), table_name="employees")
    op.drop_column("employees", "position_id")

    # Backfill NULL position_title before renaming to non-nullable column
    conn.execute(
        sa.text(
            "UPDATE employees SET position_title = 'Employee' WHERE position_title IS NULL"
        )
    )

    op.alter_column(
        "employees", "position_title", new_column_name="position", nullable=False
    )

    # Drop positions table
    op.drop_index(op.f("ix_positions_tenant_id"), table_name="positions")
    op.drop_table("positions")
