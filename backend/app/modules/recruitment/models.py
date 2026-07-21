from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models import BaseModel, Person, TenantMixin

# ---------------------------------------------------------------------------
# HRP-180: junction tables linking Vacancy ↔ Specialization / Grade
# (dictionary_items). Plain Tables (not BaseModel) because they have no
# tenant/id of their own — composite PK on the two FKs.
# ---------------------------------------------------------------------------

vacancy_specializations_table = Table(
    "vacancy_specializations",
    Base.metadata,
    Column(
        "vacancy_id",
        UUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "specialization_id",
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", DateTime(timezone=True), server_default=text("now()")),
)

vacancy_grades_table = Table(
    "vacancy_grades",
    Base.metadata,
    Column(
        "vacancy_id",
        UUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "grade_id",
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", DateTime(timezone=True), server_default=text("now()")),
)

# ---------------------------------------------------------------------------
# 1. Vacancy
# ---------------------------------------------------------------------------


class Vacancy(BaseModel, TenantMixin):
    __tablename__ = "vacancies"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # HRP-180: optional link to a Position; selecting one constrains the
    # spec/grade multi-selects to the values defined on that Position.
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("positions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Legacy single-value FKs — kept until data migration sweeps them out.
    specialization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    grade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    division_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("divisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", server_default="draft"
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # HRP-360: the responsible hiring manager (admin-tier user), separate
    # from ``owner_id`` which records who created the vacancy.
    hiring_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tasks_main: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tasks_additional: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tasks_kpi: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    salary_min: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="en", server_default="en"
    )
    close_resolution: Mapped[str | None] = mapped_column(String(50), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Incremented on every PATCH; backs the ``If-Match: W/"{version}"``
    # ETag header so concurrent editors get a 412 instead of silently
    # overwriting each other (HRP-177).
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # HRP-131: stores ``{position_ids, specialization_grade_pairs,
    # division_ids}`` selections from the form. Aggregation into
    # competences runs at read time via ``aggregate_library_competences``
    # so the schema stays flexible while the data is still queryable.
    library_refs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # HRP-135: optional textual blocks fed into the AI prompt.
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsibilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # HRP-186: tenant-scoped scale picked when the vacancy was created.
    # ``assessment_scale_snapshot`` is populated on the first assessment
    # write and frozen thereafter so later tenant-level edits to the
    # scale never reach into the already-scored data.
    assessment_scale_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recruitment_assessment_scales.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assessment_scale_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # lazy="raise": loaded explicitly (selectinload) where needed; child rows
    # are removed by the DB-level ON DELETE CASCADE (passive_deletes), so the
    # ORM delete cascade never has to lazy-load them at flush time.
    profile: Mapped[VacancyProfile | None] = relationship(
        back_populates="vacancy",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="raise",
        passive_deletes=True,
    )
    candidates: Mapped[list[CandidateVacancy]] = relationship(
        back_populates="vacancy",
        cascade="all, delete-orphan",
        lazy="raise",
        passive_deletes=True,
    )
    stages: Mapped[list[VacancyStage]] = relationship(
        back_populates="vacancy",
        cascade="all, delete-orphan",
        lazy="raise",
        passive_deletes=True,
    )
    # HRP-180: multi-select spec/grade — each row in the junction table
    # references a ``dictionary_items`` row. ``lazy="selectin"`` because
    # the page renders titles inline and N+1 is not acceptable.
    specializations = relationship(
        "DictionaryItem",
        secondary=vacancy_specializations_table,
        lazy="selectin",
    )
    grades = relationship(
        "DictionaryItem",
        secondary=vacancy_grades_table,
        lazy="selectin",
    )


# ---------------------------------------------------------------------------
# 2. VacancyProfile
# ---------------------------------------------------------------------------


class VacancyProfile(BaseModel, TenantMixin):
    __tablename__ = "vacancy_profiles"

    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    profile_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="en", server_default="en"
    )
    coverage_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_by: Mapped[str | None] = mapped_column(String(50), nullable=True)

    vacancy: Mapped[Vacancy] = relationship(
        back_populates="profile", lazy="raise_on_sql"
    )


class VacancyProfileSession(BaseModel, TenantMixin):
    """HRP-134: one tracked AI-profile-generation run per vacancy.

    Surfaces the in-progress state so the UI can show ``Generating…``
    while the sync LLM call runs server-side, and lets a returning user
    discover that a prior generation already finished (status=ready)
    even if their browser tab dropped the response.

    Terminal statuses ``ready`` / ``failed`` keep the latest result
    payload in ``result_payload`` so a returning user can re-apply or
    dismiss it. ``cancelled`` marks a user-initiated abort.
    """

    __tablename__ = "vacancy_profile_sessions"

    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        server_default="running",
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


# ---------------------------------------------------------------------------
# 3. VacancyStage (BaseModel only, tenant_id is custom nullable)
# ---------------------------------------------------------------------------


class VacancyStage(BaseModel):
    __tablename__ = "vacancy_stages"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    vacancy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_terminal: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # HRP-181 REDO: ``stage_type`` is the source of truth for funnel
    # semantics — ``active`` advances the candidate, the three
    # ``terminal_*`` values close the application (positive = Hired,
    # negative = Rejected, neutral = Withdrew). ``is_terminal`` stays
    # as a denormalised mirror so legacy queries still work.
    stage_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)

    vacancy: Mapped[Vacancy | None] = relationship(
        back_populates="stages", lazy="raise_on_sql"
    )


# ---------------------------------------------------------------------------
# 4. Candidate
# ---------------------------------------------------------------------------


class Candidate(BaseModel, TenantMixin):
    """Tenant-unique candidate.

    HRP-181 REDO: ``person_id`` is now optional so externally-sourced
    candidates (e.g. someone uploaded a resume but never had a tenant
    ``Person`` row) can live in the same table as internal referrals.
    Display fields (``full_name``, ``email``, ``phone``) are denormalised
    onto this row regardless — they're the source of truth for the
    candidate list and the candidate card, and they're populated from
    the linked ``Person`` when one exists.

    Uniqueness on ``(tenant_id, lower(email))`` is enforced by a partial
    unique index in the DB (``ux_candidates_tenant_email_active``) so
    the Upload-resume flow can detect duplicates inside a tenant.
    """

    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("person_id", "tenant_id", name="uq_candidate_person_tenant"),
        # HRP-181 REDO: duplicate-detect for the Upload-resume flow.
        # Active rows (``archived_at IS NULL``) are unique per
        # ``(tenant_id, lower(email))``; an archived twin is allowed so
        # the same address can be re-imported once the previous row is
        # soft-deleted.
        Index(
            "ux_candidates_tenant_email_active",
            "tenant_id",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("email IS NOT NULL AND archived_at IS NULL"),
        ),
    )

    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("persons.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_position: Mapped[str | None] = mapped_column(String(255), nullable=True)
    years_of_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Raw structured payload from the LLM resume parser — the candidate
    # card reads ``experience`` / ``education`` / ``skills`` /
    # ``languages`` off here.
    parsed_resume_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    person: Mapped[Person | None] = relationship(lazy="selectin")
    # lazy="raise": loaded explicitly (selectinload) where needed; child rows
    # are removed by the DB-level ON DELETE CASCADE (passive_deletes).
    vacancies: Mapped[list[CandidateVacancy]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        lazy="raise",
        passive_deletes=True,
    )
    files: Mapped[list[CandidateFile]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        lazy="raise",
        passive_deletes=True,
    )


# ---------------------------------------------------------------------------
# 5. CandidateVacancy
# ---------------------------------------------------------------------------


class CandidateVacancy(BaseModel, TenantMixin):
    __tablename__ = "candidate_vacancies"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vacancy_stages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="new", server_default="new"
    )
    status_history: Mapped[list] = mapped_column(JSONB, server_default="[]")
    ranking_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    attached_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # HRP-186: denormalized aggregated score so the candidate table
    # can render Manager score without joining round + assessments. The
    # service recomputes these whenever a round / assessment changes.
    manager_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    manager_score_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    manager_score_source_round_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recruitment_assessment_rounds.id", ondelete="SET NULL"),
        nullable=True,
    )
    manager_score_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # HRP-181 REDO: AI block (FR-23). ``ai_readiness`` tracks which
    # inputs the model has seen (``none`` / ``resume_only`` /
    # ``resume_and_transcript``); ``ai_verdict`` is the top-level
    # recommendation (``recommended`` / ``needs_check`` /
    # ``not_recommended`` / ``pending``). The four free-text fields back
    # the popover in the candidates table.
    ai_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # HRP-274: raw ``ai_score`` is on the canonical 0..1 scale — both
    # analysis prompts pin it and parsed values are clamped at ingestion
    # (see ``score_normalization.clamp_unit_score``).
    # ``ai_score_normalized`` rebases it onto the tenant's active
    # ScaleConfig max (identity fallback when no scale is active) so it
    # is directly comparable with ``manager_score`` and feeds
    # ``compute_score_divergence``. Front-end toggles which one to show
    # in the candidates table.
    ai_score_normalized: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_readiness: Mapped[str] = mapped_column(
        String(30), nullable=False, default="none", server_default="none"
    )
    ai_verdict: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    ai_verdict_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_key_strength: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_key_risk: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_risk_mitigation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # HRP-204: mirror of the active ``ai_analysis_runs`` row so the
    # candidate list can render ``[resume only]`` / ``[full]`` sub-badges
    # and the "Resume updated" banner without joining the runs table.
    # ``ai_analysis_mode`` is ``resume_only`` / ``full`` / ``None`` (no
    # completed run yet). ``ai_data_completeness`` mirrors the active
    # run's payload field.
    ai_analysis_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_analysis_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ai_data_completeness: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Bumped on every PATCH; backs ``If-Match: W/"{version}"`` ETags
    # (mirrors HRP-177 on vacancies).
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # When the candidate was attached to this vacancy. Distinct from
    # ``created_at`` so a back-dated import can preserve the real date.
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    candidate: Mapped[Candidate] = relationship(
        back_populates="vacancies", lazy="selectin"
    )
    vacancy: Mapped[Vacancy] = relationship(
        back_populates="candidates", lazy="selectin"
    )
    stage: Mapped[VacancyStage | None] = relationship(lazy="selectin")


