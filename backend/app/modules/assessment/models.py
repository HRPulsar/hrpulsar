import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import BaseModel, TenantMixin

# --- Reference tables ---


class AssessmentStatus(BaseModel):
    __tablename__ = "assessment_statuses"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class AssessmentType(BaseModel):
    __tablename__ = "assessment_types"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)


class AnswerScale(BaseModel):
    __tablename__ = "answer_scales"
    __table_args__ = (
        Index(
            "ix_answer_scales_active",
            "tenant_id",
            postgresql_where=text("deleted_at IS NULL AND is_snapshot = false"),
        ),
        Index(
            "uq_answer_scales_global_default",
            "is_default",
            unique=True,
            postgresql_where=text(
                "tenant_id IS NULL AND is_default = true AND deleted_at IS NULL"
            ),
        ),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_snapshot: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    options: Mapped[list["AnswerOption"]] = relationship(
        back_populates="scale",
        cascade="all, delete-orphan",
        order_by="AnswerOption.sort_index",
    )
    levels: Mapped[list["AnswerScaleLevel"]] = relationship(
        back_populates="scale",
        cascade="all, delete-orphan",
        order_by="AnswerScaleLevel.sort_index",
    )


class AnswerOption(BaseModel):
    __tablename__ = "answer_options"

    scale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("answer_scales.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    weight: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_neutral: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    scale: Mapped["AnswerScale"] = relationship(back_populates="options")


class AnswerScaleLevel(BaseModel):
    __tablename__ = "answer_scale_levels"
    __table_args__ = (
        CheckConstraint("percent_from BETWEEN 0 AND 100", name="ck_level_from_range"),
        CheckConstraint("percent_to BETWEEN 0 AND 100", name="ck_level_to_range"),
        CheckConstraint("percent_from <= percent_to", name="ck_level_order"),
        CheckConstraint(
            "system_code IS NOT NULL OR system_title IS NOT NULL",
            name="ck_scale_level_code_or_title",
        ),
    )

    scale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("answer_scales.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    percent_from: Mapped[int] = mapped_column(Integer, nullable=False)
    percent_to: Mapped[int] = mapped_column(Integer, nullable=False)
    # Stable identifier for origin/seeded levels. The frontend renders the
    # localized label via an i18n dictionary keyed by `system_code`; rows
    # with `system_code` set leave `system_title` NULL — there is no title
    # fallback. Tenant-custom levels go the other way: `system_code IS
    # NULL`, `system_title` carries HR-authored plain text.
    system_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    system_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    scale: Mapped["AnswerScale"] = relationship(back_populates="levels")


# --- Core assessment ---


class Assessment(BaseModel, TenantMixin):
    __tablename__ = "assessments"
    __table_args__ = (
        CheckConstraint(
            "passing_score IS NULL OR passing_score BETWEEN 0 AND 100",
            name="ck_assessment_passing_score_range",
        ),
    )

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_types.id"),
        nullable=False,
    )
    status_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_statuses.id"),
        nullable=False,
    )
    specialization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id"),
        nullable=True,
    )
    grade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id"),
        nullable=True,
    )
    scale_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("answer_scales.id"),
        nullable=True,
    )
    initiator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    approver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cpa_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cpas.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    criteria_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    passing_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommended_grade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    recommendation_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # HRP-185: while a reviewer is editing per-indicator Totals, participant
    # submissions are locked so the calibration baseline doesn't shift under
    # them. The flag flips back to ``false`` on Save / Cancel calibration.
    calibration_in_progress: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    employee = relationship("Employee", lazy="selectin")
    assessment_type: Mapped["AssessmentType"] = relationship(lazy="selectin")
    status: Mapped["AssessmentStatus"] = relationship(lazy="selectin")
    group: Mapped["AssessmentGroup | None"] = relationship(back_populates="assessments")
    participants: Mapped[list["AssessmentParticipant"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    competences: Mapped[list["AssessmentCompetence"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    results: Mapped[list["AssessmentResult"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class AssessmentCompetence(BaseModel):
    __tablename__ = "assessment_competences"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competences.id", ondelete="CASCADE"),
        nullable=False,
    )
    skill_level_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skill_levels.id", ondelete="SET NULL"),
        nullable=True,
    )

    assessment: Mapped["Assessment"] = relationship(back_populates="competences")
    competence = relationship("Competence", lazy="selectin")
    skill_level = relationship("SkillLevel", lazy="selectin")


class AssessmentParticipant(BaseModel):
    __tablename__ = "assessment_participants"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    external_reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("external_reviewers.id", ondelete="CASCADE"),
        nullable=True,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    is_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    assessment: Mapped["Assessment"] = relationship(back_populates="participants")
    user = relationship("User", lazy="selectin")
    external_reviewer: Mapped["ExternalReviewer | None"] = relationship(lazy="selectin")


class ExternalReviewer(BaseModel, TenantMixin):
    """External (anonymous) reviewer for open access assessments."""

    __tablename__ = "external_reviewers"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AssessmentAnswer(BaseModel):
    __tablename__ = "assessment_answers"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    indicator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("indicators.id", ondelete="CASCADE"),
        nullable=False,
    )
    answer_option_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("answer_options.id", ondelete="CASCADE"),
        nullable=True,
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class AssessmentCalibratedTotal(BaseModel):
    """HRP-185: per-indicator Total override stored when a reviewer
    calibrates the assessment.

    Each row pins a specific answer option as the "Total" for an
    indicator — the recompute treats it as if every role had agreed on
    that answer, so percent / level / per-skill-level percent inherit
    the override. Wiped when calibration is cancelled.
    """

    __tablename__ = "assessment_calibrated_totals"
    __table_args__ = (
        Index(
            "uq_assessment_calibrated_indicator",
            "assessment_id",
            "indicator_id",
            unique=True,
        ),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    indicator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("indicators.id", ondelete="CASCADE"),
        nullable=False,
    )
    answer_option_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("answer_options.id", ondelete="CASCADE"),
        nullable=False,
    )


class AssessmentResult(BaseModel):
    __tablename__ = "assessment_results"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # HRP-281: when a tenant is dropped competences cascade via
    # tenant_id; mirror the cascade onto assessment_results so the
    # tenant delete completes (the result is meaningless without its
    # source competence anyway).
    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competences.id", ondelete="CASCADE"),
        nullable=False,
    )
    avg_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    calibrated_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("answer_scale_levels.id", ondelete="SET NULL"),
        nullable=True,
    )

    assessment: Mapped["Assessment"] = relationship(back_populates="results")
    level: Mapped["AnswerScaleLevel | None"] = relationship(lazy="selectin")


