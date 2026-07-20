import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import BaseModel, TenantMixin


class GradeSpecialization(BaseModel, TenantMixin):
    """Links a grade to a specialization within a tenant's career ladder."""

    __tablename__ = "grade_specializations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "grade_id",
            "specialization_id",
            name="uq_grade_spec_tenant",
        ),
        CheckConstraint(
            "passing_score IS NULL OR passing_score BETWEEN 0 AND 100",
            name="ck_grade_spec_passing_score_range",
        ),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name="ck_grade_spec_salary_range",
        ),
    )

    grade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    specialization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="RUB", server_default="RUB"
    )
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    passing_score: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=75, server_default="75"
    )

    competence_links: Mapped[list["GradeCompetenceLink"]] = relationship(
        back_populates="grade_specialization",
        cascade="all, delete-orphan",
    )
    grade = relationship("DictionaryItem", foreign_keys=[grade_id], lazy="selectin")


class GradeCompetenceLink(BaseModel):
    """Which competence at which skill level is required for a grade+specialization."""

    __tablename__ = "grade_competence_links"

    grade_specialization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("grade_specializations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competences.id", ondelete="CASCADE"),
        nullable=False,
    )
    skill_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skill_levels.id", ondelete="CASCADE"),
        nullable=False,
    )

    grade_specialization: Mapped["GradeSpecialization"] = relationship(
        back_populates="competence_links"
    )
    competence = relationship("Competence", lazy="selectin")
    skill_level = relationship("SkillLevel", lazy="selectin")
