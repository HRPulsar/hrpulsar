from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

# --- Pagination ---


class PaginatedResponse(BaseModel):
    items: list = []
    total: int = 0


# --- Batch common ---


class BatchItemResult(BaseModel):
    index: int
    success: bool
    id: uuid.UUID | None = None
    error: str | None = None


class BatchResponse(BaseModel):
    total: int
    created: int
    errors: int
    results: list[BatchItemResult]


# --- Batch Employee ---


class EmployeeBatchItem(BaseModel):
    email: str = Field(max_length=255)
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    position: str = Field(
        default="Employee", max_length=255
    )  # text, resolved to position_id
    position_id: uuid.UUID | None = None
    hire_date: date
    division_id: uuid.UUID | None = None


class EmployeeBatchCreate(BaseModel):
    items: list[EmployeeBatchItem] = Field(min_length=1, max_length=100)


class EmployeeBatchUpdateItem(BaseModel):
    id: uuid.UUID
    position: str | None = Field(
        default=None, max_length=255
    )  # text, resolved to position_id
    position_id: uuid.UUID | None = None
    division_id: uuid.UUID | None = None
    status: str | None = Field(
        default=None, pattern="^(active|inactive|on_leave|terminated)$"
    )


class EmployeeBatchUpdate(BaseModel):
    items: list[EmployeeBatchUpdateItem] = Field(min_length=1, max_length=100)


# --- Batch Division ---


class DivisionBatchItem(BaseModel):
    name: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=500)
    parent_id: uuid.UUID | None = None


class DivisionBatchCreate(BaseModel):
    items: list[DivisionBatchItem] = Field(min_length=1, max_length=100)


# --- Batch Specialization ---


class SpecializationBatchItem(BaseModel):
    title: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=500)


class SpecializationBatchCreate(BaseModel):
    items: list[SpecializationBatchItem] = Field(min_length=1, max_length=100)


# --- Batch Grade ---


class GradeBatchItem(BaseModel):
    title: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=500)
    sort_index: int = 0


class GradeBatchCreate(BaseModel):
    items: list[GradeBatchItem] = Field(min_length=1, max_length=100)


# --- Batch Assessment ---


class AssessmentBatchCreate(BaseModel):
    employee_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    type_code: str  # self, 180, 360
    title: str | None = Field(default=None, max_length=255)
    specialization_id: uuid.UUID | None = None
    grade_id: uuid.UUID | None = None
    scale_id: uuid.UUID | None = None
    ended_at: datetime | None = None


# --- Batch Exam ---


class ExamBatchAssign(BaseModel):
    mass_exam_id: uuid.UUID
    employee_ids: list[uuid.UUID] | None = None
    division_ids: list[uuid.UUID] | None = None
    specialization_ids: list[uuid.UUID] | None = None
