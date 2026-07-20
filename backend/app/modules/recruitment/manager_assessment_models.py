"""HRP-186: manager assessment + invited evaluator models.

Tables here live with a ``recruitment_`` prefix because the 360-review
module already owns the plain ``assessments``, ``assessment_competences``,
etc. namespace. The recruitment manager assessment is structurally
independent — vacancy-scoped, multi-round, with public-token invited
evaluators on top of the existing :class:`AssessmentInvite` row.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import BaseModel, TenantMixin


class AssessmentScale(BaseModel, TenantMixin):
    """Tenant-scoped scale (FR-19).

    The scale is the same shape across every vacancy that adopts it;
    once a vacancy starts collecting scores, that vacancy keeps a JSONB
    snapshot in ``vacancies.assessment_scale_snapshot`` so tenant-level
    edits never reach into already-scored data.
    """

    __tablename__ = "recruitment_assessment_scales"
    __table_args__ = (
        Index(
            "ix_recr_assess_scales_one_default",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default AND archived_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    divergence_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default="2"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )


class AssessmentScaleLevel(BaseModel):
    """One level inside a scale (e.g. ``3 — Meets expectations, weight 50``)."""

    __tablename__ = "recruitment_assessment_scale_levels"
    __table_args__ = (
        UniqueConstraint("scale_id", "value", name="uq_recr_scale_level_value"),
    )

    scale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "recruitment_assessment_scales.id", ondelete="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    color: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class AssessmentRound(BaseModel, TenantMixin):
    """One round of evaluation on a candidate-vacancy.

    ``type`` is ``pre_interview`` | ``interview`` | ``final``. ``interview``
    rounds carry a ``round_number`` starting at 1; the others leave it
    NULL because only one of each is allowed per candidate-vacancy.
    """

    __tablename__ = "recruitment_assessment_rounds"
    __table_args__ = (
        Index(
            "ix_recr_rounds_cv_type_num",
            "candidate_vacancy_id",
            "type",
            "round_number",
        ),
    )

    candidate_vacancy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_vacancies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    round_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="in_progress",
        server_default="in_progress",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AssessmentRoundEvaluator(Base):
    """Join row: an internal user invited to evaluate inside a round.

    Pure association table — composite PK on (round_id, user_id), no
    synthetic id and no timestamp columns. Extending ``BaseModel`` here
    would make SQLAlchemy SELECT `id`, `created_at`, `updated_at` which
    the migration intentionally does not create.
    """

    __tablename__ = "recruitment_assessment_round_evaluators"

    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "recruitment_assessment_rounds.id", ondelete="CASCADE"
        ),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RecruitmentAssessment(BaseModel, TenantMixin):
    """Per-evaluator evaluation sheet inside a round.

    ``evaluator_type`` is ``user`` (logged-in tenant member) or
    ``invited`` (public token). At most one row per
    (round, evaluator_user_id) — and one per (round, evaluator_invite_id).
    """

    __tablename__ = "recruitment_assessments"
    __table_args__ = (
        Index(
            "ix_recr_assessments_round_user",
            "round_id",
            "evaluator_user_id",
            unique=True,
            postgresql_where=text("evaluator_user_id IS NOT NULL"),
        ),
        Index(
            "ix_recr_assessments_round_invite",
            "round_id",
            "evaluator_invite_id",
            unique=True,
            postgresql_where=text("evaluator_invite_id IS NOT NULL"),
        ),
    )

    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "recruitment_assessment_rounds.id", ondelete="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    evaluator_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="user",
        server_default="user",
    )
    evaluator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    evaluator_invite_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_invites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    evaluator_display_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    final_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )


class AssessmentCompetenceScore(BaseModel, TenantMixin):
    """One competence score within an assessment sheet."""

    __tablename__ = "recruitment_assessment_competence_scores"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id",
            "competence_id",
            name="uq_recr_assessment_competence",
        ),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "recruitment_assessments.id", ondelete="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    score_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="manual",
        server_default="manual",
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class AssessmentIndicatorScore(BaseModel, TenantMixin):
    """One indicator score within an assessment sheet."""

    __tablename__ = "recruitment_assessment_indicator_scores"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id",
            "indicator_id",
            name="uq_recr_assessment_indicator",
        ),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "recruitment_assessments.id", ondelete="CASCADE"
        ),
        nullable=False,
        index=True,
    )
    indicator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    score_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class PublicAssessmentIPBlock(BaseModel):
    """Rate-limit deny-list for the public assessment endpoint.

    Populated when an IP submits more than the configured threshold of
    invalid tokens in a short window; cleared automatically after
    ``blocked_until`` passes.
    """

    __tablename__ = "public_assessment_ip_blocks"

    ip: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    blocked_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


__all__ = [
    "AssessmentScale",
    "AssessmentScaleLevel",
    "AssessmentRound",
    "AssessmentRoundEvaluator",
    "RecruitmentAssessment",
    "AssessmentCompetenceScore",
    "AssessmentIndicatorScore",
    "PublicAssessmentIPBlock",
]
