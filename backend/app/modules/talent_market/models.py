import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import BaseModel, TenantMixin


class TalentCard(BaseModel, TenantMixin):
    __tablename__ = "talent_cards"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    card_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # vacancy, talent, project
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", server_default="draft"
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    division_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("divisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Legacy single terminal-date column. HRP-92 REDO splits the date into
    # status-specific columns; ``closed_at`` is kept on the model for
    # backwards compatibility with historic rows and the GET response —
    # new transitions write the matching column below instead.
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # HRP-92 REDO: assessment-style status dates. `completed_at` is set on
    # the Complete transition; `cancelled_at` on Cancel.
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # HRP-128: card-level required match% for the Required competencies block.
    # 50..100, defaults to 80 on create. Replaces the per-row match_percent
    # the step-3 dialog used to set on each TalentCardCompetence row.
    match_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=80, server_default="80"
    )
    # HRP-242: stamp of the last Candidates recompute (auto-populate or
    # Change-candidates save). Drives the "last match: today / yesterday /
    # Month dd" label in the Candidates block header plus the refresh
    # action. NULL means the auto-pool hasn't been run yet.
    last_matched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    specializations: Mapped[list["TalentCardSpecialization"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
    competences: Mapped[list["TalentCardCompetence"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
    requirements: Mapped[list["TalentCardRequirement"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
    candidates: Mapped[list["TalentCandidate"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )


class TalentCardSpecialization(BaseModel):
    __tablename__ = "talent_card_specializations"

    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("talent_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # HRP-281: when a tenant is dropped the dictionary_items rows cascade
    # via tenant_id; the talent_card_specializations FKs need to cascade
    # along (or set NULL for the nullable grade) so the tenant delete
    # doesn't fail with RESTRICT.
    specialization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    grade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    min_experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)

    card: Mapped["TalentCard"] = relationship(back_populates="specializations")


class TalentCardCompetence(BaseModel):
    __tablename__ = "talent_card_competences"

    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("talent_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # HRP-281: mirror the cascade hygiene fix on
    # TalentCardSpecialization — when a tenant is dropped, competences
    # and skill_levels are cascade-deleted via tenant_id, and the
    # talent_card_competences FKs need to follow.
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
    match_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)

    card: Mapped["TalentCard"] = relationship(back_populates="competences")


class TalentCardRequirement(BaseModel):
    __tablename__ = "talent_card_requirements"

    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("talent_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    min_experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)

    card: Mapped["TalentCard"] = relationship(back_populates="requirements")


class TalentCandidate(BaseModel):
    __tablename__ = "talent_candidates"

    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("talent_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    # HRP-214: status reflects the current match evaluation. `matched` /
    # `not_matched` replace the legacy `nominated`; `appointed` is set by
    # the Appoint action. Default is `not_matched` — the safer default for
    # rows the caller doesn't explicitly score.
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="not_matched",
        server_default="not_matched",
    )
    match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="SET NULL"),
        nullable=True,
    )
    pdp_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pdps.id", ondelete="SET NULL"), nullable=True
    )
    response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    appointed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    employee = relationship("Employee", lazy="selectin")
    card: Mapped["TalentCard"] = relationship(back_populates="candidates")