# --- Assessment Groups (mass assessment) ---


class AssessmentGroup(BaseModel, TenantMixin):
    __tablename__ = "assessment_groups"
    __table_args__ = (
        CheckConstraint(
            "passing_score IS NULL OR passing_score BETWEEN 0 AND 100",
            name="ck_assessment_group_passing_score_range",
        ),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    initiator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    criteria_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    specialization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id"),
        nullable=True,
    )
    grade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id"),
        nullable=True,
    )
    scale_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("answer_scales.id"),
        nullable=True,
    )
    passing_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    assessments: Mapped[list["Assessment"]] = relationship(
        foreign_keys=[Assessment.group_id], back_populates="group"
    )


# --- CPA (batch assessment) ---


class CPA(BaseModel, TenantMixin):
    __tablename__ = "cpas"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_types.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", server_default="draft"
    )
    scale_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("answer_scales.id"),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    assessments: Mapped[list["Assessment"]] = relationship(
        foreign_keys=[Assessment.cpa_id]
    )
    criteria: Mapped[list["CPACriteria"]] = relationship(
        back_populates="cpa", cascade="all, delete-orphan"
    )
    participants: Mapped[list["CPAParticipant"]] = relationship(
        back_populates="cpa", cascade="all, delete-orphan"
    )


class CPACriteria(BaseModel):
    __tablename__ = "cpa_criteria"

    cpa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cpas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    criteria_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # position, point, competence
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")

    cpa: Mapped["CPA"] = relationship(back_populates="criteria")


class CPAParticipant(BaseModel):
    __tablename__ = "cpa_participants"

    cpa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cpas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # reviewer, calibrator, observer

    cpa: Mapped["CPA"] = relationship(back_populates="participants")


# --- PDP ---


class PDP(BaseModel, TenantMixin):
    __tablename__ = "pdps"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="SET NULL"),
        nullable=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", server_default="draft"
    )
    specialization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id"),
        nullable=True,
    )
    grade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id"),
        nullable=True,
    )
    total_progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # HRP-24: snapshot of items+materials captured when the plan enters
    # ``review``; cleared when it leaves. The PDP owner sees this snapshot
    # instead of live items while the plan is under review.
    on_review_items_snapshot: Mapped[list[dict] | None] = mapped_column(
        JSONB, nullable=True
    )

    items: Mapped[list["PDPItem"]] = relationship(
        back_populates="pdp",
        cascade="all, delete-orphan",
        order_by="PDPItem.sort_index",
    )
    comments: Mapped[list["PDPComment"]] = relationship(
        back_populates="pdp", cascade="all, delete-orphan"
    )
    employee = relationship("Employee", foreign_keys=[employee_id], lazy="selectin")
    specialization = relationship(
        "DictionaryItem", foreign_keys=[specialization_id], lazy="selectin"
    )
    grade = relationship("DictionaryItem", foreign_keys=[grade_id], lazy="selectin")


class PDPItem(BaseModel):
    __tablename__ = "pdp_items"

    pdp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pdps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competences.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_passed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    entity_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="custom", server_default="custom"
    )

    pdp: Mapped["PDP"] = relationship(back_populates="items")
    materials: Mapped[list["PDPItemMaterial"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="PDPItemMaterial.sort_index",
    )


class PDPItemMaterial(BaseModel):
    __tablename__ = "pdp_item_materials"

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pdp_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    material_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("materials.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(600), nullable=False)
    format: Mapped[str | None] = mapped_column(String(100), nullable=True)
    link: Mapped[str | None] = mapped_column(String(600), nullable=True)
    study_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_passed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
    )

    item: Mapped["PDPItem"] = relationship(back_populates="materials")


class PDPComment(BaseModel):
    __tablename__ = "pdp_comments"

    pdp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pdps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pdp_items.id", ondelete="CASCADE"),
        nullable=True,
    )
    material_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pdp_item_materials.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(String(2000), nullable=False)
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
    )

    user = relationship("User", lazy="selectin")
    pdp: Mapped["PDP"] = relationship(back_populates="comments")


# --- GF12: PDP Versioning ---


class PDPVersion(BaseModel):
    __tablename__ = "pdp_versions"

    pdp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pdps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    pdp: Mapped["PDP"] = relationship()
