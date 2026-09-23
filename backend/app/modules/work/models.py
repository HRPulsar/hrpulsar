"""Work design (HRP-754): a container of work — a process or an initiative —
broken into a flat ordered list of steps, each step tagged with the
capability primitives it requires, plus the AI decomposition session that
drafts that list.

The lifecycle lives on the step, not the container (REFACTOR_PLAN §4.3):
``system_suggested`` as the model wrote it, ``tenant_edited`` after any
edit — flipped by the service so no handler can forget — and ``accepted``
once the container's owner accepts the whole list, which also pins
``catalog_version``. A step with no primitive at all is a valid state
("signature by the authorised signatory" needs no capability, only
accountability), and a rejected step is a deleted step.

There is deliberately no UNIQUE on ``(container_id, position)``: renumbering
after a drag-and-drop under such an index needs a deferrable constraint or a
two-phase update, and the order is stable enough with ``created_at`` as the
tie-break. Reorder is one ``UPDATE ... FROM (VALUES ...)``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import BaseModel, TenantMixin

CONTAINER_TYPES = ("initiative", "process")
CONTAINER_STATUSES = ("draft", "active", "archived")
CONTAINER_SOURCES = ("manual", "ai")
GAP_LABELS = ("hire", "agency")
# S1, S2 and S4 of the catalog: who answers for the step, how reversible it
# is, and whether it changes the outside world. S3 (how often and how long
# it runs) is two numbers since W6, see below.
RESPONSIBILITIES = ("none", "reputational", "formal", "regulatory")
REVERSIBILITIES = ("reversible", "costly", "irreversible")
OUTPUT_TYPES = ("draft", "external_change")
# What coverage derives for a step from its accountability and the verdicts
# of its capabilities; stored only as the company's override (HRP-863).
AUTOMATION_MODES = (
    "automatable",
    "draft_then_review",
    "review_required",
    "blocked_judgment",
    "blocked_physical",
)
# W6 (decision 2026-09-11): a step's yearly hours are ``hours_per_run x
# runs_per_year`` - the model's estimate, corrected by the company. The
# bounds are shared by the CHECKs, the wire schemas and the worker.
# The column is Numeric(6, 2): anything under half a hundredth rounds to
# 0.00 and then fails the CHECK, so the floor is a hundredth of an hour.
HOURS_PER_RUN_MIN = 0.01
HOURS_PER_RUN_MAX = 200
# Widened from the spec's 10 000 on the evidence of the acceptance run:
# on ``hc-1-emergency-triage`` the model estimated 20 000-30 000 runs a
# year - an emergency department really does triage that many patients -
# and every estimate of that process was dropped, leaving it unpriced.
# The bound is here to catch a hallucinated digit run, not to bound
# reality, so it sits where no human process reaches.
RUNS_PER_YEAR_MAX = 1_000_000
# HRP-776: a verbatim fragment of the description behind a capability, as
# stored; the worker and a reclassification cut the model's quote to it.
QUOTE_MAX = 500
STEP_STATES = ("system_suggested", "tenant_edited", "accepted")
STEP_PRIMITIVE_SOURCES = ("system_suggested", "tenant_edited")
# HRP-810: who reads a container besides the section's managers, its owner
# and the people on its steps. ``company`` - every user of the tenant;
# ``restricted`` - only the people its access rules name.
VISIBILITIES = ("company", "restricted")
# Roles a rule may name. admin and hr manage the section and read every
# container anyway; platform_admin is not a tenant role.
RULE_ROLE_CODES = ("manager", "recruiter", "hiring_manager", "employee")
ACCESS_LOG_ACTIONS = (
    "owner_changed",
    "visibility_changed",
    "rule_added",
    "rule_removed",
)

# Same lifecycle as CompetenceGenerationSession: pending → running →
# ready/error → applied/cancelled; {pending, running, ready} are «active».
SESSION_STATUSES = ("pending", "running", "ready", "error", "applied", "cancelled")
ACTIVE_STATUSES = ("pending", "running", "ready")
# HRP-775: the two LLM calls of a run, shown on the banner while running.
SESSION_PHASES = ("splitting", "classifying")
ERROR_CODES = (
    "service_error",
    "overload",
    "insufficient_data",
    "parse_error",
    "reaped_stuck",
    "output_truncated",
)


def _in(column: str, values: tuple[str, ...], *, nullable: bool = False) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    clause = f"{column} IN ({quoted})"
    return f"{column} IS NULL OR {clause}" if nullable else clause


class WorkContainer(BaseModel, TenantMixin):
    __tablename__ = "work_containers"
    __table_args__ = (
        CheckConstraint(_in("type", CONTAINER_TYPES), name="ck_work_containers_type"),
        CheckConstraint(
            _in("status", CONTAINER_STATUSES), name="ck_work_containers_status"
        ),
        CheckConstraint(
            _in("source", CONTAINER_SOURCES), name="ck_work_containers_source"
        ),
        CheckConstraint(
            _in("gap_default_label", GAP_LABELS),
            name="ck_work_containers_gap_default_label",
        ),
        CheckConstraint(
            _in("visibility", VISIBILITIES), name="ck_work_containers_visibility"
        ),
        Index("ix_work_containers_tenant_status", "tenant_id", "status"),
        Index("ix_work_containers_tenant_type", "tenant_id", "type"),
    )

    type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # The input of the AI decomposition; a hand-built container may not have one.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    # Who answers for the container: accepts the breakdown and edits it
    # (HRP-810).
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual", server_default="manual"
    )
    # The catalog version the breakdown was made against; re-pinned on accept.
    catalog_version: Mapped[str] = mapped_column(String(20), nullable=False)
    gap_default_label: Mapped[str] = mapped_column(
        String(10), nullable=False, default="hire", server_default="hire"
    )
    # HRP-810: a new container starts restricted; v2work07 opened the ones
    # that existed before to the company, so no stand lost what it showed.
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="restricted", server_default="restricted"
    )
    # HRP-862: the figures the list page shows, written whenever coverage is
    # computed, so the list never runs coverage per container. Null until
    # the first computation.
    coverage_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )


class WorkStep(BaseModel, TenantMixin):
    __tablename__ = "work_steps"
    __table_args__ = (
        CheckConstraint(
            _in("responsibility", RESPONSIBILITIES), name="ck_work_steps_responsibility"
        ),
        CheckConstraint(
            _in("reversibility", REVERSIBILITIES, nullable=True),
            name="ck_work_steps_reversibility",
        ),
        CheckConstraint(
            "hours_per_run IS NULL OR "
            f"(hours_per_run >= {HOURS_PER_RUN_MIN} "
            f"AND hours_per_run <= {HOURS_PER_RUN_MAX})",
            name="ck_work_steps_hours_per_run",
        ),
        CheckConstraint(
            "runs_per_year IS NULL OR "
            f"(runs_per_year >= 1 AND runs_per_year <= {RUNS_PER_YEAR_MAX})",
            name="ck_work_steps_runs_per_year",
        ),
        CheckConstraint(
            _in("output_type", OUTPUT_TYPES), name="ck_work_steps_output_type"
        ),
        CheckConstraint(_in("state", STEP_STATES), name="ck_work_steps_state"),
        CheckConstraint(
            _in("gap_label", GAP_LABELS, nullable=True), name="ck_work_steps_gap_label"
        ),
        CheckConstraint(
            "review_human_share IS NULL OR "
            "(review_human_share >= 0 AND review_human_share <= 100)",
            name="ck_work_steps_review_human_share",
        ),
        CheckConstraint(
            _in("manual_mode", AUTOMATION_MODES, nullable=True),
            name="ck_work_steps_manual_mode",
        ),
        Index("ix_work_steps_container_position", "container_id", "position"),
    )

    container_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_containers.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="none", server_default="none"
    )
    reversibility: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The model's estimate (W6), corrected by the company; null on a step
    # typed in by hand or drafted before ``v2work.v7`` - such a step stays
    # out of the shares and the ROI.
    hours_per_run: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    runs_per_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="system_suggested",
        server_default="system_suggested",
    )
    # Set on the gaps report; falls back to the container's default.
    gap_label: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # HRP-809: who does the step and who checks and signs it. The executor
    # outranks the computed match, agent included; both are ignored by
    # coverage once the employee is no longer active.
    executor_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    accountable_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # HRP-861: percent of a reviewed step's hours that stays with the person
    # who checks the agent's work; null means the default share.
    review_human_share: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # HRP-863: the company's word on the mode and on the agent pack (a pack
    # code, built-in or the tenant's own); each outranks the computed value.
    manual_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    manual_pack_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # HRP-868: the step's own hourly rate in the tenant's currency; null
    # falls back to the tenant's rate.
    hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)


class WorkStepPrimitive(BaseModel, TenantMixin):
    """Step ↔ primitive, N:M from the start (MVP decision 6). ``tenant_id``
    mirrors the step's so coverage filters without a join.

    HRP-776: ``confidence`` and ``quote`` are the model's case for the code
    (null when the company set it by hand); ``confirmed_at`` is when the
    company confirmed it - a chip click, the capability picker saved, or a
    code it added itself. The removal of a code is the row's deletion; the
    original proposal stays in the session payload (``work/edits.py``)."""

    __tablename__ = "work_step_primitives"
    __table_args__ = (
        UniqueConstraint("step_id", "primitive_id", name="uq_work_step_prim"),
        CheckConstraint(
            _in("source", STEP_PRIMITIVE_SOURCES), name="ck_work_step_prim_source"
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_work_step_prim_confidence",
        ),
        Index("ix_work_step_prim_primitive", "primitive_id"),
    )

    step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_steps.id", ondelete="CASCADE"),
        nullable=False,
    )
    # RESTRICT: the catalog is never deleted, only retired.
    primitive_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("primitives.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WorkContainerAccessRule(BaseModel, TenantMixin):
    """HRP-810: one reason a user reads a ``restricted`` container - their
    role, their current position or they themselves. Exactly one target per
    row; a deleted position or employee takes its rules with it."""

    __tablename__ = "work_container_access_rules"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(role_code, position_id, employee_id) = 1",
            name="ck_work_access_rules_one_target",
        ),
        CheckConstraint(
            _in("role_code", RULE_ROLE_CODES, nullable=True),
            name="ck_work_access_rules_role_code",
        ),
        Index(
            "ux_work_access_rules_role",
            "container_id",
            "role_code",
            unique=True,
            postgresql_where=text("role_code IS NOT NULL"),
        ),
        Index(
            "ux_work_access_rules_position",
            "container_id",
            "position_id",
            unique=True,
            postgresql_where=text("position_id IS NOT NULL"),
        ),
        Index(
            "ux_work_access_rules_employee",
            "container_id",
            "employee_id",
            unique=True,
            postgresql_where=text("employee_id IS NOT NULL"),
        ),
    )

    container_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_containers.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("positions.id", ondelete="CASCADE"),
        nullable=True,
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=True,
    )


class WorkContainerAccessLog(BaseModel, TenantMixin):
    """HRP-810: who changed a container's owner, visibility or rules, written
    by ``service`` in the same transaction as the change (pattern:
    ``AIWorkforceAuditLog``). ``payload`` keeps a rule's label, so the
    history still reads after the position or the employee is gone."""

    __tablename__ = "work_container_access_log"
    __table_args__ = (
        CheckConstraint(
            _in("action", ACCESS_LOG_ACTIONS), name="ck_work_access_log_action"
        ),
        Index("ix_work_access_log_container_created", "container_id", "created_at"),
    )

    # clock_timestamp(): the rows one save writes list in write order.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("clock_timestamp()"),
        nullable=False,
    )
    container_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_containers.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class WorkDecompositionSession(BaseModel, TenantMixin):
    """One AI decomposition run of a container (HRP-755) — a copy of
    ``CompetenceGenerationSession`` with the active-session guard per
    container rather than per user: two people working on two containers
    must not block each other."""

    __tablename__ = "work_decomposition_sessions"
    __table_args__ = (
        CheckConstraint(_in("status", SESSION_STATUSES), name="ck_workdecomp_status"),
        CheckConstraint(
            _in("error_code", ERROR_CODES, nullable=True),
            name="ck_workdecomp_error_code",
        ),
        CheckConstraint(
            _in("phase", SESSION_PHASES, nullable=True), name="ck_workdecomp_phase"
        ),
        Index(
            "ux_workdecomp_one_active_per_container",
            "container_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running', 'ready')"),
        ),
        Index("ix_workdecomp_status", "status"),
        # ``latest_session`` — the editor's poll on every container open.
        # The partial index above covers only the active statuses, so an
        # applied or cancelled newest run was a sequential scan.
        Index("ix_workdecomp_container_created", "container_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    container_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_containers.id", ondelete="CASCADE"),
        nullable=False,
    )
    params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    base_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    phase: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_idempotency_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    applied_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class WorkHireNeed(BaseModel, TenantMixin):
    """A gap handed to Recruitment (HRP-759, §6): which steps, which label,
    and the draft vacancy that came out of it. A separate table rather than
    a column on ``vacancies`` - one need may span several steps, and the
    dependency runs ``work → recruitment`` only."""

    __tablename__ = "work_hire_needs"
    __table_args__ = (
        CheckConstraint(_in("label", GAP_LABELS), name="ck_work_hire_needs_label"),
        Index("ix_work_hire_needs_container", "container_id"),
        Index("ix_work_hire_needs_vacancy", "vacancy_id"),
    )

    container_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_containers.id", ondelete="CASCADE"),
        nullable=False,
    )
    vacancy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="SET NULL"),
        nullable=True,
    )
    # JSON array of step uuids as strings.
    step_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    label: Mapped[str] = mapped_column(String(10), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


SKILL_STATUSES = ("generating", "ready", "failed")


class WorkStepSkill(BaseModel, TenantMixin):
    """The generated ``SKILL.md`` of a step (HRP-760, §4.4): one row per
    step, status on the artifact itself - the generation is synchronous
    and the output is one markdown file. A failed regeneration writes the
    status and the error but never clears ``content``: the last working
    skill stays in place."""

    __tablename__ = "work_step_skills"
    __table_args__ = (
        UniqueConstraint("step_id", name="uq_work_step_skills_step"),
        CheckConstraint(
            _in("status", SKILL_STATUSES), name="ck_work_step_skills_status"
        ),
    )

    step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_steps.id", ondelete="CASCADE"),
        nullable=False,
    )
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agent_packs.id", ondelete="SET NULL"),
        nullable=True,
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="generating", server_default="generating"
    )
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    catalog_version: Mapped[str] = mapped_column(String(20), nullable=False)
