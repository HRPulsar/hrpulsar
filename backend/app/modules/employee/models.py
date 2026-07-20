import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import BaseModel, TenantMixin


class Employee(BaseModel, TenantMixin):
    __tablename__ = "employees"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    division_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("divisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("positions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    position_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    # HRP-246: stamped on every status mutation so the Employee profile
    # STATUS KPI can render "since {date of last status change}" instead
    # of the row's create timestamp. Nullable for backfill — callers fall
    # back to ``created_at`` when the column is empty.
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    user = relationship("User", lazy="selectin")
    division = relationship("Division", foreign_keys=[division_id], lazy="selectin")
    position = relationship("Position", lazy="selectin")
    events: Mapped[list["EmployeeEvent"]] = relationship(
        back_populates="employee",
        order_by="EmployeeEvent.event_date.desc()",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    work_experiences: Mapped[list["WorkExperience"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    previous_employments: Mapped[list["PreviousEmployment"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    education_records: Mapped[list["Education"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    courses: Mapped[list["Course"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    compensations: Mapped[list["Compensation"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )


class EmployeeEvent(BaseModel):
    __tablename__ = "employee_events"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    # GF11: Change diff
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    employee: Mapped["Employee"] = relationship(back_populates="events")


# --- GF1: Work Experience ---


class WorkExperience(BaseModel, TenantMixin):
    """Current Employment block — a Division/Position spell within the
    current company. Legacy `title`/`role`/`competence_links` columns are
    kept nullable so importer rows and historical project-style entries
    keep rendering, but the rebuilt UI (HRP-151) writes Division + Position
    + Start instead.
    """

    __tablename__ = "work_experiences"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    division_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("divisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("positions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    employee: Mapped["Employee"] = relationship(back_populates="work_experiences")
    # HRP-163: default lazy load (no eager fetch). Callers that read
    # ``.division`` / ``.position`` opt in per-query through
    # ``selectinload(...)`` so future list endpoints don't accidentally
    # fan out to one extra SELECT per row.
    division = relationship("Division")
    position = relationship("Position")
    competence_links: Mapped[list["WorkExperienceCompetence"]] = relationship(
        back_populates="work_experience", cascade="all, delete-orphan"
    )


class PreviousEmployment(BaseModel, TenantMixin):
    """Employment history at other companies."""

    __tablename__ = "previous_employments"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    employee: Mapped["Employee"] = relationship(back_populates="previous_employments")


# --- GF2: Education & Courses ---


class Education(BaseModel, TenantMixin):
    """Formal education (university, college)."""

    __tablename__ = "education"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution: Mapped[str] = mapped_column(String(255), nullable=False)
    degree: Mapped[str] = mapped_column(String(100), nullable=False)
    field_of_study: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    employee: Mapped["Employee"] = relationship(back_populates="education_records")


class Course(BaseModel, TenantMixin):
    """Courses, certifications, training."""

    __tablename__ = "courses"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    certificate_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    employee: Mapped["Employee"] = relationship(back_populates="courses")
    competence_links: Mapped[list["CourseCompetence"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


# --- GF1/GF2 Improve: Competence links ---


class WorkExperienceCompetence(BaseModel):
    """Links a work experience to competences gained."""

    __tablename__ = "work_experience_competences"
    __table_args__ = (
        UniqueConstraint(
            "work_experience_id", "competence_id", name="uq_we_competence"
        ),
    )

    work_experience_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_experiences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competences.id", ondelete="CASCADE"),
        nullable=False,
    )

    work_experience: Mapped["WorkExperience"] = relationship(
        back_populates="competence_links"
    )
    competence = relationship("Competence", lazy="selectin")


class CourseCompetence(BaseModel):
    """Links a course to competences developed."""

    __tablename__ = "course_competences"
    __table_args__ = (
        UniqueConstraint("course_id", "competence_id", name="uq_course_competence"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competences.id", ondelete="CASCADE"),
        nullable=False,
    )

    course: Mapped["Course"] = relationship(back_populates="competence_links")
    competence = relationship("Competence", lazy="selectin")


# --- GF5: Compensation ---


class Compensation(BaseModel, TenantMixin):
    """Salary, bonus, and allowance records."""

    __tablename__ = "compensations"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # salary/bonus/allowance
    amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )  # stored in minor units (cents)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    employee: Mapped["Employee"] = relationship(back_populates="compensations")
