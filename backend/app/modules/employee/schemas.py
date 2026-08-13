from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.currency import installation_currency


def _ensure_past(value: date | None, field: str) -> date | None:
    """HRP-219/HRP-220: enforce dates referenced as "in the past" (latest
    allowed = yesterday). Used by Previous Employment and Course
    completed_date — the calendar in the UI is bounded the same way."""
    if value is None:
        return value
    if value >= date.today():
        raise ValueError(f"{field} must be in the past")
    return value


def _ensure_order(
    start: date | None,
    end: date | None,
    *,
    start_field: str = "start_date",
    end_field: str = "end_date",
) -> None:
    if start is not None and end is not None and start > end:
        raise ValueError(f"{start_field} must be on or before {end_field}")

# --- Available users (for employee creation dropdown) ---


class AvailableUser(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    origin: str  # "invited" or "self-registered"

    model_config = {"from_attributes": True}


# --- Employee ---


class EmployeeCreate(BaseModel):
    user_id: uuid.UUID
    division_id: uuid.UUID | None = None
    position_id: uuid.UUID | None = None
    position_title: str | None = Field(default=None, max_length=255)
    hire_date: date


class EmployeeUpdate(BaseModel):
    division_id: uuid.UUID | None = None
    position_id: uuid.UUID | None = None
    position_title: str | None = Field(default=None, max_length=255)
    status: str | None = Field(
        default=None, pattern="^(active|inactive|on_leave|terminated)$"
    )
    # HRP-121: Name/Last name are editable from the same Edit dialog. The
    # values land on the underlying User, but the service exposes them here
    # so the frontend can drive the whole edit from a single PUT.
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)


EmployeeAlertCodeLiteral = Literal[
    "user_inactive",
    "profile_incomplete",
    "assessment_overdue",
    "assessment_pending",
    "pdp_pending_review",
]


class EmployeeAlert(BaseModel):
    """Single alert payload returned alongside an employee record."""

    code: EmployeeAlertCodeLiteral
    label: str


class EmployeeRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    division_id: uuid.UUID | None
    position_id: uuid.UUID | None = None
    position_title: str | None = None
    specialization_id: uuid.UUID | None = None
    specialization_title: str | None = None
    grade_id: uuid.UUID | None = None
    grade_title: str | None = None
    hire_date: date
    status: str
    # HRP-246: stamped when ``status`` mutates; nullable for rows that
    # existed before the migration. Status KPI tile renders "since
    # {status_changed_at}" and falls back to ``created_at`` when null.
    status_changed_at: datetime | None = None
    tenant_id: uuid.UUID
    created_at: datetime
    user_email: str | None = None
    user_name: str | None = None
    # HRP-246: stamped on the user's first successful login. Tenure KPI
    # tile uses it for "joined {first_login_at}"; falls back to
    # ``hire_date`` when null (never logged in).
    user_first_login_at: datetime | None = None
    division_name: str | None = None
    avatar_url: str | None = None
    alert: EmployeeAlert | None = None

    model_config = {"from_attributes": True}


class EmployeeList(BaseModel):
    items: list[EmployeeRead]
    total: int


# --- Events ---


class EmployeeEventCreate(BaseModel):
    event_type: str = Field(max_length=50)
    description: str | None = Field(default=None, max_length=1000)
    event_date: date
    metadata: dict[str, Any] | None = None


class EmployeeEventRead(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    event_type: str
    description: str | None
    event_date: date
    metadata: dict[str, Any] | None = None
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- GF1: Work Experience ---


class WorkExperienceCreate(BaseModel):
    # HRP-151: the Current Employment block writes Division + Position +
    # Start as the required triad. Legacy `title`/`role`/`competence_ids`
    # stay optional so the importer and old project-style rows keep
    # round-tripping without a separate code path.
    division_id: uuid.UUID
    position_id: uuid.UUID
    start_date: date
    end_date: date | None = None
    description: str | None = None
    title: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=255)
    competence_ids: list[uuid.UUID] = []

    @model_validator(mode="after")
    def _check_dates(self) -> WorkExperienceCreate:
        # HRP-219 Task 3: Current Employment Start must be <= End when
        # both are provided.
        _ensure_order(self.start_date, self.end_date)
        return self


class WorkExperienceUpdate(BaseModel):
    division_id: uuid.UUID | None = None
    position_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=255)
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    competence_ids: list[uuid.UUID] | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> WorkExperienceUpdate:
        _ensure_order(self.start_date, self.end_date)
        return self


class CompetenceRef(BaseModel):
    id: uuid.UUID
    title: str