# ---------------------------------------------------------------------------
# 6. CandidateFile (HRP-181 REDO — renamed from Resume)
# ---------------------------------------------------------------------------


class CandidateFile(BaseModel, TenantMixin):
    """Generic file attached to a candidate.

    ``file_type`` discriminates between resumes (PDF/DOCX uploaded for
    parsing) and interview media (audio/video uploaded for
    transcription). Resumes are populated by the Upload-resume flow;
    interview rows are written by the interview upload module and
    referenced from ``interviews.audio_file_id`` etc. ``file_type``
    keeps both shapes in one table so the batch parse / status polling
    code path stays uniform.
    """

    __tablename__ = "candidate_files"

    # HRP-181 REDO Stage 3: nullable so the bulk-upload flow can persist
    # parsed-but-not-yet-finalised rows. ``finalize_candidates_from_parsed``
    # flips this to the chosen candidate (newly created or linked).
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    file_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="resume", server_default="resume"
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    parsed_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", server_default="pending"
    )

    candidate: Mapped[Candidate | None] = relationship(
        back_populates="files", lazy="raise_on_sql"
    )


# ---------------------------------------------------------------------------
# 7. CandidateQuestion
# ---------------------------------------------------------------------------


class CandidateQuestion(BaseModel, TenantMixin):
    __tablename__ = "candidate_questions"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    good_answer: Mapped[str] = mapped_column(Text, nullable=False)
    acceptable_answer: Mapped[str] = mapped_column(Text, nullable=False)
    poor_answer: Mapped[str] = mapped_column(Text, nullable=False)
    resume_fragment: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="clarification",
        server_default="clarification",
    )
    priority: Mapped[str] = mapped_column(
        String(50), nullable=False, default="should", server_default="should"
    )
    is_manual: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


