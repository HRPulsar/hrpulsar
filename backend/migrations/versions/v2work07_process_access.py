"""HRP-810: who reads and who edits a Coverage container.

``work_containers.visibility`` - ``company`` or ``restricted``; the
containers that exist today become ``company`` (only stands have any:
production gets Coverage with 2.0), a new one starts ``restricted``. A
container without an owner gets its creator. Two tables: the access rules
of a restricted container (a role, a position or an employee) and the log
of owner / visibility / rule changes.

Eleventh revision of the HRPulsar 2.0 chain (epic HRP-746, access epic
HRP-817). Downgrade drops both tables and the column; the owner backfill
stays.

Revision ID: v2work07
Revises: v2merge03
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v2work07"
down_revision: str | Sequence[str] | None = "v2merge03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RULES = "work_container_access_rules"
LOG = "work_container_access_log"


def _uuid(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def _pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _timestamp(name: str, default: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text(default),
        nullable=False,
    )


def upgrade() -> None:
    op.add_column(
        "work_containers",
        sa.Column(
            "visibility", sa.String(length=20), nullable=False, server_default="company"
        ),
    )
    op.alter_column("work_containers", "visibility", server_default="restricted")
    op.create_check_constraint(
        "ck_work_containers_visibility",
        "work_containers",
        "visibility IN ('company', 'restricted')",
    )
    op.execute(
        "UPDATE work_containers SET owner_id = created_by_id "
        "WHERE owner_id IS NULL AND created_by_id IS NOT NULL"
    )

    op.create_table(
        RULES,
        _pk(),
        _uuid("tenant_id"),
        _uuid("container_id"),
        sa.Column("role_code", sa.String(length=50), nullable=True),
        _uuid("position_id", nullable=True),
        _uuid("employee_id", nullable=True),
        _timestamp("created_at", "now()"),
        _timestamp("updated_at", "now()"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["container_id"], ["work_containers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["position_id"], ["positions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "num_nonnulls(role_code, position_id, employee_id) = 1",
            name="ck_work_access_rules_one_target",
        ),
        sa.CheckConstraint(
            "role_code IS NULL OR role_code IN "
            "('manager', 'recruiter', 'hiring_manager', 'employee')",
            name="ck_work_access_rules_role_code",
        ),
    )
    op.create_index(f"ix_{RULES}_tenant_id", RULES, ["tenant_id"])
    for kind, column in (
        ("role", "role_code"),
        ("position", "position_id"),
        ("employee", "employee_id"),
    ):
        op.create_index(
            f"ux_work_access_rules_{kind}",
            RULES,
            ["container_id", column],
            unique=True,
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )

    op.create_table(
        LOG,
        _pk(),
        _uuid("tenant_id"),
        _uuid("container_id"),
        _uuid("actor_id", nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # clock_timestamp(): the rows one save writes keep their order.
        _timestamp("created_at", "clock_timestamp()"),
        _timestamp("updated_at", "now()"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["container_id"], ["work_containers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "action IN ('owner_changed', 'visibility_changed', "
            "'rule_added', 'rule_removed')",
            name="ck_work_access_log_action",
        ),
    )
    op.create_index(f"ix_{LOG}_tenant_id", LOG, ["tenant_id"])
    op.create_index(
        "ix_work_access_log_container_created", LOG, ["container_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table(LOG)
    op.drop_table(RULES)
    op.drop_constraint(
        "ck_work_containers_visibility", "work_containers", type_="check"
    )
    op.drop_column("work_containers", "visibility")
