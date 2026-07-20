from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.validators import not_past_deadline

# --- Answer Scale ---


class AnswerOptionRead(BaseModel):
    id: uuid.UUID
    title: str
    code: str
    weight: int | None
    description: str | None
    sort_index: int
    is_neutral: bool = False
    model_config = {"from_attributes": True}


class AnswerScaleLevelRead(BaseModel):
    id: uuid.UUID
    percent_from: int
    percent_to: int
    system_code: str | None = None
    system_title: str | None = None
    description: str | None
    sort_index: int
    model_config = {"from_attributes": True}


class AnswerScaleRead(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    tenant_id: uuid.UUID | None
    is_default: bool
    options: list[AnswerOptionRead] = []
    model_config = {"from_attributes": True}


class AnswerScaleDetailRead(AnswerScaleRead):
    levels: list[AnswerScaleLevelRead] = []
    is_snapshot: bool = False
    deleted_at: datetime | None = None


class AnswerOptionInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    sort_index: int = 0
    is_neutral: bool = False


class AnswerScaleLevelInput(BaseModel):
    percent_from: int = Field(ge=0, le=100)
    percent_to: int = Field(ge=0, le=100)
    system_title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    sort_index: int = 0


class AnswerScaleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    options: list[AnswerOptionInput] = Field(min_length=2, max_length=11)
    levels: list[AnswerScaleLevelInput] = Field(default_factory=list, max_length=100)


class AnswerScaleUpdate(AnswerScaleCreate):
    pass


class AnswerScaleDeleteResult(BaseModel):
    deleted: bool
    reassigned_drafts: int


# --- Assessment ---


class AssessmentCreate(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    employee_id: uuid.UUID
    type_code: str  # self, 180, 360
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None
    scale_id: uuid.UUID | None = None
    approver_id: uuid.UUID | None = None
    ended_at: datetime | None = None

    _validate_ended_at = field_validator("ended_at")(not_past_deadline)


class AssessmentUpdate(BaseModel):
    """Inline edit for non-terminal assessments (title, deadline).

    `ended_at` is tri-state: omitted (no change), explicit `null` (clear),
    datetime (overwrite). Use `model_fields_set` in the router to tell
    "omitted" from "explicit null".
    """

    title: str | None = Field(default=None, max_length=100)
    ended_at: datetime | None = None

    _validate_ended_at = field_validator("ended_at")(not_past_deadline)


class AssessmentRead(BaseModel):
    id: uuid.UUID
    title: str | None
    employee_id: uuid.UUID
    employee_name: str
    # HRP-333: EmployeeSummaryLine inputs for the assessee.
    employee_position_title: str | None = None
    employee_status: str | None = None
    type_code: str
    type_title: str
    status_code: str
    status_title: str
    specialization_id: uuid.UUID | None
    grade_id: uuid.UUID | None
    scale_id: uuid.UUID | None
    initiator_id: uuid.UUID
    approver_id: uuid.UUID | None
    cpa_id: uuid.UUID | None
    group_id: uuid.UUID | None = None
    tenant_id: uuid.UUID
    started_at: datetime | None
    ended_at: datetime | None
    finished_at: datetime | None
    passing_score: int | None = None
    created_at: datetime
    # HRP-185: true while a reviewer is editing per-indicator Totals.
    # Participant submissions are blocked at the API while the flag is on.
    calibration_in_progress: bool = False
    model_config = {"from_attributes": True}


class AssessmentList(BaseModel):
    items: list[AssessmentRead]
    total: int


class AssessmentDetail(AssessmentRead):
    participants: list[ParticipantRead] = []
    competence_ids: list[uuid.UUID] = []
    competences: list[AssessmentCompetenceRead] = []
    criteria_type: str | None = None
    specialization_title: str | None = None
    grade_title: str | None = None
    recommendation: AssessmentRecommendation | None = None
    results: list[AssessmentResultRead] = []
    overall_percent: int | None = None
    # Scale data is embedded so the UI keeps rendering it after Sent —
    # at that point scale_id points to a snapshot that is not in the
    # picker list (`/answer-scales` filters out snapshots).
    scale: AnswerScaleDetailRead | None = None


# --- Criteria ---


class AssessmentCompetenceRead(BaseModel):
    competence_id: uuid.UUID
    competence_title: str
    skill_level_id: uuid.UUID | None = None
    skill_level_title: str | None = None


class CompetenceCriteriaItem(BaseModel):
    competence_id: uuid.UUID
    skill_level_id: uuid.UUID | None = None


class CriteriaUpdate(BaseModel):
    """Update assessment criteria.

    criteria_type:
      - 'current_positions': resolved per employee at evaluation time, no extra params
      - 'target_position': specialization_id required; grade_id None means "all grades"
      - 'competences': competences list with optional skill_level_id per item

    passing_score: optional 0..100 threshold. For target_position+specific grade
    the default is pulled from grade_specializations.passing_score; otherwise
    falls back to 75 unless explicitly provided.
    """

    criteria_type: str = Field(
        pattern="^(current_positions|target_position|competences)$"
    )
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None
    competences: list[CompetenceCriteriaItem] = []
    passing_score: int | None = Field(default=None, ge=0, le=100)


# --- Grade Recommendation ---


class GradeRecommendationItem(BaseModel):
    grade_id: uuid.UUID
    grade_title: str | None
    sort_index: int
    percent: float
    passed: bool
    missing_percent: float | None
    excluded: bool


class AssessmentRecommendation(BaseModel):
    passing_score: int | None
    recommended_grade_id: uuid.UUID | None
    recommended_grade_title: str | None
    recommended_grade_passed: bool
    grades: list[GradeRecommendationItem] = []
    computed_at: datetime | None = None


class SpecializationOption(BaseModel):
    id: uuid.UUID
    title: str


class GradeOption(BaseModel):
    id: uuid.UUID
    title: str


# --- Participants ---


class ParticipantAdd(BaseModel):
    employee_id: uuid.UUID
    role: str = Field(pattern="^(self|manager|peer|subordinate)$")


class ParticipantRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    user_name: str | None = None
    # HRP-85: employee_id is set when the participant maps to an Employee
    # row in this tenant; external reviewers and orphaned users get None.
    # `can_view_profile` lets the UI render a link to /employees/{id}
    # without re-deriving the visibility scope client-side.
    employee_id: uuid.UUID | None = None
    # HRP-333: EmployeeSummaryLine inputs (None for external reviewers).
    position_title: str | None = None
    employee_status: str | None = None
    can_view_profile: bool = False
    external_reviewer_id: uuid.UUID | None = None
    role: str
    is_completed: bool
    external_name: str | None = None
    external_email: str | None = None
    model_config = {"from_attributes": True}


# --- GF4: External Reviewers ---


class ExternalReviewerCreate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    role: str = Field(default="external", pattern="^(peer|subordinate|external)$")


class ExternalReviewerRead(BaseModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    token: str
    name: str | None
    email: str | None
    expires_at: datetime
    completed_at: datetime | None
    share_url: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class ExternalAssessmentInfo(BaseModel):
    """Minimal assessment info visible to external reviewers (no auth)."""

    assessment_id: uuid.UUID
    employee_name: str | None = None
    type_title: str
    competences: list[ExternalCompetenceInfo] = []
    scale: AnswerScaleRead | None = None


class ExternalCompetenceInfo(BaseModel):
    id: uuid.UUID
    title: str
    indicators: list[ExternalIndicatorInfo] = []


class ExternalIndicatorInfo(BaseModel):
    id: uuid.UUID
    title: str
    weight: float


class ExternalAnswerSubmit(BaseModel):
    answers: list[ExternalAnswerItem]


class ExternalAnswerItem(BaseModel):
    indicator_id: uuid.UUID
    answer_option_id: uuid.UUID | None = None
    score: int | None = None
    comment: str | None = Field(default=None, max_length=1000)


# --- Answers ---


class AnswerRecord(BaseModel):
    participant_id: uuid.UUID
    indicator_id: uuid.UUID
    answer_option_id: uuid.UUID | None = None
    score: int | None = None
    comment: str | None = Field(default=None, max_length=1000)


# --- Results ---


class PerLevelResult(BaseModel):
    skill_level_id: uuid.UUID
    skill_level_title: str | None = None
    sort_index: int
    percent: int | None = None
    model_config = {"from_attributes": True}


class AssessmentResultRead(BaseModel):
    id: uuid.UUID
    competence_id: uuid.UUID
    avg_score: float
    calibrated_score: float | None
    percent: int | None = None
    level: AnswerScaleLevelRead | None = None
    per_level_results: list[PerLevelResult] = []
    model_config = {"from_attributes": True}


class CalibrateRequest(BaseModel):
    results: list[CalibrateItem]


class CalibrateItem(BaseModel):
    competence_id: uuid.UUID
    calibrated_score: float


class CalibratedTotalItem(BaseModel):
    """HRP-185: per-indicator Total override picked by a reviewer."""

    indicator_id: uuid.UUID
    answer_option_id: uuid.UUID


class CalibrateTotalsRequest(BaseModel):
    """HRP-185: payload for ``POST /assessments/{id}/calibration/save``."""

    totals: list[CalibratedTotalItem] = Field(default_factory=list)


# --- Detailed Results (HRP-154) ---


class DetailedRoleAnswer(BaseModel):
    role: str
    answer_title: str | None
    answer_weight: float | None
    is_neutral: bool
    answers_count: int


class DetailedQuestionComment(BaseModel):
    role: str
    user_name: str | None
    created_at: datetime
    text: str


class DetailedQuestion(BaseModel):
    indicator_id: uuid.UUID
    indicator_title: str
    roles: list[DetailedRoleAnswer]
    comments: list[DetailedQuestionComment]
    overall_avg_weight: float | None
    overall_percent: int | None
    overall_answer_title: str | None
    # HRP-185 REDO: id of the answer option whose weight is closest to the
    # computed Total — the frontend pre-populates the calibration Select
    # with it so the reviewer sees what the auto-computed Total is before
    # they touch it. When a calibrated pick is present this field tracks
    # the pinned option (mirrors `calibrated_answer_option_id`).
    overall_answer_option_id: uuid.UUID | None = None
    all_dont_know: bool
    # HRP-185: true when a reviewer pinned this indicator's Total; the
    # answer fields then carry the calibrated pick and the UI shows the
    # `calibrated` chip next to the row.
    is_calibrated: bool = False
    calibrated_answer_option_id: uuid.UUID | None = None


class DetailedSkillLevel(BaseModel):
    skill_level_id: uuid.UUID | None
    skill_level_title: str | None
    sort_index: int
    percent_for_skill_level: int | None
    all_dont_know: bool
    questions: list[DetailedQuestion]


class DetailedCompetenceResult(BaseModel):
    competence_id: uuid.UUID
    competence_title: str
    competence_type_id: uuid.UUID | None
    competence_type_title: str | None
    required_skill_level_id: uuid.UUID | None
    required_skill_level_title: str | None
    percent: int | None
    level_id: uuid.UUID | None
    level_title: str | None
    all_dont_know: bool
    skill_levels: list[DetailedSkillLevel]


class DetailedResultsResponse(BaseModel):
    assessment_id: uuid.UUID
    competences: list[DetailedCompetenceResult]


# --- Status ---


class StatusChange(BaseModel):
    status_code: str


class ScaleAssign(BaseModel):
    scale_id: uuid.UUID | None = None


# --- Mass Assessment (Groups) ---


class MassAssessmentCreate(BaseModel):
    title: str = Field(max_length=100)
    employee_ids: list[uuid.UUID] = Field(min_length=1)
    type_code: str
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None
    scale_id: uuid.UUID | None = None
    approver_id: uuid.UUID | None = None
    ended_at: datetime | None = None

    _validate_ended_at = field_validator("ended_at")(not_past_deadline)


class AssessmentGroupUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class AssessmentGroupRead(BaseModel):
    id: uuid.UUID
    title: str
    initiator_id: uuid.UUID
    assessment_count: int
    status_summary: dict[str, int] = Field(default_factory=dict)
    type_code: str | None = None
    type_title: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class AssessmentGroupDetail(AssessmentGroupRead):
    assessments: list[AssessmentRead] = []
    criteria_type: str | None = None
    specialization_id: uuid.UUID | None = None
    specialization_title: str | None = None
    grade_id: uuid.UUID | None = None
    grade_title: str | None = None
    passing_score: int | None = None
    competences: list[AssessmentCompetenceRead] = []
    scale_id: uuid.UUID | None = None
    scale: AnswerScaleDetailRead | None = None
    # HRP-37: only set on the create_mass_assessment response so the
    # frontend can render a `Created M of N` snackbar when some
    # employees were at the active-assessment cap.
    created_count: int | None = None
    requested_count: int | None = None
    skipped_capped_count: int | None = None


class GroupedAssessmentListItem(BaseModel):
    kind: str  # "single" | "group"
    assessment: AssessmentRead | None = None
    group: AssessmentGroupRead | None = None


class GroupedAssessmentList(BaseModel):
    items: list[GroupedAssessmentListItem]
    total: int


class BulkStatusChange(BaseModel):
    status_code: str


class BulkStatusSkipReasons(BaseModel):
    terminal: int = 0
    same_or_lower_status: int = 0
    already_cancelled: int = 0
    missing_criteria_or_scale: int = 0
    deadline_in_past: int = 0
    no_completed_participant: int = 0
    not_in_on_review: int = 0
    manual_in_progress_not_allowed: int = 0


class BulkStatusChangeResult(BaseModel):
    changed: int
    skipped: int
    total: int
    skipped_reasons: BulkStatusSkipReasons = BulkStatusSkipReasons()


# --- CPA ---


class CPACreate(BaseModel):
    title: str = Field(max_length=255)
    type_code: str
    scale_id: uuid.UUID | None = None
    ended_at: datetime | None = None


class CPARead(BaseModel):
    id: uuid.UUID
    title: str
    author_id: uuid.UUID
    type_code: str | None = None
    status: str
    scale_id: uuid.UUID | None
    tenant_id: uuid.UUID
    started_at: datetime | None
    ended_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    model_config = {"from_attributes": True}


class CPADetail(CPARead):
    criteria: list[CPACriteriaRead] = []
    participants: list[CPAParticipantRead] = []
    assessment_count: int = 0


# --- CPA Criteria ---


class CPACriteriaCreate(BaseModel):
    criteria_type: str = Field(pattern="^(position|point|competence)$")
    config: dict | None = None
    weight: float = 1.0


class CPACriteriaRead(BaseModel):
    id: uuid.UUID
    cpa_id: uuid.UUID
    criteria_type: str
    config: dict | None
    weight: float
    model_config = {"from_attributes": True}


# --- CPA Participants ---


class CPAParticipantAdd(BaseModel):
    user_id: uuid.UUID
    role: str = Field(pattern="^(reviewer|calibrator|observer)$")


class CPAParticipantRead(BaseModel):
    id: uuid.UUID
    cpa_id: uuid.UUID
    user_id: uuid.UUID
    user_name: str | None = None
    role: str
    model_config = {"from_attributes": True}


# --- CPA Analytics ---


class CPAAnalytics(BaseModel):
    cpa_id: uuid.UUID
    total_assessments: int
    completed_assessments: int
    ranking: list[CPARankingItem] = []
    score_distribution: dict = {}


class CPARankingItem(BaseModel):
    employee_id: uuid.UUID
    employee_name: str | None = None
    assessment_id: uuid.UUID
    avg_score: float
    rank: int


# --- PDP ---


class PDPCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    employee_id: uuid.UUID
    assessment_id: uuid.UUID | None = None
    reviewer_id: uuid.UUID | None = None
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None
    deadline: datetime | None = None

    _validate_deadline = field_validator("deadline")(not_past_deadline)


class PDPUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    deadline: datetime | None = None
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None

    model_config = {"extra": "forbid"}

    _validate_deadline = field_validator("deadline")(not_past_deadline)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> PDPUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one field must be set")
        return self


class PDPRead(BaseModel):
    id: uuid.UUID
    title: str
    employee_id: uuid.UUID
    employee_name: str | None = None
    # HRP-333: EmployeeSummaryLine inputs for the plan's employee.
    employee_position_title: str | None = None
    employee_status: str | None = None
    assessment_id: uuid.UUID | None
    author_id: uuid.UUID
    reviewer_id: uuid.UUID | None
    reviewer_name: str | None = None
    status: str
    specialization_id: uuid.UUID | None
    specialization_title: str | None = None
    grade_id: uuid.UUID | None
    grade_title: str | None = None
    total_progress: int
    deadline: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    tenant_id: uuid.UUID
    created_at: datetime
    model_config = {"from_attributes": True}


class PDPDetail(PDPRead):
    items: list[PDPItemRead] = []
    comments: list[PDPCommentRead] = []
    # HRP-13: tells the UI whether the current viewer owns this plan so it
    # can enable/disable the item-passed checkboxes and pick the right
    # action-row.
    is_owner: bool = False
    # HRP-130: true when the current viewer is the resolved reviewer for
    # this plan — either the explicit ``reviewer_id`` or the employee's
    # division manager (the same fallback used for ``reviewer_name``). The
    # UI uses this directly instead of comparing ``reviewer_id`` itself,
    # which would miss the implicit-manager case.
    is_reviewer: bool = False


class PDPItemCreate(BaseModel):
    competence_id: uuid.UUID | None = None
    title: str = Field(max_length=300)
    description: str | None = Field(default=None, max_length=1000)
    sort_index: int = 0
    entity_type: str = "custom"


class PDPItemRead(BaseModel):
    id: uuid.UUID
    competence_id: uuid.UUID | None
    title: str
    description: str | None
    sort_index: int
    is_passed: bool
    entity_type: str
    materials: list[PDPMaterialRead] = []
    model_config = {"from_attributes": True}


class PDPMaterialCreate(BaseModel):
    material_id: uuid.UUID | None = None
    title: str = Field(max_length=600)
    format: str | None = Field(default=None, max_length=100)
    link: str | None = Field(default=None, max_length=600)
    study_time: int | None = None
    sort_index: int = 0
    file_id: uuid.UUID | None = None


class PDPItemUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=1000)
    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _at_least_one_field(self) -> PDPItemUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one field must be set")
        return self


class PDPItemReorder(BaseModel):
    ordered_ids: list[uuid.UUID] = Field(min_length=1)


class PDPItemPassUpdate(BaseModel):
    # HRP-19/130: ``POST /pdp/{id}/items/{item_id}/pass`` toggles passed state.
    # ``true`` ticks the item, ``false`` clears it. Older clients that POSTed
    # an empty body get the default (= mark as passed) for backwards
    # compatibility.
    is_passed: bool = True


class PDPMaterialUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=600)
    format: str | None = Field(default=None, max_length=100)
    link: str | None = Field(default=None, max_length=600)
    study_time: int | None = None
    file_id: uuid.UUID | None = None
    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _at_least_one_field(self) -> PDPMaterialUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one field must be set")
        return self


class PDPMaterialRead(BaseModel):
    id: uuid.UUID
    material_id: uuid.UUID | None
    title: str
    format: str | None
    link: str | None
    study_time: int | None
    sort_index: int
    is_passed: bool
    file_id: uuid.UUID | None = None
    file_url: str | None = None
    file_name: str | None = None
    model_config = {"from_attributes": True}


class PDPCommentCreate(BaseModel):
    item_id: uuid.UUID | None = None
    material_id: uuid.UUID | None = None
    text: str = Field(max_length=2000)
    file_id: uuid.UUID | None = None


class PDPCommentRead(BaseModel):
    id: uuid.UUID
    pdp_id: uuid.UUID
    item_id: uuid.UUID | None
    material_id: uuid.UUID | None = None
    user_id: uuid.UUID
    user_name: str | None = None
    text: str
    file_id: uuid.UUID | None = None
    file_url: str | None = None
    file_name: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


# --- GF12: PDP Versioning ---


class PDPVersionRead(BaseModel):
    id: uuid.UUID
    pdp_id: uuid.UUID
    version_number: int
    status: str
    created_at: datetime
    model_config = {"from_attributes": True}


class PDPVersionDetail(PDPVersionRead):
    snapshot: dict
