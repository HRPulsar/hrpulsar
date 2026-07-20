"""gf5_gf6_gf7_compensation_manager_spec_division

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-17 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # GF5: Compensation table
    op.create_table(
        "compensations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_compensations_tenant_id", "compensations", ["tenant_id"])
    op.create_index("ix_compensations_employee_id", "compensations", ["employee_id"])

    # GF6: Division manager
    op.add_column(
        "divisions",
        sa.Column(
            "manager_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_divisions_manager_id",
        "divisions",
        "employees",
        ["manager_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_divisions_manager_id", "divisions", ["manager_id"])

    # GF7: Specialization-Division mapping
    op.create_table(
        "specialization_divisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("division_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("specialization_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["division_id"], ["divisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["specialization_id"], ["dictionary_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "division_id", "specialization_id", name="uq_spec_div_tenant"
        ),
    )
    op.create_index(
        "ix_specialization_divisions_tenant_id",
        "specialization_divisions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_specialization_divisions_division_id",
        "specialization_divisions",
        ["division_id"],
    )


def downgrade() -> None:
    op.drop_table("specialization_divisions")
    op.drop_index("ix_divisions_manager_id", "divisions")
    op.drop_constraint("fk_divisions_manager_id", "divisions", type_="foreignkey")
    op.drop_column("divisions", "manager_id")
    op.drop_table("compensations")