# ---------------------------------------------------------------------------
# 8. Interview
# ---------------------------------------------------------------------------


class Interview(BaseModel, TenantMixin):
    __tablename__ = "interviews"

    candidate_vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    interviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    interview_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # HRP-202: ``duration_seconds`` is the probed media length, populated
    # after upload completes. ``duration_minutes`` is the user-entered
    # planned duration from the Schedule modal.
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # HRP-202 lifecycle states: scheduled / uploading / uploaded /
    # upload_failed / archived. Older R3a values (planned / completed)
    # still resolve until tenants migrate.
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="undecided", server_default="undecided"
    )
    audio_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    video_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    transcript_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
    )
    file_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    file_mime: Mapped[str | None] = mapped_column(String(120), nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="scheduled",
        server_default="scheduled",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Bumped on every PATCH; backs ``If-Match: W/"{version}"`` ETags so
    # concurrent editors get a 412 instead of silently overwriting each
    # other (mirrors HRP-177 on vacancies).
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    av_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    av_scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consent_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consent_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consent_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    transcription_provider: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    transcription_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", server_default="pending"
    )
    analysis_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", server_default="pending"
    )
    transcription_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # HRP-202 REDO: when the upload was submitted with auto-processing on,
    # the transcribe task chains straight into AI analysis on success.
    auto_process: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    candidate_vacancy: Mapped[CandidateVacancy] = relationship(lazy="selectin")
    # lazy="raise": loaded explicitly (selectinload) where needed; child rows
    # are removed by the DB-level ON DELETE CASCADE (passive_deletes).
    segments: Mapped[list[InterviewSegment]] = relationship(
        back_populates="interview",
        cascade="all, delete-orphan",
        lazy="raise",
        passive_deletes=True,
    )
    interviewers: Mapped[list[InterviewInterviewer]] = relationship(
        back_populates="interview",
        cascade="all, delete-orphan",
        lazy="raise",
        passive_deletes=True,
    )


