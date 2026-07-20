"""Phase CR1: competence library rework — model fields + audit log

Revision ID: cr1a0b1c2d3e4
Revises: f3a4b5c6d7e8
Create Date: 2026-04-30 22:00:00.000000

Adds the foundation for Phase CR (competence library rework + AI generation):

* ``competences.is_published`` — explicit publication flag for client-created
  competences (PM spec: a new competence is created in unpublished state and
  must be explicitly published). Existing client competences are backfilled
  to ``TRUE`` to preserve current behavior.
* ``competence_groups.can_deactivate`` — superadmin flag controlling whether
  an origin group can be hidden by tenants. Origin groups default to
  ``FALSE`` (locked). Existing client groups are backfilled to ``TRUE``.
* ``skill_levels.tenant_id`` / ``i18n_key`` / ``is_active`` — per-tenant
  custom skill levels (PM spec note #1). Origin levels keep
  ``tenant_id IS NULL``; ``i18n_key`` is backfilled from lowercase title.
* ``materials.comment`` / ``material_type`` — product spec for the
  competence admin page adds a comment field (≤350 chars) and a material
  type select (theoretical / practical / feedback).
* ``competence_tree_audit_log`` — captures every mutation of the tree for
  the «date, time, author» log on the competence library page and for
  AI-generation apply records (CR11).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cr1a0b1c2d3e4"
down_revision: str | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- competences.is_published ---
    op.add_column(
        "competences",
        sa.Column(
            "is_published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute("UPDATE competences SET is_published = TRUE WHERE tenant_id IS NOT NULL")

    # --- competence_groups.can_deactivate ---
    op.add_column(
        "competence_groups",
        sa.Column(
            "can_deactivate",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute(
        "UPDATE competence_groups SET can_deactivate = TRUE WHERE tenant_id IS NOT NULL"
    )

    # --- skill_levels: tenant_id, i18n_key, is_active ---
    op.add_column(
        "skill_levels",
        sa.Column("i18n_key", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "skill_levels",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "skill_levels",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_skill_levels_tenant_id",
        "skill_levels",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_skill_levels_tenant_id", "skill_levels", ["tenant_id"])
    op.create_index(
        "ix_skill_levels_tenant_sort",
        "skill_levels",
        ["tenant_id", "sort_index"],
    )

    # Backfill i18n_key for the three seeded origin levels
    op.execute(
        "UPDATE skill_levels SET i18n_key = LOWER(title) "
        "WHERE i18n_key IS NULL AND tenant_id IS NULL"
    )

    # --- materials: comment, material_type ---
    op.add_column(
        "materials",
        sa.Column("comment", sa.String(length=350), nullable=True),
    )
    op.add_column(
        "materials",
        sa.Column("material_type", sa.String(length=50), nullable=True),
    )

    # --- competence_tree_audit_log ---
    op.create_table(
        "competence_tree_audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("element_type", sa.String(length=50), nullable=True),
        sa.Column("element_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
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
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_competence_tree_audit_log_tenant_id",
        "competence_tree_audit_log",
        ["tenant_id"],
    )
    op.create_index(
        "ix_competence_tree_audit_log_actor_id",
        "competence_tree_audit_log",
        ["actor_id"],
    )
    op.create_index(
        "ix_competence_tree_audit_log_action",
        "competence_tree_audit_log",
        ["action"],
    )
    op.create_index(
        "ix_competence_tree_audit_log_element_id",
        "competence_tree_audit_log",
        ["element_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_competence_tree_audit_log_element_id",
        table_name="competence_tree_audit_log",
    )
    op.drop_index(
        "ix_competence_tree_audit_log_action",
        table_name="competence_tree_audit_log",
    )
    op.drop_index(
        "ix_competence_tree_audit_log_actor_id",
        table_name="competence_tree_audit_log",
    )
    op.drop_index(
        "ix_competence_tree_audit_log_tenant_id",
        table_name="competence_tree_audit_log",
    )
    op.drop_table("competence_tree_audit_log")

    op.drop_column("materials", "material_type")
    op.drop_column("materials", "comment")

    op.drop_index("ix_skill_levels_tenant_sort", table_name="skill_levels")
    op.drop_index("ix_skill_levels_tenant_id", table_name="skill_levels")
    op.drop_constraint("fk_skill_levels_tenant_id", "skill_levels", type_="foreignkey")
    op.drop_column("skill_levels", "tenant_id")
    op.drop_column("skill_levels", "is_active")
    op.drop_column("skill_levels", "i18n_key")

    op.drop_column("competence_groups", "can_deactivate")
    op.drop_column("competences", "is_published")
