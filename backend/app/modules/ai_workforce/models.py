"""AI workforce registry (HRP-752): agent packs, registered agents, who may
use them for what, the automated workflows they run in, and an audit trail.

A *pack* is a class of agents that covers a fixed set of capability
primitives. Coverage (REFACTOR_PLAN §5) counts agent capability by pack,
not by registered agent, so an empty tenant still gets an "agent" verdict
on the steps a pack covers. Built-in packs have ``tenant_id IS NULL`` and
are seeded by migration ``v2agnt01`` from ``pack_data.PACKS``; no pack ever
declares P6 / P7 / P8 or a boundary code (§2.4) — that is what keeps the
matching rule ``step.primitives ⊆ pack.primitives`` a single line.

An *agent* is the single Agent ↔ AITool entity of the AI workforce plan
(§3.3.1): a registered tool with its contract and compliance data.
``AIAgentPrimitive`` widens or narrows an agent's capabilities against its
pack (``add`` / ``remove``) — the same base-plus-delta pattern as
``MaterialSpecializationOverride``. Assignments, workflows and the audit log
are the full AR1–AR3 scope (decision O4, 2026-08-31). Enumerations are
plain strings with CHECK constraints, as everywhere else in the schema.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.currency import installation_currency
from app.models import BaseModel, TenantMixin

AGENT_CATEGORIES = (
    "chat",
    "code",
    "data",
    "customer_outreach",
    "image",
    "agent",
    "other",
)
DATA_CLASSIFICATIONS = ("public", "internal", "pii", "customer_data", "financial")
SECURITY_REVIEW_STATUSES = ("not_reviewed", "in_review", "approved", "rejected")
EU_AI_ACT_RISK_LEVELS = ("minimal", "limited", "high", "unacceptable")
PRIMITIVE_OVERRIDE_MODES = ("add", "remove")
SUPERVISION_LEVELS = ("autonomous", "human_review_required", "human_approval_gate")
# pending: self-service request awaiting approval; the other three are final
# for the row — a revoked or rejected assignment is re-created, not revived.
ASSIGNMENT_STATUSES = ("pending", "active", "rejected", "revoked")
# The person's part in a workflow (conductor vs. violinist), not an RBAC role:
# the name stays clear of the *_ROLES suffix test_rbac_role_codes.py scans.
HUMAN_ROLE_KINDS = ("orchestrator", "executor", "reviewer", "observer")
AUDIT_TARGET_TYPES = ("ai_agent", "ai_usage_assignment", "agent_workflow")


class AIAgentPack(BaseModel):
    __tablename__ = "ai_agent_packs"
    __table_args__ = (
        UniqueConstraint("code", "tenant_id", name="uq_agent_packs_code_tenant"),
        # NULLs are distinct in a UNIQUE, so built-ins need their own guard;
        # the seed's ON CONFLICT targets this index.
        Index(
            "uq_agent_packs_builtin_code",
            "code",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
        Index("ix_agent_packs_tenant", "tenant_id"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    # English is the render fallback; the frontend resolves
    # reference.agentPack.<i18n_key>.{label,description}.
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    description_en: Mapped[str | None] = mapped_column(String(600), nullable=True)
    i18n_key: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # NULL = built-in, shipped with the platform; a uuid = the tenant's own.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )


class AIAgentPackPrimitive(BaseModel):
    __tablename__ = "ai_agent_pack_primitives"
    __table_args__ = (
        UniqueConstraint("pack_id", "primitive_id", name="uq_agent_pack_prim"),
        Index("ix_agent_pack_prim_primitive", "primitive_id"),
    )

    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agent_packs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # RESTRICT: the catalog is never deleted, only retired.
    primitive_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("primitives.id", ondelete="RESTRICT"),
        nullable=False,
    )


class AIAgent(BaseModel, TenantMixin):
    __tablename__ = "ai_agents"
    __table_args__ = (
        # Functional, because ``_ensure_name_free`` compares lower(name):
        # a plain (tenant_id, name) constraint would let "ChatGPT" and
        # "chatgpt" both through the pre-check and both commit.
        Index(
            "uq_ai_agents_tenant_name_lower",
            "tenant_id",
            text("lower(name)"),
            unique=True,
        ),
        CheckConstraint(
            f"category IN {AGENT_CATEGORIES!r}", name="ck_ai_agents_category"
        ),
        CheckConstraint(
            f"data_classification IN {DATA_CLASSIFICATIONS!r}",
            name="ck_ai_agents_data_classification",
        ),
        CheckConstraint(
            f"security_review_status IN {SECURITY_REVIEW_STATUSES!r}",
            name="ck_ai_agents_security_review_status",
        ),
        CheckConstraint(
            f"eu_ai_act_risk_level IN {EU_AI_ACT_RISK_LEVELS!r}",
            name="ck_ai_agents_eu_ai_act_risk_level",
        ),
        Index("ix_ai_agents_tenant_active", "tenant_id", "is_active"),
        Index("ix_ai_agents_pack", "pack_id"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    homepage_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agent_packs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Contract
    seats_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Same rule as GradeSpecialization.salary_currency: the installation's
    # currency, resolved at insert time, no server_default.
    cost_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=installation_currency
    )
    contract_renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Security and compliance
    data_classification: Mapped[str] = mapped_column(
        String(20), nullable=False, default="internal", server_default="internal"
    )
    security_review_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="not_reviewed",
        server_default="not_reviewed",
    )
    security_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    security_review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    eu_ai_act_risk_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="minimal", server_default="minimal"
    )

    # State
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AIAgentPrimitive(BaseModel):
    """Per-agent delta against its pack: effective capabilities are
    ``pack.primitives ∪ add − remove``."""

    __tablename__ = "ai_agent_primitives"
    __table_args__ = (
        UniqueConstraint("agent_id", "primitive_id", name="uq_agent_prim"),
        CheckConstraint(
            f"mode IN {PRIMITIVE_OVERRIDE_MODES!r}", name="ck_agent_prim_mode"
        ),
        # The unique constraint leads with agent_id; retiring a primitive
        # (and the RESTRICT check behind it) walks the other way.
        Index("ix_agent_prim_primitive_id", "primitive_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    primitive_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("primitives.id", ondelete="RESTRICT"),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False)


class AIUsageAssignment(BaseModel, TenantMixin):
    """Employee × agent: what the person may use the agent for, under whose
    accountability and supervision, and for how long (§3.3.2)."""

    __tablename__ = "ai_usage_assignments"
    __table_args__ = (
        CheckConstraint(
            f"status IN {ASSIGNMENT_STATUSES!r}", name="ck_ai_assignments_status"
        ),
        CheckConstraint(
            f"supervision_level IN {SUPERVISION_LEVELS!r}",
            name="ck_ai_assignments_supervision_level",
        ),
        Index(
            "ix_ai_assignments_tenant_employee_status",
            "tenant_id",
            "employee_id",
            "status",
        ),
        Index("ix_ai_assignments_tenant_agent", "tenant_id", "agent_id"),
        Index("ix_ai_assignments_tenant_owner", "tenant_id", "accountability_owner_id"),
        Index("ix_ai_assignments_tenant_valid_until", "tenant_id", "valid_until"),
        # The duplicate-pending guard in ``request_assignment`` is a
        # check-then-insert; this is what makes the second one lose.
        Index(
            "uq_ai_assignments_pending",
            "employee_id",
            "agent_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    allowed_use_cases: Mapped[str] = mapped_column(Text, nullable=False)
    supervision_level: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="human_review_required",
        server_default="human_review_required",
    )
    # Required by the API on create and approve; nullable so that losing
    # the owner employee does not take the assignment down with them.
    accountability_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    valid_from: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


# Competences the assignment is scoped to (``competence_tags`` in §3.3.2).
ai_usage_assignment_competences = Table(
    "ai_usage_assignment_competences",
    BaseModel.metadata,
    Column(
        "assignment_id",
        UUID(as_uuid=True),
        ForeignKey("ai_usage_assignments.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "competence_id",
        UUID(as_uuid=True),
        ForeignKey("competences.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # The PK leads with assignment_id; deleting a competence needs this one.
    Index("ix_ai_assign_comp_competence", "competence_id"),
)


class AgentWorkflow(BaseModel, TenantMixin):
    """An automated process: ordered steps of human / ai / hybrid work, the
    human's role in it (orchestrator / executor / reviewer / observer) and
    rough volume and cost estimates (§3.3.3)."""

    __tablename__ = "agent_workflows"
    __table_args__ = (
        CheckConstraint(
            f"human_role IN {HUMAN_ROLE_KINDS!r}", name="ck_agent_workflows_human_role"
        ),
        Index("ix_agent_workflows_tenant_active", "tenant_id", "is_active"),
        Index("ix_agent_workflows_tenant_owner", "tenant_id", "owner_id"),
        Index("ix_agent_workflows_tenant_human_role", "tenant_id", "human_role"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{"type": "human|ai|hybrid", "title": ..., "agent_id": ...,
    #   "escalation_to": ...}] — validated by schemas.WorkflowStep.
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    output_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    monthly_volume_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_rate_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_cost_estimate: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    cost_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=installation_currency
    )

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    human_role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AIWorkforceAuditLog(BaseModel, TenantMixin):
    """One row per registry mutation, written by ``service`` in the same
    transaction as the change (pattern: ``CompetenceTreeAuditLog``)."""

    __tablename__ = "ai_workforce_audit_log"
    __table_args__ = (
        CheckConstraint(
            f"target_type IN {AUDIT_TARGET_TYPES!r}", name="ck_ai_wf_audit_target_type"
        ),
        Index("ix_ai_wf_audit_tenant_created", "tenant_id", "created_at"),
        Index("ix_ai_wf_audit_tenant_target", "tenant_id", "target_type", "target_id"),
        Index("ix_ai_wf_audit_tenant_actor", "tenant_id", "actor_id"),
    )

    # clock_timestamp() advances within a transaction (now() does not), so
    # rows one mutation writes together list in the order they were written.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("clock_timestamp()"),
        nullable=False,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
