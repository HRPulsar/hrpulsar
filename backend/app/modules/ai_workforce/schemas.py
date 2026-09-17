from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

AgentCategory = Literal[
    "chat", "code", "data", "customer_outreach", "image", "agent", "other"
]
DataClassification = Literal["public", "internal", "pii", "customer_data", "financial"]
SecurityReviewStatus = Literal["not_reviewed", "in_review", "approved", "rejected"]
RiskLevel = Literal["minimal", "limited", "high", "unacceptable"]
OverrideMode = Literal["add", "remove"]
SupervisionLevel = Literal["autonomous", "human_review_required", "human_approval_gate"]
AssignmentStatus = Literal["pending", "active", "rejected", "revoked"]
HumanRole = Literal["orchestrator", "executor", "reviewer", "observer"]
StepType = Literal["human", "ai", "hybrid"]
AuditTargetType = Literal["ai_agent", "ai_usage_assignment", "agent_workflow"]


# --- Packs ------------------------------------------------------------------


class AgentPackRead(BaseModel):
    id: uuid.UUID
    code: str
    title_en: str
    description_en: str | None
    i18n_key: str
    sort_index: int
    is_active: bool
    # None = built-in.
    tenant_id: uuid.UUID | None
    primitive_codes: list[str]


# --- Agents -----------------------------------------------------------------


class PrimitiveOverride(BaseModel):
    """One delta against the agent's pack; the effective set is
    ``pack ∪ add − remove``."""

    code: str = Field(min_length=1, max_length=10)
    mode: OverrideMode


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    vendor: str | None = Field(default=None, max_length=200)
    category: AgentCategory = "other"
    description: str | None = None
    homepage_url: str | None = Field(default=None, max_length=600)
    pack_id: uuid.UUID | None = None
    seats_count: int | None = Field(default=None, ge=0)
    monthly_cost: Decimal | None = Field(default=None, ge=0)
    contract_renewal_date: date | None = None
    data_classification: DataClassification = "internal"
    security_review_status: SecurityReviewStatus = "not_reviewed"
    security_review_date: date | None = None
    security_review_notes: str | None = None
    eu_ai_act_risk_level: RiskLevel = "minimal"
    primitives: list[PrimitiveOverride] = Field(default_factory=list, max_length=50)


def _not_null(value: Any) -> Any:
    """PATCH bodies: an absent field is untouched, an explicit ``null``
    clears it - except on NOT NULL columns, where it is refused here so it
    surfaces as a 422 naming the field rather than a 500 from the flush."""
    if value is None:
        raise ValueError("Field required")
    return value


class AgentUpdate(BaseModel):
    _reject_null = field_validator(
        "name",
        "category",
        "data_classification",
        "security_review_status",
        "eu_ai_act_risk_level",
        mode="before",
    )(_not_null)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    vendor: str | None = Field(default=None, max_length=200)
    category: AgentCategory | None = None
    description: str | None = None
    homepage_url: str | None = Field(default=None, max_length=600)
    pack_id: uuid.UUID | None = None
    seats_count: int | None = Field(default=None, ge=0)
    monthly_cost: Decimal | None = Field(default=None, ge=0)
    contract_renewal_date: date | None = None
    data_classification: DataClassification | None = None
    security_review_status: SecurityReviewStatus | None = None
    security_review_date: date | None = None
    security_review_notes: str | None = None
    eu_ai_act_risk_level: RiskLevel | None = None


class AgentRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    vendor: str | None
    category: str
    description: str | None
    homepage_url: str | None
    pack_id: uuid.UUID | None
    pack_code: str | None
    seats_count: int | None
    monthly_cost: Decimal | None
    cost_currency: str
    contract_renewal_date: date | None
    data_classification: str
    security_review_status: str
    security_review_date: date | None
    security_review_notes: str | None
    eu_ai_act_risk_level: str
    is_active: bool
    deactivated_at: datetime | None
    primitive_overrides: list[PrimitiveOverride]
    # pack ∪ add − remove, in catalog order — what Coverage matches against.
    effective_primitive_codes: list[str]
    created_at: datetime
    updated_at: datetime


class AgentList(BaseModel):
    items: list[AgentRead]
    total: int