class InterviewInterviewer(TenantMixin, Base):
    """HRP-202: many-to-many between interviews and interviewer users.

    The legacy ``interviews.interviewer_id`` column is still populated
    with the *primary* interviewer for back-compat with the analysis /
    notifications code; this table is the source of truth for the full
    list shown in the UI.

    Composite PK on ``(interview_id, user_id)`` — no surrogate ``id``,
    matching the migration in ``hrp202inthr01_interview_upload_overhaul``.
    """

    __tablename__ = "interview_interviewers"

    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )

    interview: Mapped[Interview] = relationship(
        back_populates="interviewers", lazy="raise_on_sql"
    )


class UploadSession(BaseModel, TenantMixin):
    """HRP-202: durable record of an in-flight S3 multipart upload.

    Persisted across page reloads so the TUS-style ``HEAD`` and ``PATCH``
    endpoints can resume from the right offset, and the orphan-cleanup
    Celery task can abort the underlying S3 multipart when the session
    expires.
    """

    __tablename__ = "upload_sessions"

    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    total_size: Mapped[int] = mapped_column(nullable=False)
    uploaded_bytes: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    part_size: Mapped[int] = mapped_column(Integer, nullable=False)
    s3_upload_id: Mapped[str] = mapped_column(String(500), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    s3_parts: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


# ---------------------------------------------------------------------------
# 9. InterviewSegment
# ---------------------------------------------------------------------------


class InterviewSegment(BaseModel, TenantMixin):
    __tablename__ = "interview_segments"

    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    speaker: Mapped[str] = mapped_column(String(50), nullable=False)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    interview: Mapped[Interview] = relationship(
        back_populates="segments", lazy="raise_on_sql"
    )


# ---------------------------------------------------------------------------
# 10. HumanAssessment
# ---------------------------------------------------------------------------


class HumanAssessment(BaseModel, TenantMixin):
    __tablename__ = "human_assessments"

    candidate_vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    evaluator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    evaluator_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invite_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_invites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


# ---------------------------------------------------------------------------
# 11. AIAssessment
# ---------------------------------------------------------------------------


class AIAssessment(BaseModel, TenantMixin):
    __tablename__ = "ai_assessments"

    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    citations: Mapped[list] = mapped_column(JSONB, server_default="[]")
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# 11b. InterviewAnalysisCache (HRP-252)
# ---------------------------------------------------------------------------


class InterviewAnalysisCache(BaseModel, TenantMixin):
    """Deduplicates LLM analysis runs on identical transcript + profile.

    Re-running ``POST /recruitment/interviews/{id}/analyze`` against an
    untouched transcript should not burn another 40 credits — the LLM
    output is deterministic enough at temperature 0.2 for an exact-input
    cache to be safe. Key = sha256 of transcript + vacancy_profile.id +
    profile.version, scoped per-tenant so two tenants on the same
    transcript do not share AIAssessment payloads (multitenant isolation).
    """

    __tablename__ = "interview_analysis_cache"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "cache_key", name="uq_interview_analysis_cache_key"
        ),
    )

    # 64-char lowercase hex sha256 digest. No standalone index: the
    # (tenant_id, cache_key) UQ btree above covers every lookup.
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    assessments: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )


