"""HRP-759 / HRP-760: hire needs (the gap → Recruitment handoff) and the
generated ``SKILL.md`` of a step (module ``work``).

Fifth revision of the HRPulsar 2.0 chain (epic HRP-746). Additive.
``work_hire_needs.vacancy_id`` points into ``recruitment`` (ON DELETE SET
NULL) — the dependency runs ``work → recruitment``, never back.
Downgrade order: ``v2work02 -> v2work01 -> v2agnt01 -> v2prim02 -> v2prim01``.

Revision ID: v2work02
Revises: v2work01
Create Date: 2026-09-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v2work02"
down_revision: str | Sequence[str] | None = "v2work01"
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
        "work_hire_needs",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("container_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vacancy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "step_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("label", sa.String(length=10), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["container_id"], ["work_containers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["vacancy_id"], ["vacancies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "label IN ('hire', 'agency')", name="ck_work_hire_needs_label"
        ),
    )
    op.create_index("ix_work_hire_needs_tenant_id", "work_hire_needs", ["tenant_id"])
    op.create_index("ix_work_hire_needs_container", "work_hire_needs", ["container_id"])
    op.create_index("ix_work_hire_needs_vacancy", "work_hire_needs", ["vacancy_id"])

    op.create_table(
        "work_step_skills",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pack_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("skill_name", sa.String(length=100), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="generating",
            nullable=False,
        ),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("prompt_version", sa.String(length=40), nullable=True),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("generated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("catalog_version", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["work_steps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["pack_id"], ["ai_agent_packs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["generated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("step_id", name="uq_work_step_skills_step"),
        sa.CheckConstraint(
            "status IN ('generating', 'ready', 'failed')",
            name="ck_work_step_skills_status",
        ),
    )
    op.create_index("ix_work_step_skills_tenant_id", "work_step_skills", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_work_step_skills_tenant_id", table_name="work_step_skills")
    op.drop_table("work_step_skills")
    op.drop_index("ix_work_hire_needs_vacancy", table_name="work_hire_needs")
    op.drop_index("ix_work_hire_needs_container", table_name="work_hire_needs")
    op.drop_index("ix_work_hire_needs_tenant_id", table_name="work_hire_needs")
    op.drop_table("work_hire_needs")
