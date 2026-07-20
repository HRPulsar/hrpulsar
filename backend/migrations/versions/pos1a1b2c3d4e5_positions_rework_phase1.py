"""Phase POS1: Position lifecycle, Spec×Grade attrs, material overrides

Revision ID: pos1a1b2c3d4e5
Revises: cr12s1y2s3t4c5
Create Date: 2026-05-04 12:00:00.000000

Adds the schema groundwork for the Positions Rework phase:

* `positions.lifecycle_status` (varchar(20), default 'active', CHECK enum
  active|on_hold|frozen|closed) replaces the binary `is_active` semantics
  for the new UI. `is_active` stays for backwards compatibility and is
  backfilled into `lifecycle_status` (`True → active`, `False → frozen`).
* `grade_specializations` gains `requirements` (Text), salary range
  (`salary_min`, `salary_max`, `salary_currency` default `RUB`) and a
  range CHECK; `description` widens from `String(600)` to `Text` to
  match the requirements field.
* `material_specialization_overrides` is a new table that powers the
  two-level material model — base materials on the competence + per
  `(material × specialization)` add/hide overrides for context-specific
  materials in PDPs.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "pos1a1b2c3d4e5"
down_revision = "cr12s1y2s3t4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Position lifecycle status ---
    op.add_column(
        "positions",
        sa.Column(
            "lifecycle_status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
    )
    op.execute(
        "UPDATE positions SET lifecycle_status = "
        "CASE WHEN is_active THEN 'active' ELSE 'frozen' END"
    )
    op.create_check_constraint(
        "ck_position_lifecycle_status",
        "positions",
        "lifecycle_status IN ('active','on_hold','frozen','closed')",
    )

    # --- GradeSpecialization: description → Text + requirements + salary ---
    op.alter_column(
        "grade_specializations",
        "description",
        existing_type=sa.String(length=600),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.add_column(
        "grade_specializations",
        sa.Column("requirements", sa.Text(), nullable=True),
    )
    op.add_column(
        "grade_specializations",
        sa.Column("salary_min", sa.Integer(), nullable=True),
    )
    op.add_column(
        "grade_specializations",
        sa.Column("salary_max", sa.Integer(), nullable=True),
    )
    op.add_column(
        "grade_specializations",
        sa.Column(
            "salary_currency",
            sa.String(length=3),
            nullable=False,
            server_default="RUB",
        ),
    )
    op.create_check_constraint(
        "ck_grade_spec_salary_range",
        "grade_specializations",
        "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
    )

    # --- material_specialization_overrides ---
    op.create_table(
        "material_specialization_overrides",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
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
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "material_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("materials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "specialization_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dictionary_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "material_id",
            "specialization_id",
            "mode",
            name="uq_material_spec_override",
        ),
    )
    op.create_index(
        "ix_material_spec_override_tenant",
        "material_specialization_overrides",
        ["tenant_id"],
    )
    op.create_index(
        "ix_material_spec_override_material",
        "material_specialization_overrides",
        ["material_id"],
    )
    op.create_index(
        "ix_material_spec_override_specialization",
        "material_specialization_overrides",
        ["specialization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_material_spec_override_specialization",
        table_name="material_specialization_overrides",
    )
    op.drop_index(
        "ix_material_spec_override_material",
        table_name="material_specialization_overrides",
    )
    op.drop_index(
        "ix_material_spec_override_tenant",
        table_name="material_specialization_overrides",
    )
    op.drop_table("material_specialization_overrides")

    op.drop_constraint(
        "ck_grade_spec_salary_range", "grade_specializations", type_="check"
    )
    op.drop_column("grade_specializations", "salary_currency")
    op.drop_column("grade_specializations", "salary_max")
    op.drop_column("grade_specializations", "salary_min")
    op.drop_column("grade_specializations", "requirements")
    op.alter_column(
        "grade_specializations",
        "description",
        existing_type=sa.Text(),
        type_=sa.String(length=600),
        existing_nullable=True,
    )

    op.drop_constraint("ck_position_lifecycle_status", "positions", type_="check")
    op.drop_column("positions", "lifecycle_status")