# ---------------------------------------------------------------------------
# 11c. AIAnalysisRun (HRP-204)
# ---------------------------------------------------------------------------


class AIAnalysisRun(BaseModel, TenantMixin):
    """One AI analysis run for a ``(candidate, vacancy)`` pair.

    ``mode`` discriminates resume-only (pre-interview pre-screening,
    20 credits, 4 stages out of 6) from full (interview-backed, 40
    credits, 6 stages). Both modes write competence assessments,
    blind spots, red flags, verdict + verdict_summary into
    ``analysis_data``; full additionally writes ``process_findings`` and
    transcript-anchored ``citations``; resume-only writes
    ``resume_excerpts`` instead of citations.

    Top-up flow (resume-only → full, +20 credits): the new full run
    points at the prior resume-only via ``supersedes_id`` and the
    older row is stamped ``archived_at`` + ``replaced_by_id`` in the
    same transaction.
    """

    __tablename__ = "ai_analysis_runs"
    __table_args__ = (
        # HRP-423: mirror of the migration-defined partial unique index
        # (hrp204). The "active" run per pair = ``archived_at IS NULL``;
        # a successful run must archive older active rows BEFORE its own
        # row turns ``completed`` (the index is non-deferrable). Declared
        # on the model too so metadata-created schemas (unit-test DB)
        # enforce the same invariant as production.
        Index(
            "uq_ai_analysis_runs_active_per_cv",
            "candidate_vacancy_id",
            unique=True,
            postgresql_where=text("archived_at IS NULL AND status = 'completed'"),
        ),
    )

    candidate_vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    data_completeness: Mapped[str | None] = mapped_column(String(20), nullable=True)
    interview_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interviews.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    candidate_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    vacancy_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vacancy_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    vacancy_profile_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(30), nullable=True)
    verdict_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_strength: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_risk: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_mitigation: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_for_next_step: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    ai_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    credits_charged: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_analysis_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_analysis_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # HRP-270: per-stage progress + cancel bookkeeping.
    #
    # ``current_stage`` is one of the values in
    # ``app.modules.recruitment.constants.AI_ANALYSIS_STAGES`` (None
    # while the run is still ``pending``). The Celery task bumps it
    # at the start of each pipeline step so the candidate-card
    # InFlightCard can highlight the active row and the cancel
    # endpoint can decide between a full and a no-credit refund.
    #
    # ``celery_task_id`` is captured at enqueue time so the cancel
    # endpoint can call ``celery.control.revoke(terminate=True)`` —
    # we deliberately keep it nullable for legacy rows + cache-hit
    # full mode (no Celery task is dispatched there).
    current_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # HRP-272: SHA256 over the candidate's parsed_resume JSON at enqueue
    # time. ``serialize_run_for_read`` compares this against the current
    # resume hash to flag the run as outdated when the candidate uploads
    # a fresh CV — the UI surfaces a "Resume updated — re-analyze" banner
    # that re-runs the existing resume-only billable. NULL on legacy rows
    # created before HRP-272.
    resume_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


# ---------------------------------------------------------------------------
# 12. AssessmentInvite
# ---------------------------------------------------------------------------


