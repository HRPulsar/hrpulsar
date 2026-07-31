from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

# --- Person ---


class PersonRead(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    middle_name: str | None = None
    email: str | None = None
    phone: str | None = None

    model_config = {"from_attributes": True}


class PersonUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)


# --- Vacancy ---


class SpecializationGradePair(BaseModel):
    """One row of the HRP-131 specialization multi-select."""

    specialization_id: uuid.UUID
    grade_ids: list[uuid.UUID] = Field(default_factory=list)


class VacancyLibraryRefs(BaseModel):
    """HRP-131 — selections from company library on Create/Edit Vacancy."""

    position_ids: list[uuid.UUID] = Field(default_factory=list)
    specialization_grade_pairs: list[SpecializationGradePair] = Field(
        default_factory=list
    )
    division_ids: list[uuid.UUID] = Field(default_factory=list)


class VacancyCreate(BaseModel):
    title: str = Field(max_length=255)
    description: str | None = None
    # HRP-180: optional Position link + spec/grade multi-select. Spec/grade
    # IDs must belong to the chosen Position when ``position_id`` is set.
    position_id: uuid.UUID | None = None
    specialization_ids: list[uuid.UUID] | None = None
    grade_ids: list[uuid.UUID] | None = None
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None
    division_id: uuid.UUID | None = None
    # HRP-360: defaults to the creating user when omitted.
    hiring_manager_id: uuid.UUID | None = None
    tasks_main: dict | None = None
    tasks_additional: dict | None = None
    tasks_kpi: dict | None = None
    employment_type: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=255)
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = Field(default=None, max_length=10)
    language: str = Field(default="en", max_length=10)
    # HRP-135
    requirements: str | None = None
    responsibilities: str | None = None
    conditions: str | None = None
    # HRP-131
    library_refs: VacancyLibraryRefs | None = None


class VacancyUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    # HRP-180
    position_id: uuid.UUID | None = None
    specialization_ids: list[uuid.UUID] | None = None
    grade_ids: list[uuid.UUID] | None = None
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None
    division_id: uuid.UUID | None = None
    hiring_manager_id: uuid.UUID | None = None
    tasks_main: dict | None = None
    tasks_additional: dict | None = None
    tasks_kpi: dict | None = None
    employment_type: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=255)
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = Field(default=None, max_length=10)
    language: str | None = Field(default=None, max_length=10)
    status: str | None = Field(default=None, max_length=50)
    requirements: str | None = None
    responsibilities: str | None = None
    conditions: str | None = None
    library_refs: VacancyLibraryRefs | None = None


# --- HRP-136 vacancy competences ---


class VacancyCompetenceSpec(BaseModel):
    competence_id: uuid.UUID
    skill_level_ids: list[uuid.UUID] = Field(default_factory=list)
    source: Literal["manual", "library", "ai"] = "manual"


class VacancyCompetencesUpdate(BaseModel):
    competences: list[VacancyCompetenceSpec] = Field(default_factory=list)


class VacancyCompetenceRead(BaseModel):
    id: uuid.UUID
    vacancy_id: uuid.UUID
    competence_id: uuid.UUID
    skill_level_ids: list[uuid.UUID] = Field(default_factory=list)
    source: str

    model_config = {"from_attributes": True}


# --- HRP-135 attachments ---


class VacancyAttachmentRead(BaseModel):
    id: uuid.UUID
    vacancy_id: uuid.UUID
    file_id: uuid.UUID | None = None
    filename: str
    mime_type: str
    size_bytes: int
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class VacancyDictionaryRef(BaseModel):
    """Compact dictionary_item reference for VacancyRead.specializations / grades."""

    id: uuid.UUID
    title: str | None = None


