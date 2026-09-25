"""Wire schemas of ``/api/work`` (HRP-754)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    create_model,
    field_validator,
)

from app.modules.work.models import (
    HOURS_PER_RUN_MAX,
    HOURS_PER_RUN_MIN,
    RUNS_PER_YEAR_MAX,
)

ContainerType = Literal["initiative", "process"]
ContainerStatus = Literal["draft", "active", "archived"]
GapLabel = Literal["hire", "agency"]
Responsibility = Literal["none", "reputational", "formal", "regulatory"]
Reversibility = Literal["reversible", "costly", "irreversible"]
OutputType = Literal["draft", "external_change"]
# W6: the step's yearly hours are hours_per_run x runs_per_year; null
# means "not estimated" and keeps the step out of the shares.
HoursPerRun = Annotated[float, Field(ge=HOURS_PER_RUN_MIN, le=HOURS_PER_RUN_MAX)]
RunsPerYear = Annotated[int, Field(ge=1, le=RUNS_PER_YEAR_MAX)]
StepState = Literal["system_suggested", "tenant_edited", "accepted"]
# What coverage derives for a step; on the step itself only as the
# company's override (HRP-863).
AutomationMode = Literal[
    "automatable",
    "draft_then_review",
    "review_required",
    "blocked_judgment",
    "blocked_physical",
]
# HRP-861: percent of a reviewed step's hours that stays with the checker.
ReviewHumanShare = Annotated[int, Field(ge=0, le=100)]
# HRP-868: the step's own rate, in the tenant's currency. The floor is a
# cent, not a hair above zero: the column is Numeric(10, 2), so anything
# smaller would be stored as 0.00 and price the step at nothing.
StepHourlyRate = Annotated[float, Field(ge=0.01, le=99_999_999)]
Visibility = Literal["company", "restricted"]
AccessLevel = Literal["manage", "edit", "read"]
RuleRoleCode = Literal["manager", "recruiter", "hiring_manager", "employee"]
AccessLogAction = Literal[
    "owner_changed", "visibility_changed", "rule_added", "rule_removed"
]

TITLE_MAX = 300
TEXT_MAX = 20_000
Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX)
]


class ContainerCreate(BaseModel):
    type: ContainerType
    title: Title
    description: str | None = Field(default=None, max_length=TEXT_MAX)
    goal: str | None = Field(default=None, max_length=TEXT_MAX)
    owner_id: uuid.UUID | None = None
    gap_default_label: GapLabel = "hire"


def _not_null(value: Any) -> Any:
    """PATCH bodies: an absent field is untouched, an explicit ``null``
    clears it - except on NOT NULL columns, where it is refused here so it
    surfaces as a 422 naming the field rather than a 500 from the flush."""
    if value is None:
        raise ValueError("Field required")
    return value


class ContainerUpdate(BaseModel):
    _reject_null = field_validator(
        "title", "status", "gap_default_label", mode="before"
    )(_not_null)

    title: Title | None = None
    description: str | None = Field(default=None, max_length=TEXT_MAX)
    goal: str | None = Field(default=None, max_length=TEXT_MAX)
    # ``active`` is reached only through accept, which also flips the steps
    # and pins the catalog version.
    status: Literal["draft", "archived"] | None = None
    owner_id: uuid.UUID | None = None
    gap_default_label: GapLabel | None = None


class ContainerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    type: ContainerType
    title: str
    description: str | None
    goal: str | None
    status: ContainerStatus
    owner_id: uuid.UUID | None
    created_by_id: uuid.UUID | None
    source: str
    catalog_version: str
    gap_default_label: GapLabel
    visibility: Visibility
    # HRP-810: what the caller may do with it - filled by the router, which
    # knows the caller; the service returns rows.
    my_access: AccessLevel | None = None
    # HRP-862: ``coverage.summary_of`` as last computed - ``hours``, ``shares``
    # and ``automated_share``; null until the coverage was opened once. Left
    # untyped on purpose: it is a stored cache, and a row written by an older
    # release must read as "not known" rather than fail the whole list.
    coverage_summary: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ContainerList(BaseModel):
    items: list[ContainerRead]
    total: int


class AccessRuleRef(BaseModel):
    """One target of an access rule (HRP-810). Exactly one field is set; the
    service refuses anything else with ``work_access_rule_invalid``."""

    role_code: RuleRoleCode | None = None
    position_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None


class AccessRuleRead(AccessRuleRef):
    # A position's title or an employee's name; a role is labelled by the SPA.
    label: str | None = None


class AccessOwnerRead(BaseModel):
    user_id: uuid.UUID
    name: str
    # False once the owner left: the account is off or the card is not active.
    active: bool


class AccessLogRead(BaseModel):
    action: AccessLogAction
    actor_name: str | None
    payload: dict[str, Any] | None
    created_at: datetime


class ContainerAccessRead(BaseModel):
    visibility: Visibility
    owner: AccessOwnerRead | None
    rules: list[AccessRuleRead]
    history: list[AccessLogRead]


class ProcessPersonRead(BaseModel):
    employee_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    email: str | None
    position_title: str | None
    # At work, so a step can be assigned to them (HRP-809); anyone listed
    # can be named in an access rule or made the owner.
    assignable: bool


class ContainerAccessUpdate(BaseModel):
    visibility: Visibility
    rules: list[AccessRuleRef] = Field(default_factory=list, max_length=200)


class StepCreate(BaseModel):
    title: Title
    description: str | None = Field(default=None, max_length=TEXT_MAX)
    responsibility: Responsibility = "none"
    reversibility: Reversibility | None = None
    hours_per_run: HoursPerRun | None = None
    runs_per_year: RunsPerYear | None = None
    output_type: OutputType = "draft"
    gap_label: GapLabel | None = None
    notes: str | None = Field(default=None, max_length=TEXT_MAX)
    # HRP-944: omitted means «not classified yet»; an empty list is the
    # company's word that the step needs no capability.
    primitive_codes: list[str] | None = Field(default=None, max_length=20)


class StepUpdate(BaseModel):
    _reject_null = field_validator(
        "title", "responsibility", "output_type", mode="before"
    )(_not_null)

    title: Title | None = None
    description: str | None = Field(default=None, max_length=TEXT_MAX)
    responsibility: Responsibility | None = None
    reversibility: Reversibility | None = None
    hours_per_run: HoursPerRun | None = None
    runs_per_year: RunsPerYear | None = None
    output_type: OutputType | None = None
    gap_label: GapLabel | None = None
    notes: str | None = Field(default=None, max_length=TEXT_MAX)
    # HRP-809: an active employee of the tenant; ``null`` clears it.
    executor_employee_id: uuid.UUID | None = None
    accountable_employee_id: uuid.UUID | None = None
    # ``null`` clears each: the default share (HRP-861), the computed mode
    # and pack (HRP-863), the tenant's rate (HRP-868).
    review_human_share: ReviewHumanShare | None = None
    manual_mode: AutomationMode | None = None
    manual_pack_code: str | None = Field(default=None, max_length=50)
    hourly_rate: StepHourlyRate | None = None


class StepCapability(BaseModel):
    """One capability link with its provenance (HRP-776): the model's
    confidence and the fragment of the description it quoted, and whether
    the company confirmed it. ``confidence`` is null for a code the company
    set by hand or one written before the model reported confidence."""

    code: str
    confidence: float | None
    quote: str | None
    confirmed: bool


class StepRead(BaseModel):
    id: uuid.UUID
    container_id: uuid.UUID
    position: int
    title: str
    description: str | None
    responsibility: Responsibility
    reversibility: Reversibility | None
    hours_per_run: float | None
    runs_per_year: int | None
    output_type: OutputType
    state: StepState
    gap_label: GapLabel | None
    notes: str | None
    executor_employee_id: uuid.UUID | None
    accountable_employee_id: uuid.UUID | None
    review_human_share: int | None
    manual_mode: AutomationMode | None
    manual_pack_code: str | None
    hourly_rate: float | None
    primitive_codes: list[str]
    capabilities: list[StepCapability]
    created_at: datetime
    updated_at: datetime


class StepOrder(BaseModel):
    step_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class StepPrimitivesUpdate(BaseModel):
    codes: list[str] = Field(max_length=20)


# --- AI decomposition (HRP-755) ----------------------------------------------

SessionStatus = Literal["pending", "running", "ready", "error", "applied", "cancelled"]


class DecomposedStep(BaseModel):
    """One step as the model returns it. Lenient where the catalog is:
    ``primitives`` are filtered against the catalog by the worker, so an
    invented code costs one code, not the whole paid answer."""

    title: Title
    description: str | None = None
    primitives: list[str] = Field(default_factory=list)
    responsibility: Responsibility = "none"
    reversibility: Reversibility | None = None
    # W6: the model's estimate of the step's yearly hours, as two numbers.
    # Unbounded here on purpose: a number out of range is dropped by the
    # worker's ``_normalise`` (the step shows "hours not set"), not a
    # validation failure that retries the whole paid answer.
    hours_per_run: float | None = None
    runs_per_year: float | None = None
    output_type: OutputType = "draft"


class DecompositionSchema(BaseModel):
    steps: list[DecomposedStep] = Field(max_length=60)


class Evidence(BaseModel):
    """Why a code is on a step (HRP-776): a verbatim fragment of the
    description and the model's confidence 0..1. Lenient on the quote's
    length - the worker truncates."""

    code: str
    quote: str = ""
    confidence: float = Field(ge=0, le=1)


class StepClassification(BaseModel):
    """The second pass (HRP-775): what the model says about one fixed step.
    Title, description and the scales stay as the first pass wrote them."""

    primitives: list[str] = Field(default_factory=list)
    responsibility: Responsibility = "none"
    output_type: OutputType = "draft"
    # Required, not defaulted: the few-shot answers carry no evidence, and
    # an optional key let a model that copied them pass validation with
    # every confidence NULL - no chip ever tentative, no quote anywhere.
    # Absent, the answer fails validation and is retried like a parse error.
    evidence: list[Evidence]


def classification_schema(count: int) -> type[BaseModel]:
    """One entry per fixed step, no more, no less: a count mismatch fails
    validation, which the retry loop treats as a parse error and retries
    rather than pairing codes with the wrong steps."""
    return create_model(
        "ClassificationSchema",
        steps=(list[StepClassification], Field(min_length=count, max_length=count)),
    )


class ReclassifyRequest(BaseModel):
    comment: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]


class SessionCreate(BaseModel):
    container_id: uuid.UUID


class SessionApply(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=100)


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # ``params`` is the run's own bookkeeping; the price pinned for the
    # charge is ours, not something a reader of a breakdown is shown.
    @field_validator("params", mode="after")
    @classmethod
    def _without_cost(cls, params: dict) -> dict:
        return {k: v for k, v in params.items() if k != "cost"}

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    container_id: uuid.UUID
    params: dict
    payload: dict | None
    status: SessionStatus
    # ``splitting`` / ``classifying`` while running (HRP-775), else null.
    phase: str | None = None
    error_code: str | None
    error_message: str | None
    prompt_version: str
    llm_model: str | None
    celery_task_id: str | None
    applied_result: dict | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class ApplyResult(BaseModel):
    created_steps: list[uuid.UUID]
    idempotency_key: str


# --- Coverage (HRP-758) ------------------------------------------------------

Verdict = Literal["agent", "human", "gap", "out_of_scope", "unclassified"]
# ``assigned`` (HRP-809): named on the step by the company, whatever the
# match says.
HumanLabel = Literal["assessed", "expected", "assigned"]
# W6 (§5.3): how well an agent does the step - the weakest capability's
# verdict. Same four values as ``Primitive.ai_verdict``.
Quality = Literal["no", "draft", "strong", "better_than_human"]


class GapHireNeed(BaseModel):
    id: uuid.UUID
    vacancy_id: uuid.UUID | None
    label: GapLabel


class CoverageAgent(BaseModel):
    pack_id: uuid.UUID | None
    pack_code: str | None
    # HRP-863: the company named this pack on the step; ``pack_code`` is the
    # effective one either way.
    pack_manual: bool = False
    agent_id: uuid.UUID | None
    agent_name: str | None


class CoverageGround(BaseModel):
    """HRP-871: one competence of the matched person behind the step's
    capabilities - confirmed by the latest completed assessment (``percent``
    reached the person's passing score) or only expected by the grade matrix
    of their position (no score yet)."""

    competence_id: uuid.UUID
    title: str
    state: Literal["assessed", "expected"]
    percent: int | None
    # The step's capabilities this competence covers.
    codes: list[str]


class CoverageHuman(BaseModel):
    employee_id: uuid.UUID
    name: str
    # The matching is by capability, not by role; the title lets the
    # reader see when a product manager covers a controller's sign-off.
    position: str | None
    label: HumanLabel
    # The step's cognitive codes the person does not hold; only an assigned
    # executor can have any.
    missing_codes: list[str]
    # HRP-871: what the match stands on, and the passing score the scores
    # were held against (the person's grade specialization, or the default).
    # Empty for an assigned executor: the company named them, nothing matched.
    passing_score: int | None = None
    grounds: list[CoverageGround] = []


class CoveragePerson(BaseModel):
    employee_id: uuid.UUID
    name: str
    position: str | None


SkillStatus = Literal["none", "generating", "ready", "failed"]


class CoverageStep(BaseModel):
    step_id: uuid.UUID
    position: int
    title: str
    state: StepState
    codes: list[str]
    required_codes: list[str]
    in_scope: bool
    mode: AutomationMode | None
    # HRP-863: ``mode`` is the company's override, not the computed one.
    mode_manual: bool = False
    # None for a step out of scope, which has no cognitive capability.
    quality: Quality | None
    verdict: Verdict
    agent: CoverageAgent | None
    human: CoverageHuman | None
    human_backup: bool
    # HRP-809: who checks and signs the step, and whether the step asks for
    # one - an agent's draft or review, or a responsibility someone bears.
    accountable: CoveragePerson | None
    needs_accountable: bool
    gap_label: GapLabel | None
    # hours_per_run x runs_per_year; null when either is not set.
    hours_per_year: float | None
    # The newest hire need of this step that still points at a vacancy, so
    # the row links to it instead of offering the handoff a second time.
    hire_need: GapHireNeed | None
    skill_status: SkillStatus
    # HRP-776: the verdict is preliminary while the step is not accepted or
    # rests on a code the model was unsure of and nobody confirmed.
    tentative: bool
    # HRP-861: percent of the step's hours its checker keeps - the step's own
    # or the default; null outside the review bucket.
    review_human_share: int | None


class CoverageShares(BaseModel):
    moves: float
    to_review: float
    stays: float


class CoverageHours(BaseModel):
    """Yearly hours of the in-scope steps that carry an estimate, by
    bucket (W6). ``unestimated`` counts the in-scope steps without one -
    they are in no bucket and no share."""

    total: float
    moves: float
    to_review: float
    stays: float
    unestimated: int
    # HRP-861: ``to_review`` is the bucket before an agent drafts the work;
    # this is what its checkers keep after. ``freed`` is ``moves`` plus the
    # difference between the two.
    to_review_after: float
    freed: float
    # HRP-862: the hours of the steps an agent the tenant registered does
    # today - part of ``total``, not a bucket of its own.
    automated: float


class CoverageMoney(BaseModel):
    """HRP-868: the yearly money of the estimated steps, the same set as
    ``CoverageHours`` and in the tenant's currency - a sum over the steps,
    each at its own rate or the tenant's. ``unpriced`` counts the estimated
    steps with neither: they are in no figure here."""

    total: float
    moves: float
    to_review: float
    to_review_after: float
    stays: float
    freed: float
    unpriced: int


class CoverageQuality(BaseModel):
    """How many in-scope steps sit at each quality (§5.3)."""

    no: int
    draft: int
    strong: int
    better_than_human: int


class CoverageRead(BaseModel):
    container_id: uuid.UUID
    status: ContainerStatus
    mapping_pending: bool
    candidate_step_ids: list[uuid.UUID]
    # Percentages of ``hours`` by bucket; None on a breakdown shorter than
    # four steps in scope, or while no candidate step carries an estimate.
    shares: CoverageShares | None
    hours: CoverageHours
    quality: CoverageQuality
    # The tenant's own hourly rate, for the ROI in money; None until it is
    # set, and then the screen shows hours only (§5.2).
    hourly_rate: float | None
    hourly_rate_currency: str | None
    # HRP-868: null while no estimated step has a rate - hours only, then.
    money: CoverageMoney | None
    # HRP-861: the share a reviewed step falls back to, for the editor's hint.
    review_human_share_default: int
    steps: list[CoverageStep]


# W6 (§5.10): which To do section the row belongs to - nobody covers it,
# or an agent could and nobody has automated it yet.
GapKind = Literal["no_owner", "not_automated_yet"]


class GapRead(BaseModel):
    step_id: uuid.UUID
    position: int
    title: str
    kind: GapKind
    mode: AutomationMode | None
    # Only a ``no_owner`` row is routed to hiring; the other kind has none.
    gap_label: GapLabel | None
    required_codes: list[str]
    # The agent type that covers a ``not_automated_yet`` row, so the screen
    # can register the agent the company already uses for it.
    agent: CoverageAgent | None
    skill_status: SkillStatus
    # The newest hire need that still points at a vacancy, if any.
    hire_need: GapHireNeed | None


# --- Hire needs (HRP-759) ----------------------------------------------------


class HireNeedCreate(BaseModel):
    step_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    label: GapLabel = "hire"
    title: Title | None = None
    division_id: uuid.UUID | None = None
    # W6 (§5.9): search inside the company first, or go straight outside.
    # Passed through to the draft vacancy, which owns the switch.
    internal_search_allowed: bool = True


class HireNeedRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    container_id: uuid.UUID
    vacancy_id: uuid.UUID | None
    step_ids: list[uuid.UUID]
    label: GapLabel
    created_by_id: uuid.UUID | None
    created_at: datetime


# --- Step skills (HRP-760) ---------------------------------------------------


class GeneratedSkillSchema(BaseModel):
    """What the model returns: the frontmatter fields and the filled
    skeleton. Lenient on length - the renderer slugs and truncates."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    body: str = Field(min_length=20)


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    step_id: uuid.UUID
    pack_id: uuid.UUID | None
    status: Literal["generating", "ready", "failed"]
    skill_name: str | None
    content: str | None
    error_message: str | None
    prompt_version: str | None
    llm_model: str | None
    generated_by_id: uuid.UUID | None
    generated_at: datetime | None
    catalog_version: str
    created_at: datetime
    updated_at: datetime