class AssessmentInvite(BaseModel, TenantMixin):
    __tablename__ = "assessment_invites"

    candidate_vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    # HRP-186: only the hash should live in the DB long-term; ``token`` stays
    # populated for the existing R3-era invite flow but new invites issued
    # through the manager-assessment path clear ``token`` after first use.
    token_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    evaluator_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", server_default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # HRP-186: when an invite binds to a specific round, the recruiter
    # picks the round in the modal and we tag the row. Public-token
    # writes then land into the same round as the internal evaluators.
    round_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recruitment_assessment_rounds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    allow_reediting: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    personal_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # HRP-358: ``opened_at`` now stamps the first link visit, so the
    # consent acknowledgment needs its own timestamp to keep the gate up.
    consent_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    declined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="queued", server_default="queued"
    )
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


# ---------------------------------------------------------------------------
# 13. ConsolidatedReport
# ---------------------------------------------------------------------------


class ConsolidatedReport(BaseModel, TenantMixin):
    __tablename__ = "consolidated_reports"

    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    report_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sections: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", server_default="pending"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


# ---------------------------------------------------------------------------
# 14. ScaleConfig
# ---------------------------------------------------------------------------


class ScaleConfig(BaseModel, TenantMixin):
    __tablename__ = "scale_configs"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    min_value: Mapped[float] = mapped_column(Float, nullable=False)
    max_value: Mapped[float] = mapped_column(Float, nullable=False)
    step: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")
    labels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )

    # Partial unique: at most one active scale per tenant. The service
    # layer already enforces this in _deactivate_other_scales, but a
    # concurrent create+update race could slip two through without this
    # invariant in the DB. Mirrors migration r4b2c3d4e5f6.
    __table_args__ = (
        Index(
            "ix_scale_configs_one_active_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )


# ---------------------------------------------------------------------------
# 15. ReportTemplate
# ---------------------------------------------------------------------------


class ReportTemplate(BaseModel, TenantMixin):
    __tablename__ = "report_templates"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    template_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sections: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )


# ---------------------------------------------------------------------------
# 16. LLMProviderConfig
# ---------------------------------------------------------------------------


class LLMProviderConfig(BaseModel, TenantMixin):
    __tablename__ = "llm_provider_configs"

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


# ---------------------------------------------------------------------------
# 17. TranscriptionProviderConfig
# ---------------------------------------------------------------------------


class TranscriptionProviderConfig(BaseModel, TenantMixin):
    __tablename__ = "transcription_provider_configs"

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


# ---------------------------------------------------------------------------
# 18. ConsentTemplate (R3a)
# ---------------------------------------------------------------------------


class ConsentTemplate(BaseModel, TenantMixin):
    __tablename__ = "consent_templates"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="en", server_default="en"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


# ---------------------------------------------------------------------------
# 19. ConsentRequest (R3a)
# ---------------------------------------------------------------------------


class ConsentRequest(BaseModel, TenantMixin):
    __tablename__ = "consent_requests"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consent_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    signed_user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", server_default="pending"
    )
    # R4c: who issued the consent magic link. Notification routing for
    # ``consent.signed`` falls back to this user (otherwise we'd have to
    # broadcast to all admins).
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


# ---------------------------------------------------------------------------
# 20. RecruitmentRetentionConfig (R4b, SCR-96)
# ---------------------------------------------------------------------------


class RecruitmentRetentionConfig(BaseModel, TenantMixin):
    """Per-tenant retention windows for recruitment data (days)."""

    __tablename__ = "recruitment_retention_configs"

    interviews_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=365, server_default="365"
    )
    resumes_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=365, server_default="365"
    )
    consents_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=365, server_default="365"
    )
    reports_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=365, server_default="365"
    )


# ---------------------------------------------------------------------------
# 21. RecruitmentAuditLog (R4b, FR-28)
# ---------------------------------------------------------------------------


class RecruitmentAuditLog(BaseModel, TenantMixin):
    """Append-only audit trail for mutating recruitment operations."""

    __tablename__ = "recruitment_audit_log"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    payload_diff: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)


# ---------------------------------------------------------------------------
# 22. GDPRExportRequest (R4b, §9.2)
# ---------------------------------------------------------------------------


