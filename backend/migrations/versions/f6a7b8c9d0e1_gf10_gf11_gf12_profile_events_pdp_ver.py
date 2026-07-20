"""GF10 GF11 GF12: company profile, employee event changes, PDP versioning

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-18 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- GF10: Company profile fields on tenants ---
    op.add_column("tenants", sa.Column("industry", sa.String(255), nullable=True))
    op.add_column("tenants", sa.Column("company_size", sa.String(50), nullable=True))
    op.add_column("tenants", sa.Column("website", sa.String(500), nullable=True))
    op.add_column("tenants", sa.Column("description", sa.Text(), nullable=True))

    # --- GF10: Company activity fields (many-to-many with dictionary_items) ---
    op.create_table(
        "company_activity_fields",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("activity_field_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["activity_field_id"], ["dictionary_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "activity_field_id", name="uq_company_activity_field"
        ),
    )
    op.create_index(
        "ix_company_activity_fields_tenant_id", "company_activity_fields", ["tenant_id"]
    )

    # --- GF11: Add old_value/new_value to employee_events ---
    op.add_column(
        "employee_events", sa.Column("old_value", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "employee_events", sa.Column("new_value", postgresql.JSONB(), nullable=True)
    )
    op.create_index("ix_employee_events_event_type", "employee_events", ["event_type"])

    # --- GF12: PDP versions ---
    op.create_table(
        "pdp_versions",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("pdp_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["pdp_id"], ["pdps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pdp_versions_pdp_id", "pdp_versions", ["pdp_id"])


def downgrade() -> None:
    op.drop_table("pdp_versions")
    op.drop_index("ix_employee_events_event_type", table_name="employee_events")
    op.drop_column("employee_events", "new_value")
    op.drop_column("employee_events", "old_value")
    op.drop_table("company_activity_fields")
    op.drop_column("tenants", "description")
    op.drop_column("tenants", "website")
    op.drop_column("tenants", "company_size")
    op.drop_column("tenants", "industry")
