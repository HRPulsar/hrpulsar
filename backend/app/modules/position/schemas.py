from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.employee.schemas import EmployeeAlert

LifecycleStatus = Literal["active", "on_hold", "frozen", "closed"]


class PositionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None
    division_id: uuid.UUID | None = None
    headcount: int | None = Field(default=None, ge=0)
    lifecycle_status: LifecycleStatus | None = None


class PositionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None
    division_id: uuid.UUID | None = None
    headcount: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    lifecycle_status: LifecycleStatus | None = None


class PositionDictionaryRef(BaseModel):
    """HRP-180: spec/grade option exposed in the Position payload so the
    vacancy form can populate its multi-selects without a second call."""

    id: uuid.UUID
    title: str | None = None


class PositionRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    title: str
    description: str | None
    specialization_id: uuid.UUID | None
    specialization_title: str | None = None
    grade_id: uuid.UUID | None
    grade_title: str | None = None
    division_id: uuid.UUID | None
    division_name: str | None = None
    headcount: int | None
    is_active: bool
    lifecycle_status: LifecycleStatus
    source: str
    employee_count: int = 0
    # HRP-180: available spec/grade pool the vacancy multi-select reads from.
    # Currently mirrors the single-value (specialization_id, grade_id) so the
    # form has a non-empty universe even when only one option exists.
    specializations: list[PositionDictionaryRef] = []
    grades: list[PositionDictionaryRef] = []
    # HRP-57 E8: computed inheritance from GradeSpecialization for the
    # (specialization_id, grade_id) pair. None when the pair has no profile
    # row or the position is missing one side of the pair. The Position page
    # renders salary as read-only — editing happens on Specialization.
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    # HRP-57 E8: derived from headcount - employee_count, clipped at 0. None
    # when headcount is unset (no plan → no vacancy concept).
    vacancy_count: int | None = None
    # HRP-57 E8: True iff the (spec, grade) pair has at least one
    # GradeCompetenceLink. Drives the "⚠ Matrix not configured" banner.
    matrix_configured: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class PositionList(BaseModel):
    items: list[PositionRead]
    total: int


class PositionBulkAction(BaseModel):
    ids: list[uuid.UUID]
    action: Literal["approve", "reject"]


class PositionEmployeeRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str | None = None
    user_email: str | None = None
    position_title: str | None = None
    specialization_title: str | None = None
    grade_title: str | None = None
    # HRP-175: division_id surfaces so the Division cell in the unified
    # EmployeeList can deep-link to /company/divisions/{id}.
    division_id: uuid.UUID | None = None
    division_name: str | None = None
    hire_date: date
    status: str
    avatar_url: str | None = None
    alert: EmployeeAlert | None = None

    model_config = {"from_attributes": True}


class PositionStatusUpdate(BaseModel):
    lifecycle_status: LifecycleStatus


class PositionOccupancy(BaseModel):
    position_id: uuid.UUID
    assigned: int
    headcount: int | None = None
    vacant: int | None = None


class PositionMatrixStatus(BaseModel):
    configured: bool
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None
    grade_specialization_id: uuid.UUID | None = None
    link_count: int = 0


class PositionIndicatorRead(BaseModel):
    id: uuid.UUID
    title: str
    weight: int
    sort_index: int
    skill_level_id: uuid.UUID
    skill_level_title: str | None = None
    # HRP-479: origin levels localize via reference.skillLevel.*.
    skill_level_i18n_key: str | None = None


class PositionCompetenceRead(BaseModel):
    competence_id: uuid.UUID
    title: str
    description: str | None = None
    group_id: uuid.UUID
    group_title: str | None = None
    skill_level_id: uuid.UUID
    skill_level_title: str | None = None
    skill_level_i18n_key: str | None = None
    indicators: list[PositionIndicatorRead] = []


class PositionMatrix(BaseModel):
    configured: bool
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None
    grade_specialization_id: uuid.UUID | None = None
    competences: list[PositionCompetenceRead] = []
