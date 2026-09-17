"""HRP-752: AI workforce registry — packs, agents, assignments, workflows,
audit log — and the seed of the nine built-in packs.

Third revision of the HRPulsar 2.0 chain (epic HRP-746). Additive; the
only dependency on earlier revisions is ``primitives.id`` (``v2prim01``),
referenced ON DELETE RESTRICT from the pack and agent link tables, so this
revision must be downgraded before ``v2prim01``:
``v2work02 -> v2work01 -> v2agnt01 -> v2prim02 -> v2prim01``.

Revision ID: v2agnt01
Revises: v2prim02
Create Date: 2026-09-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v2agnt01"
down_revision: str | Sequence[str] | None = "v2prim02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "ai_agent_packs",
        _uuid_pk(),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("title_en", sa.String(length=200), nullable=False),
        sa.Column("description_en", sa.String(length=600), nullable=True),
        sa.Column("i18n_key", sa.String(length=100), nullable=False),
        sa.Column("sort_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("code", "tenant_id", name="uq_agent_packs_code_tenant"),
    )
    op.create_index("ix_agent_packs_tenant", "ai_agent_packs", ["tenant_id"])
    op.create_index(
        "uq_agent_packs_builtin_code",
        "ai_agent_packs",
        ["code"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )

    op.create_table(
        "ai_agent_pack_primitives",
        _uuid_pk(),
        sa.Column("pack_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primitive_id", postgresql.UUID(as_uuid=True), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pack_id"], ["ai_agent_packs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["primitive_id"], ["primitives.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("pack_id", "primitive_id", name="uq_agent_pack_prim"),
    )
    op.create_index(
        "ix_agent_pack_prim_primitive", "ai_agent_pack_primitives", ["primitive_id"]
    )

    op.create_table(
        "ai_agents",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("vendor", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("homepage_url", sa.String(length=600), nullable=True),
        sa.Column("pack_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("seats_count", sa.Integer(), nullable=True),
        sa.Column("monthly_cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("cost_currency", sa.String(length=3), nullable=False),
        sa.Column("contract_renewal_date", sa.Date(), nullable=True),
        sa.Column(
            "data_classification",
            sa.String(length=20),
            server_default="internal",
            nullable=False,
        ),
        sa.Column(
            "security_review_status",
            sa.String(length=20),
            server_default="not_reviewed",
            nullable=False,
        ),
        sa.Column("security_review_date", sa.Date(), nullable=True),
        sa.Column("security_review_notes", sa.Text(), nullable=True),
        sa.Column(
            "eu_ai_act_risk_level",
            sa.String(length=20),
            server_default="minimal",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["pack_id"], ["ai_agent_packs.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ai_agents_tenant_name"),
        sa.CheckConstraint(
            "category IN ('chat', 'code', 'data', 'customer_outreach', "
            "'image', 'agent', 'other')",
            name="ck_ai_agents_category",
        ),
        sa.CheckConstraint(
            "data_classification IN ('public', 'internal', 'pii', "
            "'customer_data', 'financial')",
            name="ck_ai_agents_data_classification",
        ),
        sa.CheckConstraint(
            "security_review_status IN ('not_reviewed', 'in_review', "
            "'approved', 'rejected')",
            name="ck_ai_agents_security_review_status",
        ),
        sa.CheckConstraint(
            "eu_ai_act_risk_level IN ('minimal', 'limited', 'high', 'unacceptable')",
            name="ck_ai_agents_eu_ai_act_risk_level",
        ),
    )
    op.create_index("ix_ai_agents_tenant_id", "ai_agents", ["tenant_id"])
    op.create_index(
        "ix_ai_agents_tenant_active", "ai_agents", ["tenant_id", "is_active"]
    )
    op.create_index("ix_ai_agents_pack", "ai_agents", ["pack_id"])

    op.create_table(
        "ai_agent_primitives",
        _uuid_pk(),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primitive_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["ai_agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["primitive_id"], ["primitives.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("agent_id", "primitive_id", name="uq_agent_prim"),
        sa.CheckConstraint("mode IN ('add', 'remove')", name="ck_agent_prim_mode"),
    )

    op.create_table(
        "ai_usage_assignments",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allowed_use_cases", sa.Text(), nullable=False),
        sa.Column(
            "supervision_level",
            sa.String(length=30),
            server_default="human_review_required",
            nullable=False,
        ),
        sa.Column(
            "accountability_owner_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="active", nullable=False
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["ai_agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["accountability_owner_id"], ["employees.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'rejected', 'revoked')",
            name="ck_ai_assignments_status",
        ),
        sa.CheckConstraint(
            "supervision_level IN ('autonomous', 'human_review_required', "
            "'human_approval_gate')",
            name="ck_ai_assignments_supervision_level",
        ),
    )
    op.create_index(
        "ix_ai_usage_assignments_tenant_id", "ai_usage_assignments", ["tenant_id"]
    )
    op.create_index(
        "ix_ai_assignments_tenant_employee_status",
        "ai_usage_assignments",
        ["tenant_id", "employee_id", "status"],
    )
    op.create_index(
        "ix_ai_assignments_tenant_agent",
        "ai_usage_assignments",
        ["tenant_id", "agent_id"],
    )
    op.create_index(
        "ix_ai_assignments_tenant_owner",
        "ai_usage_assignments",
        ["tenant_id", "accountability_owner_id"],
    )
    op.create_index(
        "ix_ai_assignments_tenant_valid_until",
        "ai_usage_assignments",
        ["tenant_id", "valid_until"],
    )

    op.create_table(
        "ai_usage_assignment_competences",
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("competence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("assignment_id", "competence_id"),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["ai_usage_assignments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["competence_id"], ["competences.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_ai_assign_comp_competence",
        "ai_usage_assignment_competences",
        ["competence_id"],
    )

    op.create_table(
        "agent_workflows",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_type", sa.String(length=100), nullable=True),
        sa.Column("monthly_volume_estimate", sa.Integer(), nullable=True),
        sa.Column("error_rate_estimate", sa.Float(), nullable=True),
        sa.Column(
            "monthly_cost_estimate", sa.Numeric(precision=12, scale=2), nullable=True
        ),
        sa.Column("cost_currency", sa.String(length=3), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("human_role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["employees.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "human_role IN ('orchestrator', 'executor', 'reviewer', 'observer')",
            name="ck_agent_workflows_human_role",
        ),
    )
    op.create_index("ix_agent_workflows_tenant_id", "agent_workflows", ["tenant_id"])
    op.create_index(
        "ix_agent_workflows_tenant_active",
        "agent_workflows",
        ["tenant_id", "is_active"],
    )
    op.create_index(
        "ix_agent_workflows_tenant_owner", "agent_workflows", ["tenant_id", "owner_id"]
    )
    op.create_index(
        "ix_agent_workflows_tenant_human_role",
        "agent_workflows",
        ["tenant_id", "human_role"],
    )

    op.create_table(
        "ai_workforce_audit_log",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        # clock_timestamp(): rows written by one transaction keep their order.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "target_type IN ('ai_agent', 'ai_usage_assignment', 'agent_workflow')",
            name="ck_ai_wf_audit_target_type",
        ),
    )
    op.create_index(
        "ix_ai_workforce_audit_log_tenant_id", "ai_workforce_audit_log", ["tenant_id"]
    )
    op.create_index(
        "ix_ai_wf_audit_tenant_created",
        "ai_workforce_audit_log",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_ai_wf_audit_tenant_target",
        "ai_workforce_audit_log",
        ["tenant_id", "target_type", "target_id"],
    )
    op.create_index(
        "ix_ai_wf_audit_tenant_actor",
        "ai_workforce_audit_log",
        ["tenant_id", "actor_id"],
    )

    # Seed the nine built-in packs (decision O5). Same statements as
    # service.seed_packs; the import is local for the same reason as in
    # v2prim01 — graph-only alembic commands load this module without
    # env.py having put the app package on the path.
    from app.modules.ai_workforce.pack_data import seed_statements

    bind = op.get_bind()
    for stmt in seed_statements():
        bind.execute(stmt)


def downgrade() -> None:
    op.drop_index("ix_ai_wf_audit_tenant_actor", table_name="ai_workforce_audit_log")
    op.drop_index("ix_ai_wf_audit_tenant_target", table_name="ai_workforce_audit_log")
    op.drop_index("ix_ai_wf_audit_tenant_created", table_name="ai_workforce_audit_log")
    op.drop_index(
        "ix_ai_workforce_audit_log_tenant_id", table_name="ai_workforce_audit_log"
    )
    op.drop_table("ai_workforce_audit_log")
    op.drop_index("ix_agent_workflows_tenant_human_role", table_name="agent_workflows")
    op.drop_index("ix_agent_workflows_tenant_owner", table_name="agent_workflows")
    op.drop_index("ix_agent_workflows_tenant_active", table_name="agent_workflows")
    op.drop_index("ix_agent_workflows_tenant_id", table_name="agent_workflows")
    op.drop_table("agent_workflows")
    op.drop_index(
        "ix_ai_assign_comp_competence", table_name="ai_usage_assignment_competences"
    )
    op.drop_table("ai_usage_assignment_competences")
    op.drop_index(
        "ix_ai_assignments_tenant_valid_until", table_name="ai_usage_assignments"
    )
    op.drop_index("ix_ai_assignments_tenant_owner", table_name="ai_usage_assignments")
    op.drop_index("ix_ai_assignments_tenant_agent", table_name="ai_usage_assignments")
    op.drop_index(
        "ix_ai_assignments_tenant_employee_status", table_name="ai_usage_assignments"
    )
    op.drop_index(
        "ix_ai_usage_assignments_tenant_id", table_name="ai_usage_assignments"
    )
    op.drop_table("ai_usage_assignments")
    op.drop_table("ai_agent_primitives")
    op.drop_index("ix_ai_agents_pack", table_name="ai_agents")
    op.drop_index("ix_ai_agents_tenant_active", table_name="ai_agents")
    op.drop_index("ix_ai_agents_tenant_id", table_name="ai_agents")
    op.drop_table("ai_agents")
    op.drop_index("ix_agent_pack_prim_primitive", table_name="ai_agent_pack_primitives")
    op.drop_table("ai_agent_pack_primitives")
    op.drop_index("uq_agent_packs_builtin_code", table_name="ai_agent_packs")
    op.drop_index("ix_agent_packs_tenant", table_name="ai_agent_packs")
    op.drop_table("ai_agent_packs")