class GDPRExportRequest(BaseModel, TenantMixin):
    """Async export job manifest. The actual JSON dump lives in S3."""

    __tablename__ = "gdpr_export_requests"

    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subject_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", server_default="pending"
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# 23. GDPRErasureLog (R4b, §9.2)
# ---------------------------------------------------------------------------


class GDPRErasureLog(BaseModel, TenantMixin):
    """Audit trail of soft-erasure (right to be forgotten) actions."""

    __tablename__ = "gdpr_erasure_log"

    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    affected: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


# ---------------------------------------------------------------------------
# 24. RecruitmentReportShare (R4c, FR-22, SCR-84)
# ---------------------------------------------------------------------------


class RecruitmentReportShare(BaseModel, TenantMixin):
    """Tokenised public share of a consolidated XLSX report."""

    __tablename__ = "recruitment_report_shares"

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consolidated_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recipients: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    open_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# HRP-135: VacancyAttachment — uploaded docs fed into the AI prompt
# ---------------------------------------------------------------------------


class VacancyAttachment(BaseModel, TenantMixin):
    """File attached to a vacancy (PDF / DOCX / image / etc).

    Stored in ``modules/storage`` (S3/MinIO) — this row only links the
    vacancy to the file row and remembers display metadata so the UI
    doesn't have to hit storage to list attachments.
    """

    __tablename__ = "vacancy_attachments"

    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


# ---------------------------------------------------------------------------
# HRP-136: VacancyCompetence — manual / generated competence list
# ---------------------------------------------------------------------------


class VacancyCompetence(BaseModel, TenantMixin):
    """Competence required by a vacancy with target skill levels.

    ``skill_level_ids`` is a JSON array of skill-level UUIDs (the user
    can pick more than one — the spec calls for "select level + preview
    indicators"). ``source`` records whether the row was added manually
    from the library, inherited from a specialization/grade, or proposed
    by AI generation.
    """

    __tablename__ = "vacancy_competences"
    __table_args__ = (
        UniqueConstraint("vacancy_id", "competence_id", name="uq_vacancy_competence"),
    )

    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    skill_level_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual", server_default="manual"
    )


# ---------------------------------------------------------------------------
# HRP-205. QuestionSet / Question / QuestionSetJob
#
# Individual interview questions per candidate-vacancy, evolving per round.
# Replaces the flat ``candidate_questions`` model from R1: sets are
# versioned bundles attached to a single ``candidate_vacancies`` row;
# questions inside carry rich metadata (resume anchor, expected answer
# indicators, follow-ups, rationale, covered state, source).
# ---------------------------------------------------------------------------


class QuestionSet(BaseModel, TenantMixin):
    __tablename__ = "question_sets"

    candidate_vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interviews.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # pre_interview | interview_round | final
    set_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pre_interview",
        server_default="pre_interview",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # ready | generating | failed | sample
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ready", server_default="ready"
    )
    # initial | regenerated | dynamic_next | manual
    generation_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="initial",
        server_default="initial",
    )
    source_round_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    coverage_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    questions: Mapped[list[Question]] = relationship(
        back_populates="question_set",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Question.sort_order",
    )


class Question(BaseModel, TenantMixin):
    __tablename__ = "questions"

    question_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("question_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # clarification | depth | risk | motivation | fit
    goal: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="clarification",
        server_default="clarification",
    )
    # must | should | nice_to_ask
    priority: Mapped[str] = mapped_column(
        String(32), nullable=False, default="should", server_default="should"
    )
    competence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # {"quote": "...", "section": "experience", "offset": null}
    resume_anchor_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    expected_answer_indicators: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )
    follow_ups: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ai_generated | manual | from_competency_indicator | from_blind_spot
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ai_generated",
        server_default="ai_generated",
    )
    source_blind_spot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # active | removed
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    covered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    covered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # manual | auto_from_transcript
    covered_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    question_set: Mapped[QuestionSet] = relationship(
        back_populates="questions", lazy="raise_on_sql"
    )


class QuestionSetJob(BaseModel, TenantMixin):
    __tablename__ = "question_set_jobs"

    question_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("question_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # queued | running | succeeded | failed
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
