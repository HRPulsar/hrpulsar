"""HRP-754: work containers, steps, step ↔ primitive links and AI
decomposition sessions (module ``work``).

Fourth revision of the HRPulsar 2.0 chain (epic HRP-746). Additive.
``work_step_primitives`` references ``primitives.id`` (``v2prim01``) ON
DELETE RESTRICT, so this revision must be downgraded before ``v2prim01``:
``v2work02 -> v2work01 -> v2agnt01 -> v2prim02 -> v2prim01``.

Revision ID: v2work01
Revises: v2agnt01
Create Date: 2026-09-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v2work01"
down_revision: str | Sequence[str] | None = "v2agnt01"
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
        "work_containers",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="draft", nullable=False
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "source", sa.String(length=20), server_default="manual", nullable=False
        ),
        sa.Column("catalog_version", sa.String(length=20), nullable=False),
        sa.Column(
            "gap_default_label",
            sa.String(length=10),
            server_default="hire",
            nullable=False,
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "type IN ('initiative', 'process')", name="ck_work_containers_type"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_work_containers_status",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'ai')", name="ck_work_containers_source"
        ),
        sa.CheckConstraint(
            "gap_default_label IN ('hire', 'agency')",
            name="ck_work_containers_gap_default_label",
        ),
    )
    op.create_index("ix_work_containers_tenant_id", "work_containers", ["tenant_id"])
    op.create_index(
        "ix_work_containers_tenant_status", "work_containers", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_work_containers_tenant_type", "work_containers", ["tenant_id", "type"]
    )

    op.create_table(
        "work_steps",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("container_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "responsibility",
            sa.String(length=20),
            server_default="none",
            nullable=False,
        ),
        sa.Column("reversibility", sa.String(length=20), nullable=True),
        sa.Column("frequency", sa.String(length=10), nullable=True),
        sa.Column("effort", sa.String(length=10), nullable=True),
        sa.Column(
            "output_type", sa.String(length=20), server_default="draft", nullable=False
        ),
        sa.Column(
            "state",
            sa.String(length=20),
            server_default="system_suggested",
            nullable=False,
        ),
        sa.Column("gap_label", sa.String(length=10), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["container_id"], ["work_containers.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "responsibility IN ('none', 'reputational', 'formal', 'regulatory')",
            name="ck_work_steps_responsibility",
        ),
        sa.CheckConstraint(
            "reversibility IS NULL OR reversibility IN "
            "('reversible', 'costly', 'irreversible')",
            name="ck_work_steps_reversibility",
        ),
        sa.CheckConstraint(
            "frequency IS NULL OR frequency IN ('high', 'medium', 'low')",
            name="ck_work_steps_frequency",
        ),
        sa.CheckConstraint(
            "effort IS NULL OR effort IN ('high', 'medium', 'low')",
            name="ck_work_steps_effort",
        ),
        sa.CheckConstraint(
            "output_type IN ('draft', 'external_change')",
            name="ck_work_steps_output_type",
        ),
        sa.CheckConstraint(
            "state IN ('system_suggested', 'tenant_edited', 'accepted')",
            name="ck_work_steps_state",
        ),
        sa.CheckConstraint(
            "gap_label IS NULL OR gap_label IN ('hire', 'agency')",
            name="ck_work_steps_gap_label",
        ),
    )
    op.create_index("ix_work_steps_tenant_id", "work_steps", ["tenant_id"])
    op.create_index(
        "ix_work_steps_container_position", "work_steps", ["container_id", "position"]
    )

    op.create_table(
        "work_step_primitives",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primitive_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["work_steps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["primitive_id"], ["primitives.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("step_id", "primitive_id", name="uq_work_step_prim"),
        sa.CheckConstraint(
            "source IN ('system_suggested', 'tenant_edited')",
            name="ck_work_step_prim_source",
        ),
    )
    op.create_index(
        "ix_work_step_primitives_tenant_id", "work_step_primitives", ["tenant_id"]
    )
    op.create_index(
        "ix_work_step_prim_primitive", "work_step_primitives", ["primitive_id"]
    )

    op.create_table(
        "work_decomposition_sessions",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("container_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "base_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_idempotency_key", sa.String(length=100), nullable=True),
        sa.Column(
            "applied_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["container_id"], ["work_containers.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'ready', 'error', 'applied', "
            "'cancelled')",
            name="ck_workdecomp_status",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN ('service_error', 'overload', "
            "'insufficient_data', 'parse_error', 'reaped_stuck', 'output_truncated')",
            name="ck_workdecomp_error_code",
        ),
    )
    op.create_index(
        "ix_work_decomposition_sessions_tenant_id",
        "work_decomposition_sessions",
        ["tenant_id"],
    )
    op.create_index("ix_workdecomp_status", "work_decomposition_sessions", ["status"])
    op.create_index(
        "ux_workdecomp_one_active_per_container",
        "work_decomposition_sessions",
        ["container_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running', 'ready')"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_workdecomp_one_active_per_container",
        table_name="work_decomposition_sessions",
    )
    op.drop_index("ix_workdecomp_status", table_name="work_decomposition_sessions")
    op.drop_index(
        "ix_work_decomposition_sessions_tenant_id",
        table_name="work_decomposition_sessions",
    )
    op.drop_table("work_decomposition_sessions")
    op.drop_index("ix_work_step_prim_primitive", table_name="work_step_primitives")
    op.drop_index(
        "ix_work_step_primitives_tenant_id", table_name="work_step_primitives"
    )
    op.drop_table("work_step_primitives")
    op.drop_index("ix_work_steps_container_position", table_name="work_steps")
    op.drop_index("ix_work_steps_tenant_id", table_name="work_steps")
    op.drop_table("work_steps")
    op.drop_index("ix_work_containers_tenant_type", table_name="work_containers")
    op.drop_index("ix_work_containers_tenant_status", table_name="work_containers")
    op.drop_index("ix_work_containers_tenant_id", table_name="work_containers")
    op.drop_table("work_containers")