class AgentPrimitivesUpdate(BaseModel):
    primitives: list[PrimitiveOverride] = Field(default_factory=list, max_length=50)


# --- Usage assignments ------------------------------------------------------


class AssignmentCreate(BaseModel):
    employee_id: uuid.UUID
    agent_id: uuid.UUID
    allowed_use_cases: str = Field(min_length=1)
    supervision_level: SupervisionLevel = "human_review_required"
    accountability_owner_id: uuid.UUID
    # None = today.
    valid_from: date | None = None
    # None = open-ended.
    valid_until: date | None = None
    competence_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class AssignmentRequest(BaseModel):
    """Self-service: the caller asks for an agent for themselves; the
    employee row is resolved from the caller's user."""

    agent_id: uuid.UUID
    allowed_use_cases: str = Field(min_length=1)
    accountability_owner_id: uuid.UUID | None = None
    valid_until: date | None = None
    competence_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class AssignmentUpdate(BaseModel):
    # The owner may change hands, never be cleared: an approved assignment
    # names who answers for the agent's use (``approve_assignment`` refuses
    # one without), and an explicit null slipped past the service's
    # ``is not None`` check straight into the column.
    _reject_null = field_validator(
        "allowed_use_cases", "valid_from", "accountability_owner_id", mode="before"
    )(_not_null)

    allowed_use_cases: str | None = Field(default=None, min_length=1)
    accountability_owner_id: uuid.UUID | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    competence_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)


class AssignmentApprove(BaseModel):
    # Required here when the request named no owner.
    accountability_owner_id: uuid.UUID | None = None
    supervision_level: SupervisionLevel | None = None
    valid_until: date | None = None


class AssignmentDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class SupervisionChange(BaseModel):
    supervision_level: SupervisionLevel


class AssignmentRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    employee_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    allowed_use_cases: str
    supervision_level: str
    accountability_owner_id: uuid.UUID | None
    valid_from: date
    valid_until: date | None
    status: str
    requested_at: datetime | None
    approved_at: datetime | None
    approved_by_id: uuid.UUID | None
    competence_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class AssignmentList(BaseModel):
    items: list[AssignmentRead]
    total: int


# --- Workflows --------------------------------------------------------------


class WorkflowStep(BaseModel):
    type: StepType
    title: str = Field(min_length=1, max_length=200)
    # A registered agent doing the step (ai / hybrid).
    agent_id: uuid.UUID | None = None
    # Employee who takes over when the step escalates.
    escalation_to: uuid.UUID | None = None


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    steps: list[WorkflowStep] = Field(default_factory=list, max_length=100)
    output_type: str | None = Field(default=None, max_length=100)
    monthly_volume_estimate: int | None = Field(default=None, ge=0)
    error_rate_estimate: float | None = Field(default=None, ge=0, le=1)
    monthly_cost_estimate: Decimal | None = Field(default=None, ge=0)
    owner_id: uuid.UUID
    human_role: HumanRole


class WorkflowUpdate(BaseModel):
    # ``steps`` is NOT NULL too, but a null there is an accepted way to say
    # "leave the steps alone" - update_workflow drops it.
    _reject_null = field_validator("name", "human_role", mode="before")(_not_null)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    steps: list[WorkflowStep] | None = Field(default=None, max_length=100)
    output_type: str | None = Field(default=None, max_length=100)
    monthly_volume_estimate: int | None = Field(default=None, ge=0)
    error_rate_estimate: float | None = Field(default=None, ge=0, le=1)
    monthly_cost_estimate: Decimal | None = Field(default=None, ge=0)
    owner_id: uuid.UUID | None = None
    human_role: HumanRole | None = None


class WorkflowRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    steps: list[WorkflowStep]
    output_type: str | None
    monthly_volume_estimate: int | None
    error_rate_estimate: float | None
    monthly_cost_estimate: Decimal | None
    cost_currency: str
    owner_id: uuid.UUID | None
    human_role: str
    is_active: bool
    deactivated_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowList(BaseModel):
    items: list[WorkflowRead]
    total: int


# --- Audit ------------------------------------------------------------------


class AuditRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    target_type: str
    target_id: uuid.UUID
    payload: dict[str, Any] | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditList(BaseModel):
    items: list[AuditRead]
    total: int