class WorkExperienceRead(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    division_id: uuid.UUID | None = None
    position_id: uuid.UUID | None = None
    division_name: str | None = None
    position_title: str | None = None
    title: str | None
    role: str | None
    description: str | None
    start_date: date
    end_date: date | None
    duration: str | None = None
    competences: list[CompetenceRef] = []
    created_at: datetime

    model_config = {"from_attributes": True}


# --- GF1: Previous Employment ---


class PreviousEmploymentCreate(BaseModel):
    # HRP-219 Tasks 1 + 2: Company name, Position, Start date, End date
    # are required, both dates must lie strictly in the past, and Start
    # must be on or before End.
    company_name: str = Field(min_length=1, max_length=255)
    position: str = Field(min_length=1, max_length=255)
    description: str | None = None
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _check_dates(self) -> PreviousEmploymentCreate:
        _ensure_past(self.start_date, "start_date")
        _ensure_past(self.end_date, "end_date")
        _ensure_order(self.start_date, self.end_date)
        return self


class PreviousEmploymentUpdate(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    position: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> PreviousEmploymentUpdate:
        _ensure_past(self.start_date, "start_date")
        _ensure_past(self.end_date, "end_date")
        _ensure_order(self.start_date, self.end_date)
        return self


class PreviousEmploymentRead(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    company_name: str
    position: str
    description: str | None
    start_date: date
    end_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- GF2: Education ---


class EducationCreate(BaseModel):
    # HRP-220: Institution, Degree, Field of Study, Start date are
    # required (end_date stays optional for ongoing studies). Start must
    # be on or before End when both are present.
    institution: str = Field(min_length=1, max_length=255)
    degree: str = Field(min_length=1, max_length=100)
    field_of_study: str = Field(min_length=1, max_length=255)
    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> EducationCreate:
        _ensure_order(self.start_date, self.end_date)
        return self


class EducationUpdate(BaseModel):
    institution: str | None = Field(default=None, min_length=1, max_length=255)
    degree: str | None = Field(default=None, min_length=1, max_length=100)
    field_of_study: str | None = Field(default=None, min_length=1, max_length=255)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> EducationUpdate:
        _ensure_order(self.start_date, self.end_date)
        return self


class EducationRead(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    institution: str
    degree: str
    field_of_study: str
    start_date: date
    end_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- GF2: Courses & Certifications ---


class CourseCreate(BaseModel):
    # HRP-220: Title and Completed date are required, Completed date
    # must be in the past, and Completed <= Expire when both are set.
    title: str = Field(min_length=1, max_length=255)
    provider: str | None = Field(default=None, max_length=255)
    certificate_url: str | None = Field(default=None, max_length=500)
    completed_date: date
    expiry_date: date | None = None
    competence_ids: list[uuid.UUID] = []

    @model_validator(mode="after")
    def _check_dates(self) -> CourseCreate:
        _ensure_past(self.completed_date, "completed_date")
        _ensure_order(
            self.completed_date,
            self.expiry_date,
            start_field="completed_date",
            end_field="expiry_date",
        )
        return self


class CourseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    provider: str | None = Field(default=None, max_length=255)
    certificate_url: str | None = Field(default=None, max_length=500)
    completed_date: date | None = None
    expiry_date: date | None = None
    competence_ids: list[uuid.UUID] | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> CourseUpdate:
        _ensure_past(self.completed_date, "completed_date")
        _ensure_order(
            self.completed_date,
            self.expiry_date,
            start_field="completed_date",
            end_field="expiry_date",
        )
        return self


class CourseRead(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    title: str
    provider: str | None
    certificate_url: str | None
    completed_date: date | None
    expiry_date: date | None
    competences: list[CompetenceRef] = []
    created_at: datetime

    model_config = {"from_attributes": True}


# --- HRP-153: Competence Overview ---


class EmployeeCompetenceLevelBreakdown(BaseModel):
    """One row of the per-level breakdown shown in the (i) popup.

    Mirrors a slice of the HRP-90 assessment cascade so each Competences-tab
    row can render the same Skill level / Percent table the Assessments
    Results page shows.
    """

    skill_level_id: uuid.UUID
    skill_level_title: str
    skill_level_sort_index: int = 0
    percent: int


class EmployeeCompetenceRow(BaseModel):
    competence_id: uuid.UUID
    competence_title: str
    group_id: uuid.UUID | None = None
    skill_level_id: uuid.UUID
    skill_level_title: str
    skill_level_sort_index: int = 0
    percent: int | None = None
    assessment_id: uuid.UUID | None = None
    completed_at: datetime | None = None
    level_breakdown: list[EmployeeCompetenceLevelBreakdown] = []


class EmployeeCompetenceOverview(BaseModel):
    """Two-block competence summary for the Employee Competences tab.

    `current_position` lists every (competence, skill_level) pair the
    employee's current position requires through its grade-specialization,
    populated with the latest qualifying assessment percent (or null when
    the required level was never reached). `other` lists one row per
    competence the employee was assessed on at a level higher than what
    Current Position already covers -- the row's level is the highest
    assessed target and `percent` is averaged over the breakdown rows up
    to that level.
    """

    current_position: list[EmployeeCompetenceRow]
    other: list[EmployeeCompetenceRow]


# --- GF5: Compensation ---


class CompensationCreate(BaseModel):
    type: str = Field(max_length=50, pattern="^(salary|bonus|allowance)$")
    amount: int = Field(gt=0)
    # HRP-439: installation currency, not a hardcoded literal.
    currency: str = Field(
        default_factory=installation_currency, max_length=3, min_length=3
    )
    effective_date: date
    end_date: date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> CompensationCreate:
        # HRP-221 Bug 1: Effective date must be on or before End date.
        _ensure_order(
            self.effective_date,
            self.end_date,
            start_field="effective_date",
            end_field="end_date",
        )
        return self


class CompensationUpdate(BaseModel):
    type: str | None = Field(
        default=None, max_length=50, pattern="^(salary|bonus|allowance)$"
    )
    amount: int | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, max_length=3, min_length=3)
    effective_date: date | None = None
    end_date: date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> CompensationUpdate:
        _ensure_order(
            self.effective_date,
            self.end_date,
            start_field="effective_date",
            end_field="end_date",
        )
        return self


class CompensationRead(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    type: str
    amount: int
    currency: str
    effective_date: date
    end_date: date | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