class VacancyRead(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    # HRP-180
    position_id: uuid.UUID | None = None
    position_title: str | None = None
    specializations: list[VacancyDictionaryRef] = Field(default_factory=list)
    grades: list[VacancyDictionaryRef] = Field(default_factory=list)
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None
    division_id: uuid.UUID | None = None
    status: str
    owner_id: uuid.UUID | None = None
    hiring_manager_id: uuid.UUID | None = None
    tasks_main: dict | None = None
    tasks_additional: dict | None = None
    tasks_kpi: dict | None = None
    employment_type: str | None = None
    location: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    language: str
    # HRP-344: HRP-135 text fields were persisted but never returned,
    # so the form showed them empty after save.
    requirements: str | None = None
    responsibilities: str | None = None
    conditions: str | None = None
    close_resolution: str | None = None
    close_reason: str | None = None
    closed_at: datetime | None = None
    archived_at: datetime | None = None
    archived_by: uuid.UUID | None = None
    version: int = 1
    # HRP-348: the manager-assessment sheet and the vacancy Assessment
    # Scale block need the bound scale; ``response_model`` used to strip
    # these because they were missing from the schema.
    assessment_scale_id: uuid.UUID | None = None
    assessment_scale_snapshot: dict | None = None
    created_at: datetime
    updated_at: datetime
    # Joined fields (populated in service layer)
    owner_name: str | None = None
    hiring_manager_name: str | None = None
    specialization_title: str | None = None
    grade_title: str | None = None
    division_name: str | None = None
    candidates_count: int = 0
    has_profile: bool = False
    active_invites_count: int = 0

    model_config = {"from_attributes": True}


class HiringManagerOption(BaseModel):
    """HRP-360: admin-tier user selectable as a vacancy hiring manager."""

    id: uuid.UUID
    full_name: str
    email: str


class VacancyCloseData(BaseModel):
    resolution: Literal["hired", "closed_no_hire", "cancelled"]
    hired_candidate_id: uuid.UUID | None = None
    close_reason: str | None = None


# --- Candidate ---


class CandidateCreate(BaseModel):
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    source: str | None = Field(default=None, max_length=50)
    notes: str | None = None


class CandidateUpdate(BaseModel):
    source: str | None = Field(default=None, max_length=50)
    notes: str | None = None


class CandidateRead(BaseModel):
    id: uuid.UUID
    person_id: uuid.UUID
    person: PersonRead
    source: str | None = None
    notes: str | None = None
    resumes_count: int = 0
    is_employee: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


# --- CandidateVacancy ---


class CandidateVacancyCreate(BaseModel):
    candidate_id: uuid.UUID
    vacancy_id: uuid.UUID
    stage_id: uuid.UUID | None = None


class CandidateVacancyStatusUpdate(BaseModel):
    stage_id: uuid.UUID
    comment: str | None = None


class CandidateVacancyRead(BaseModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    vacancy_id: uuid.UUID
    stage_id: uuid.UUID | None = None
    status: str
    status_history: list = []
    ranking_score: float | None = None
    stage_name: str | None = None
    candidate_name: str | None = None
    vacancy_title: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Funnel Stages ---


class VacancyStageCreate(BaseModel):
    name: str = Field(max_length=100)
    code: str = Field(max_length=50)
    sort_order: int = 0
    is_terminal: bool = False
    color: str | None = Field(default=None, max_length=20)


class VacancyStageUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    code: str | None = Field(default=None, max_length=50)
    sort_order: int | None = None
    is_terminal: bool | None = None
    color: str | None = Field(default=None, max_length=20)


class VacancyStageRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    vacancy_id: uuid.UUID | None = None
    name: str
    code: str
    sort_order: int
    is_terminal: bool
    # HRP-181 REDO: ``stage_type`` is the canonical source of truth for the
    # funnel classification. ``is_terminal`` stays as a denormalised mirror
    # so legacy callers keep working.
    stage_type: str = "active"
    color: str | None = None

    model_config = {"from_attributes": True}


# --- HRP-181 REDO: canonical candidate add / list / card ---


class CandidateManualCreate(BaseModel):
    """Manual add candidate to a vacancy.

    Either ``email`` or ``phone`` must be provided alongside ``full_name``
    (FR-04). Optional fields cover the inline shortcuts on the modal:
    LinkedIn / location / current position / years of experience are all
    self-reported, the parser does not run on this path.
    """

    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    linkedin_url: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=255)
    current_position: str | None = Field(default=None, max_length=255)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    source: str | None = Field(default=None, max_length=50)
    notes: str | None = None
    # When the client has already confirmed the duplicate-detect prompt
    # ("link to existing candidate"), it sends ``link_candidate_id`` and
    # the server skips creating a new Candidate row.
    link_candidate_id: uuid.UUID | None = None


class CandidateCanonicalRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    full_name: str
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    current_position: str | None = None
    years_of_experience: int | None = None
    source: str | None = None
    notes: str | None = None
    parsed_resume_jsonb: dict | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CandidateVacancyApplicationRead(BaseModel):
    """Compact CandidateVacancy view for the candidate full-card."""

    cv_id: uuid.UUID
    vacancy_id: uuid.UUID
    vacancy_title: str | None = None
    stage_id: uuid.UUID | None = None
    stage_name: str | None = None
    stage_type: str | None = None
    status: str
    manager_score: float | None = None
    ai_score: float | None = None
    ai_verdict: str
    ai_verdict_summary: str | None = None
    # HRP-204: surface the active run mode so the candidate card chips
    # can render the ``[resume only]`` / ``[full]`` sub-badge.
    ai_analysis_mode: str | None = None
    ai_data_completeness: str | None = None
    added_at: datetime


class CandidateFileSummary(BaseModel):
    id: uuid.UUID
    file_type: str
    original_filename: str
    mime_type: str
    file_size: int
    parse_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CandidateCanonicalCardRead(CandidateCanonicalRead):
    """Full card: canonical fields + applications + files.

    The ``experience`` / ``education`` / ``skills`` / ``languages`` blocks
    live inside ``parsed_resume_jsonb``; the client renders them off that
    payload so the card stays one round-trip.
    """

    vacancy_applications: list[CandidateVacancyApplicationRead] = Field(
        default_factory=list
    )
    candidate_files: list[CandidateFileSummary] = Field(default_factory=list)


class CandidateCanonicalPatch(BaseModel):
    """Inline-edit any visible section of the candidate card.

    ``parsed_resume_jsonb`` is a full overwrite — the card surfaces a
    "edit experience/skills" inline action that ships the whole block back.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    linkedin_url: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=255)
    current_position: str | None = Field(default=None, max_length=255)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    source: str | None = Field(default=None, max_length=50)
    notes: str | None = None
    parsed_resume_jsonb: dict | None = None


class DivergentCompetencePreview(BaseModel):
    """Tooltip-row on the Divergence badge — top-5 cells (HRP-267)."""

    competence_id: uuid.UUID
    competence_name: str
    manager_score: float | None = None
    ai_score: float | None = None


class CandidateVacancyEnrichedRead(BaseModel):
    """List row for the vacancy candidates table (FR-09).

    ``score_divergence`` is precomputed server-side off the spec threshold
    (1.0 on the tenant assessment scale, comparing ``manager_score`` with
    ``ai_score_normalized`` — see ``compute_score_divergence``) so the UI
    does not need to recheck.

    HRP-267 added the % match aggregates: ``manager_percent`` /
    ``ai_percent`` mirror what the Compact matrix shows so the candidates
    table can sort by either side; ``divergence_count`` counts cells
    where ``abs(manager_avg - ai_score) >= tenant.divergence_threshold``;
    ``divergence_top`` previews up to 5 of those cells for the tooltip
    on the Divergence column badge.
    """

    id: uuid.UUID
    candidate_id: uuid.UUID
    vacancy_id: uuid.UUID
    candidate_name: str
    last_position: str | None = None
    years_of_experience: int | None = None
    stage_id: uuid.UUID | None = None
    stage: VacancyStageRead | None = None
    status: str
    manager_score: float | None = None
    ai_score: float | None = None
    # HRP-274: raw ``ai_score`` is on the canonical 0..1 LLM scale;
    # ``ai_score_normalized`` rebases it onto the tenant's active
    # ``ScaleConfig.max_value`` (identity fallback when no scale is
    # active) so it is comparable with ``manager_score``. The candidates
    # table toggles between the two.
    ai_score_normalized: float | None = None
    score_divergence: bool = False
    # HRP-267 — % match aggregates + per-tenant Compact-matrix divergence.
    manager_percent: float | None = None
    ai_percent: float | None = None
    divergence_count: int = 0
    divergence_top: list[DivergentCompetencePreview] = Field(default_factory=list)
    ai_readiness: str
    ai_verdict: str
    ai_verdict_summary: str | None = None
    ai_key_strength: str | None = None
    ai_key_risk: str | None = None
    ai_risk_mitigation: str | None = None
    # HRP-204 — mode of the active AIAnalysisRun and its
    # ``data_completeness``. ``None`` until the first run completes.
    ai_analysis_mode: str | None = None
    ai_data_completeness: str | None = None
    version: int
    added_at: datetime


class CandidateVacancyPatch(BaseModel):
    """Stage / status / manager_score mutation. AI block stays internal —
    the parser and verdict generator write it, the recruiter cannot edit
    it through this endpoint."""

    stage_id: uuid.UUID | None = None
    status: str | None = Field(default=None, max_length=50)
    manager_score: float | None = Field(default=None, ge=0, le=10)
    comment: str | None = None


# --- HRP-181 REDO Stage 3: bulk resume upload + parsing poll ---


class BulkResumeUploadItem(BaseModel):
    """Ack row returned by ``POST /vacancies/{id}/resumes/bulk-upload``.

    The client uses ``file_id`` to drive the parsing-status poll and the
    eventual ``BatchFinalizeFile`` payload.
    """

    file_id: uuid.UUID
    original_filename: str
    mime_type: str
    file_size: int
    parse_status: str


class ResumeParseStatusItem(BaseModel):
    """Per-file row inside ``GET /vacancies/{id}/resumes/parsing-status``."""

    file_id: uuid.UUID
    parse_status: str
    original_filename: str
    full_name: str | None = None
    email: str | None = None
    last_position: str | None = None
    error: str | None = None


class ResumeParseStatusResponse(BaseModel):
    counts: dict[str, int]
    files: list[ResumeParseStatusItem] = Field(default_factory=list)


class ResumeDedupPreviewItem(BaseModel):
    """One file's duplicate-detect verdict.

    ``existing_candidate_id`` is set only when ``parsed_email`` matches an
    active candidate in the tenant; the modal shows a "link or create new"
    chip when this is non-null.
    """

    file_id: uuid.UUID
    parsed_email: str | None = None
    existing_candidate_id: uuid.UUID | None = None
    existing_candidate_full_name: str | None = None


class BatchFinalizeFile(BaseModel):
    file_id: uuid.UUID
    # When the client confirmed the dup prompt, ``link_candidate_id`` is
    # populated so the file lands on an existing candidate. Otherwise the
    # endpoint creates a fresh canonical candidate.
    link_candidate_id: uuid.UUID | None = None


class BatchFinalizeRequest(BaseModel):
    files: list[BatchFinalizeFile] = Field(default_factory=list)


class VacancyStageReplaceItem(BaseModel):
    """One stage in a per-vacancy override (PUT /vacancies/.../stages).

    ``id`` is present when the client wants to keep / update an existing
    override row; absent for newly added stages. Anything previously
    present and not in the payload is deleted (subject to the
    candidates-attached guard, which returns 409 with
    ``affected_candidate_count``).
    """

    id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=50)
    sort_order: int = 0
    stage_type: Literal[
        "active",
        "terminal_positive",
        "terminal_negative",
        "terminal_neutral",
    ] = "active"
    color: str | None = Field(default=None, max_length=20)


class VacancyStagesReplace(BaseModel):
    stages: list[VacancyStageReplaceItem] = Field(default_factory=list)


# --- Resume ---


class ResumeRead(BaseModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    original_filename: str
    mime_type: str
    file_size: int
    parsed_data: dict | None = None
    parse_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- VacancyProfile ---


class CompetenceItem(BaseModel):
    group: str
    subgroup: str
    name: str
    criticality: Literal["critical", "important", "desirable"]
    why_important: str
    how_manifests: str
    indicator_question: str
    good_answer: str
    acceptable_answer: str
    poor_answer: str


class VacancyProfileRead(BaseModel):
    id: uuid.UUID
    vacancy_id: uuid.UUID
    profile_data: dict | None = None
    version: int
    language: str
    coverage_note: str | None = None
    generated_by: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class VacancyProfileUpdate(BaseModel):
    profile_data: dict
    # HRP-339: optimistic lock — the version the editor loaded. When set,
    # the save is rejected with 409 if the profile moved on underneath
    # (generation finished in another tab, another recruiter saved).
    base_version: int | None = None


class VacancyProfileGenerateRequest(BaseModel):
    """HRP-134 REDO: extra recruiter context for the Generate matrix modal.

    Both fields are optional — an empty body keeps the legacy fire-and-
    forget call site (the ``Regenerate`` button) working unchanged.
    """

    clarification: str | None = None


class VacancyProfileSessionApplyRequest(BaseModel):
    """HRP-235 REDO (QA case 4): persist a reviewed generation result.

    ``session_id`` names the ``ready`` session whose parked payload was
    reviewed; ``profile_data`` is the recruiter's kept + edited subset of
    it (the review dialog applies checkbox selection and inline edits
    client-side before submitting).
    """

    session_id: uuid.UUID
    profile_data: dict


class VacancyProfileSessionCancelRequest(BaseModel):
    """HRP-134 REDO: optional target for the session-cancel endpoint.

    ``session_id`` pins the cancel to one specific session so dismissing
    an old failed banner cannot race a newer running generation (second
    tab / second recruiter). Omitted or empty body keeps the legacy
    latest-match behaviour for API compatibility.
    """

    session_id: uuid.UUID | None = None


# --- CandidateQuestion ---


class QuestionCreate(BaseModel):
    question_text: str
    good_answer: str = ""
    acceptable_answer: str = ""
    poor_answer: str = ""
    resume_fragment: str | None = None
    competence_id: uuid.UUID | None = None
    purpose: Literal["clarification", "depth", "risk", "motivation", "fit"] = (
        "clarification"
    )
    priority: Literal["must", "should", "nice_to_ask"] = "should"


class QuestionUpdate(BaseModel):
    question_text: str | None = None
    good_answer: str | None = None
    acceptable_answer: str | None = None
    poor_answer: str | None = None
    resume_fragment: str | None = None
    competence_id: uuid.UUID | None = None
    purpose: Literal["clarification", "depth", "risk", "motivation", "fit"] | None = (
        None
    )
    priority: Literal["must", "should", "nice_to_ask"] | None = None


class QuestionRead(BaseModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    vacancy_id: uuid.UUID
    competence_id: uuid.UUID | None = None
    question_text: str
    good_answer: str
    acceptable_answer: str
    poor_answer: str
    resume_fragment: str | None = None
    purpose: str
    priority: str
    is_manual: bool
    sort_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


# --- HumanAssessment ---


class AssessmentScoreCreate(BaseModel):
    competence_id: uuid.UUID
    score: float | None = None
    comment: str | None = None


class AssessmentScoreUpdate(BaseModel):
    score: float | None = None
    comment: str | None = None


class AssessmentRevertRequest(BaseModel):
    """Body for ``POST .../assessments/{comp}/evaluators/{ev}/revert``.

    ``audit_event_id`` is the timeline row the user picked in the
    Versions panel; the service restores ``old_score`` from that row.
    """

    audit_event_id: uuid.UUID


class AssessmentScoreRead(BaseModel):
    id: uuid.UUID
    candidate_vacancy_id: uuid.UUID
    competence_id: uuid.UUID
    evaluator_id: uuid.UUID
    score: float | None = None
    comment: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- AssessmentInvite ---


class InviteCreate(BaseModel):
    email: str = Field(max_length=255)
    evaluator_name: str | None = Field(default=None, max_length=255)
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InviteRead(BaseModel):
    id: uuid.UUID
    candidate_vacancy_id: uuid.UUID
    token: str
    email: str
    evaluator_name: str | None = None
    status: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Interview (R3a + HRP-202) ---


InterviewType = Literal["audio", "video", "text_transcript", "undecided"]


class InterviewCreate(BaseModel):
    """Schedule-an-interview payload (HRP-202).

    All fields are optional so the existing R3a callers (legacy minimal
    payload of ``interviewer_id`` + ``interview_date`` + ``notes``) keep
    working. ``interviewers`` is the HRP-202 multi-assignee list and
    takes precedence over the legacy ``interviewer_id`` when both are
    given.
    """

    title: str | None = Field(default=None, max_length=255)
    interviewer_id: uuid.UUID | None = None
    interviewers: list[uuid.UUID] | None = None
    interview_date: datetime | None = None
    timezone: str | None = Field(default=None, max_length=50)
    duration_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    type: InterviewType | None = None
    round_id: uuid.UUID | None = None
    notes: str | None = None


class InterviewUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    interviewer_id: uuid.UUID | None = None
    interviewers: list[uuid.UUID] | None = None
    interview_date: datetime | None = None
    timezone: str | None = Field(default=None, max_length=50)
    duration_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    type: InterviewType | None = None
    round_id: uuid.UUID | None = None
    status: str | None = Field(default=None, max_length=50)
    notes: str | None = None


class InterviewSegmentRead(BaseModel):
    id: uuid.UUID
    interview_id: uuid.UUID
    speaker: str
    start_sec: float
    end_sec: float
    text: str
    confidence: float | None = None

    model_config = {"from_attributes": True}


class InterviewSegmentUpdate(BaseModel):
    speaker: str | None = Field(default=None, max_length=50)
    text: str | None = None
    start_sec: float | None = None
    end_sec: float | None = None


class TranscriptUpdate(BaseModel):
    transcript: str


class AIAssessmentRead(BaseModel):
    id: uuid.UUID
    interview_id: uuid.UUID
    competence_id: uuid.UUID
    score: float | None = None
    status: str
    citations: list = Field(default_factory=list)
    reasoning: str | None = None

    model_config = {"from_attributes": True}


class InterviewRead(BaseModel):
    id: uuid.UUID
    candidate_vacancy_id: uuid.UUID
    title: str | None = None
    type: str | None = None
    timezone: str | None = None
    duration_minutes: int | None = None
    interviewer_id: uuid.UUID | None = None
    interviewer_ids: list[uuid.UUID] = Field(default_factory=list)
    interview_date: datetime | None = None
    duration_seconds: int | None = None
    audio_file_id: uuid.UUID | None = None
    video_file_id: uuid.UUID | None = None
    transcript_file_id: uuid.UUID | None = None
    file_s3_key: str | None = None
    file_size_bytes: int | None = None
    file_mime: str | None = None
    transcript: str | None = None
    notes: str | None = None
    status: str
    av_status: str | None = None
    av_scanned_at: datetime | None = None
    version: int = 1
    archived_at: datetime | None = None
    created_by: uuid.UUID | None = None
    transcription_provider: str | None = None
    transcription_status: str
    analysis_status: str
    transcription_error: str | None = None
    analysis_error: str | None = None
    auto_process: bool = False
    consent_signed_at: datetime | None = None
    consent_template_id: uuid.UUID | None = None
    segments: list[InterviewSegmentRead] = Field(default_factory=list)
    ai_assessments: list[AIAssessmentRead] = Field(default_factory=list)
    analysis: dict | None = None

    model_config = {"from_attributes": True}


# --- Chunked upload ---


class InitUploadRequest(BaseModel):
    filename: str = Field(max_length=255)
    mime_type: str = Field(max_length=120)
    size_bytes: int = Field(ge=1)
    # HRP-385: transcripts (pdf/txt) are a first-class upload kind. The
    # literal used to allow audio/video only, which forced both frontend
    # surfaces to send kind="audio" for a PDF — and the MIME/kind
    # cross-check then rejected it with 422, so no transcript could ever
    # be uploaded and the interview stayed "scheduled".
    kind: Literal["audio", "video", "text_transcript"]


class InitUploadResponse(BaseModel):
    upload_id: str
    session_id: uuid.UUID | None = None
    path: str
    part_size: int
    total_parts: int


class PartUrlRequest(BaseModel):
    upload_id: str
    part_number: int = Field(ge=1, le=10000)


class PartUrlResponse(BaseModel):
    part_number: int
    url: str
    expires_in: int


class CompletePart(BaseModel):
    part_number: int = Field(ge=1, le=10000)
    etag: str


class CompleteUploadRequest(BaseModel):
    upload_id: str
    parts: list[CompletePart]
    # HRP-202 REDO: chain transcribe -> analyze automatically after the
    # upload lands. Both hops stay behind the regular billing wrappers.
    auto_process: bool = False


class AbortUploadRequest(BaseModel):
    upload_id: str


# --- HRP-202 upload sessions (TUS-style resume) ---


class UploadSessionRead(BaseModel):
    """Snapshot of an in-flight upload session for the resume flow."""

    id: uuid.UUID
    interview_id: uuid.UUID
    filename: str
    mime_type: str
    kind: str
    total_size: int
    uploaded_bytes: int
    part_size: int
    s3_upload_id: str
    s3_parts: list = Field(default_factory=list)
    status: str
    expires_at: datetime

    model_config = {"from_attributes": True}


class UploadChunkAck(BaseModel):
    """Sent by the client with each chunk PATCH (TUS-style).

    The actual bytes are PUT directly to S3 from the browser; this
    payload tells the backend the chunk landed so it can update the
    persistent offset.
    """

    part_number: int = Field(ge=1, le=10000)
    etag: str
    size: int = Field(ge=0)


class TextTranscriptRequest(BaseModel):
    """Inline-paste transcript (HRP-202): no media file needed."""

    text: str = Field(min_length=1)


class InterviewArchiveRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


# --- Consent (R3a) ---


class ConsentTemplateCreate(BaseModel):
    name: str = Field(max_length=100)
    body: str
    language: str = Field(default="en", max_length=10)
    is_active: bool = True


class ConsentTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    body: str | None = None
    language: str | None = Field(default=None, max_length=10)
    is_active: bool | None = None


class ConsentTemplateRead(BaseModel):
    id: uuid.UUID
    name: str
    body: str
    language: str
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConsentSendRequest(BaseModel):
    email: EmailStr
    template_id: uuid.UUID | None = None
    expires_in_days: int = Field(default=14, ge=1, le=60)


class ConsentRequestRead(BaseModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    template_id: uuid.UUID
    email: str
    status: str
    expires_at: datetime
    signed_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConsentTokenView(BaseModel):
    candidate_id: uuid.UUID
    candidate_name: str
    template_name: str
    template_body: str
    template_language: str
    status: str
    expires_at: datetime
    signed_at: datetime | None = None


class ConsentSignResult(BaseModel):
    signed_at: datetime
    status: str


# --- Reports + Templates (R4a) ---

# Section codes mirror RECRUITING_MODULE.md §11.2 SCR-81. Frontend renders
# one chip per code; the worker maps each to a sheet in the XLSX.
ReportSectionCode = Literal[
    "vacancy_summary",
    "competence_profile",
    "candidates_summary",
    "comparison_grid",
    "interview_analysis",
    "human_assessments",
    "process_findings",
    "red_flags",
    "verdict",
]


REPORT_SECTION_CODES: tuple[str, ...] = (
    "vacancy_summary",
    "competence_profile",
    "candidates_summary",
    "comparison_grid",
    "interview_analysis",
    "human_assessments",
    "process_findings",
    "red_flags",
    "verdict",
)


class ReportTemplateCreate(BaseModel):
    name: str = Field(max_length=100)
    sections: list[ReportSectionCode] = Field(default_factory=list)
    is_active: bool = True
    is_default: bool = False
    template_data: dict | None = None


class ReportTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    sections: list[ReportSectionCode] | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    template_data: dict | None = None


class ReportTemplateRead(BaseModel):
    id: uuid.UUID
    name: str
    sections: list[str] = Field(default_factory=list)
    is_active: bool
    is_default: bool
    template_data: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReportGenerateRequest(BaseModel):
    template_id: uuid.UUID | None = None
    sections: list[ReportSectionCode] | None = None
    # HRP-268 — strips Detail-sheet ``process_findings`` to a positive
    # reframe for the hiring-manager audience; full text otherwise.
    audience: Literal["recruiter", "hiring_manager"] | None = None
    # HRP-268 — optional whitelist; when present only these candidates
    # land in the Summary / Matrix / Detail sheets. Empty / None means
    # every active candidate-vacancy row on the vacancy.
    candidate_vacancy_ids: list[uuid.UUID] | None = None


class ReportGenerateResponse(BaseModel):
    export_id: uuid.UUID
    task_id: str


class ReportExportRead(BaseModel):
    id: uuid.UUID
    vacancy_id: uuid.UUID
    template_id: uuid.UUID | None = None
    template_name: str | None = None
    sections: list[str] = Field(default_factory=list)
    status: str
    error: str | None = None
    file_id: uuid.UUID | None = None
    download_url: str | None = None
    requested_by: uuid.UUID | None = None
    requested_by_name: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


# --- R4d: Report XLSX preview (FR-23, SCR-83) ---


class ReportPreviewSheet(BaseModel):
    name: str
    cells: list[list[str | int | float | None]] = Field(default_factory=list)


class ReportPreviewRead(BaseModel):
    export_id: uuid.UUID
    sheets: list[ReportPreviewSheet] = Field(default_factory=list)
    truncated: bool = False  # True when a sheet was clipped to the row/col cap


# --- Candidate comparison (R4a, SCR-55/56) ---


class ComparisonCellRead(BaseModel):
    candidate_id: uuid.UUID
    score: float | None = None
    source: Literal["human", "ai", "missing"] = "missing"


class ComparisonCompetenceRead(BaseModel):
    competence_id: str
    name: str
    group: str | None = None
    criticality: str | None = None
    cells: list[ComparisonCellRead]
    divergence: float | None = None  # max - min over scored cells


class ComparisonCandidateRead(BaseModel):
    id: uuid.UUID
    candidate_vacancy_id: uuid.UUID
    name: str
    status: str | None = None
    ranking_score: float | None = None


class ComparisonRead(BaseModel):
    vacancy_id: uuid.UUID
    candidates: list[ComparisonCandidateRead]
    competences: list[ComparisonCompetenceRead]


# --- R4c: Onboarding ---


OnboardingStep = Literal[
    "welcome",
    "vacancy_created",
    "candidate_invited",
    "interview_scheduled",
    "report_reviewed",
    "done",
]


class OnboardingState(BaseModel):
    step: OnboardingStep = "welcome"
    dismissed_at: datetime | None = None
    demo_seeded_at: datetime | None = None


# --- R4c: Report sharing (FR-22, SCR-84) ---


class ReportShareCreate(BaseModel):
    recipients: list[EmailStr] = Field(default_factory=list, max_length=20)
    expires_in_days: int = Field(default=7, ge=1, le=60)
    message: str | None = Field(default=None, max_length=200)


class ReportShareRead(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    token: str
    share_url: str
    expires_at: datetime
    recipients: list[str]
    message: str | None
    open_count: int
    last_opened_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    created_by: uuid.UUID | None


class ReportSharePublicView(BaseModel):
    report_id: uuid.UUID
    vacancy_title: str | None
    generated_at: datetime | None
    expires_at: datetime
    download_url: str | None


# --- R4c: Analytics ---


class FunnelStageStat(BaseModel):
    stage_id: uuid.UUID | None
    stage_name: str | None
    candidate_count: int
    median_seconds_in_stage: float | None


class VacancyAnalytics(BaseModel):
    vacancy_id: uuid.UUID
    funnel: list[FunnelStageStat]
    win_loss: dict[str, int]
    total_candidates: int


class SummaryVacancyEntry(BaseModel):
    vacancy_id: uuid.UUID
    title: str
    metric_value: float | None


class AnalyticsSummary(BaseModel):
    top_velocity: list[SummaryVacancyEntry]
    top_drop_off: list[SummaryVacancyEntry]
    ai_variance_by_recruiter: list[dict]


class RadarScore(BaseModel):
    competence_id: uuid.UUID
    competence_name: str | None
    score: float | None


class RadarCandidate(BaseModel):
    candidate_id: uuid.UUID
    name: str | None
    scores: list[RadarScore]


class ComparisonRadar(BaseModel):
    vacancy_id: uuid.UUID
    candidates: list[RadarCandidate]
    competences: list[ComparisonCompetenceRead]


# ---------------------------------------------------------------------------
# HRP-205: question sets / questions
# ---------------------------------------------------------------------------


QuestionGoal = Literal["clarification", "depth", "risk", "motivation", "fit"]
QuestionPriority = Literal["must", "should", "nice_to_ask"]
QuestionSource = Literal[
    "ai_generated", "manual", "from_competency_indicator", "from_blind_spot"
]
SetType = Literal["pre_interview", "interview_round", "final"]
GenerationMode = Literal["initial", "regenerated", "dynamic_next", "manual"]
SetStatus = Literal["ready", "generating", "failed", "sample"]


class QuestionRead2(BaseModel):
    id: uuid.UUID
    question_set_id: uuid.UUID
    text: str
    goal: QuestionGoal
    priority: QuestionPriority
    competence_id: uuid.UUID | None = None
    resume_anchor_jsonb: dict | None = None
    expected_answer_indicators: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    rationale: str | None = None
    source: QuestionSource
    source_blind_spot_id: uuid.UUID | None = None
    sort_order: int
    status: Literal["active", "removed"]
    covered_at: datetime | None = None
    covered_by: uuid.UUID | None = None
    covered_method: Literal["manual", "auto_from_transcript"] | None = None
    version: int

    model_config = {"from_attributes": True}


class QuestionSetRead(BaseModel):
    id: uuid.UUID
    candidate_vacancy_id: uuid.UUID
    round_id: uuid.UUID | None = None
    set_type: SetType
    name: str
    status: SetStatus
    generation_mode: GenerationMode
    source_round_ids: list[uuid.UUID] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    coverage_note: str | None = None
    created_by: uuid.UUID | None = None
    archived_at: datetime | None = None
    version: int
    created_at: datetime
    questions: list[QuestionRead2] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class GenerateQuestionSetRequest(BaseModel):
    """Trigger AI generation for a candidate-vacancy.

    ``mode=initial`` — first set, fresh.
    ``mode=regenerated`` — replace AI questions in target_set_id, keep manual.
    ``mode=dynamic_next`` — new set after one or more rounds, sees prior
    sets + transcripts; ``source_round_ids`` lists which rounds it covers.
    """

    mode: GenerationMode = "initial"
    round_id: uuid.UUID | None = None
    source_round_ids: list[uuid.UUID] | None = None
    target_set_id: uuid.UUID | None = None
    set_type: SetType = "pre_interview"
    name: str | None = None


class QuestionCreate2(BaseModel):
    """Custom question add (FR-13 — manual + from_competency_indicator)."""

    text: str = Field(min_length=1)
    goal: QuestionGoal = "clarification"
    priority: QuestionPriority = "should"
    competence_id: uuid.UUID | None = None
    resume_anchor_jsonb: dict | None = None
    expected_answer_indicators: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    rationale: str | None = None
    source: Literal["manual", "from_competency_indicator"] = "manual"


class QuestionUpdate2(BaseModel):
    text: str | None = Field(default=None, min_length=1)
    goal: QuestionGoal | None = None
    priority: QuestionPriority | None = None
    competence_id: uuid.UUID | None = None
    rationale: str | None = None
    expected_answer_indicators: list[str] | None = None
    follow_ups: list[str] | None = None
    # Toggle covered state. ``True`` stamps covered_at + covered_method
    # = 'manual'. ``False`` clears it.
    covered: bool | None = None
    # Cross-set move
    move_to_set_id: uuid.UUID | None = None


class QuestionSetExportRequest(BaseModel):
    format: Literal["compact", "full", "cards"] = "compact"
    include_indicators: bool = True
    include_follow_ups: bool = True
    include_rationale: bool = False
    include_resume_anchor: bool = True
    language: str | None = None
    sort: Literal["priority", "competence", "sort_order"] = "sort_order"


class QuestionsPDFExportRequest(BaseModel):
    include_good: bool = True
    include_acceptable: bool = True
    include_poor: bool = True


# ---------------------------------------------------------------------------
# HRP-204: AI analysis (resume-only / full / top-up + bulk + history)
# ---------------------------------------------------------------------------


AIAnalysisMode = Literal["resume_only", "full", "topup_to_full"]


class AIAnalysisEnqueueRequest(BaseModel):
    """Single-candidate analyze trigger.

    ``mode`` selects the entry point:

    * ``resume_only`` — 20 cr, no transcript required.
    * ``full`` — 40 cr, redirects to the legacy interview-page entry
      point (kept for parity with existing UI flows; requires an
      ``interview_id``).
    * ``topup_to_full`` — 20 cr, upgrades a prior resume-only run to
      full when an interview transcript exists. Backend re-validates
      eligibility (30-day window, profile unchanged) and 409s with a
      structured reason on failure.
    """

    mode: AIAnalysisMode = "resume_only"
    interview_id: uuid.UUID | None = None


class ResumeExcerptRead(BaseModel):
    """HRP-271 — narrow public mirror of the prompt-side ``ResumeExcerpt``.

    Surfaced on ``AIAnalysisRunRead`` so the UI can render click-to-locate
    citations without receiving the full ``analysis_data`` blob (which
    carries role-filtered fields like ``red_flags`` and process findings).
    """

    section: Literal["experience", "education", "skills", "projects", "summary"]
    excerpt_text: str
    source_company: str | None = None
    source_period: str | None = None


class AIAnalysisRunRead(BaseModel):
    id: uuid.UUID
    candidate_vacancy_id: uuid.UUID
    mode: Literal["resume_only", "full"]
    # HRP-270: ``cancelled`` joins the prior four states.
    status: Literal["pending", "processing", "completed", "failed", "cancelled"]
    data_completeness: str | None = None
    interview_id: uuid.UUID | None = None
    verdict: str | None = None
    verdict_summary: str | None = None
    key_strength: str | None = None
    key_risk: str | None = None
    risk_mitigation: str | None = None
    recommendation_for_next_step: str | None = None
    ai_score: float | None = None
    vacancy_profile_version: int | None = None
    archived_at: datetime | None = None
    replaced_by_id: uuid.UUID | None = None
    supersedes_id: uuid.UUID | None = None
    created_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    # HRP-270: per-stage progress + cancel bookkeeping. ``current_stage``
    # is one of the slugs in
    # ``app.modules.recruitment.ai_analysis_stages.ALL_STAGES``; ``None``
    # while the run is still ``pending`` or already terminal.
    current_stage: str | None = None
    cancelled_at: datetime | None = None
    cancelled_by_id: uuid.UUID | None = None
    # HRP-271: resume_only runs surface verbatim ``ResumeExcerpt`` items
    # (per-competence) so the UI can render click-to-locate citations.
    # Populated by ``resume_analysis_service.serialize_run_for_read``
    # from ``analysis_data['competence_assessments'][*]['resume_excerpts']``
    # — the raw payload stays server-side so role-filtered fields (red
    # flags, process findings) never leak via this serializer.
    resume_excerpts: list[ResumeExcerptRead] | None = None
    # HRP-272: True when the candidate uploaded a fresh resume after
    # this run was enqueued (current parsed_resume hash diverges from
    # the run's stored ``resume_snapshot_hash``). Resume-only mode only;
    # full-mode runs and legacy rows without a stamped hash stay False.
    resume_outdated: bool = False

    # ``validate_assignment`` lets the serializer mutate
    # ``resume_excerpts`` / ``resume_outdated`` after
    # ``model_validate(run)`` and still get ``ResumeExcerptRead``
    # coercion from the raw dict.
    model_config = {"from_attributes": True, "validate_assignment": True}


class AIAnalysisEnqueueResponse(BaseModel):
    task_id: str | None = None
    # ``None`` on the full-mode cache-hit path: the cached analysis is
    # written directly onto the interview row without producing a fresh
    # ``AIAnalysisRun`` id (the legacy ``enqueue_analyze_or_cached``
    # entry point predates the runs table).
    run_id: uuid.UUID | None = None
    status: Literal["queued", "completed"]
    mode: Literal["resume_only", "full"]
    supersedes_id: uuid.UUID | None = None


class TopupEligibilityResponse(BaseModel):
    eligible: bool
    reason: str | None = None
    active_run_id: uuid.UUID | None = None
    interview_id: uuid.UUID | None = None
    # HRP-269: surface the latest transcribed interview regardless of
    # ``eligible``, so the candidate-card split-button can offer a direct
    # ``Resume + interview`` run without first having to create a
    # resume-only baseline. ``interview_id`` above stays gated behind
    # the top-up checks for backwards compatibility.
    transcribed_interview_id: uuid.UUID | None = None
    age_days: int | None = None
    window_days: int | None = None
    stored_version: int | None = None
    current_version: int | None = None


class BulkAnalyzeRequest(BaseModel):
    candidate_vacancy_ids: list[uuid.UUID] = Field(min_length=1)


class BulkAnalyzeQueuedRow(BaseModel):
    candidate_vacancy_id: uuid.UUID
    task_id: str | None = None
    run_id: uuid.UUID | None = None
    status: str


class BulkAnalyzeFailedRow(BaseModel):
    candidate_vacancy_id: uuid.UUID
    error: str
    status_code: int


class BulkAnalyzeResponse(BaseModel):
    queued: list[BulkAnalyzeQueuedRow]
    failed: list[BulkAnalyzeFailedRow]
