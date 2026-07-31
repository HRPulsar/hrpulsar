from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SpecializationGradeAttrs(BaseModel):
    """Spec×Grade attributes editable from the Specialization page."""

    description: str | None = None
    requirements: str | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="RUB", min_length=3, max_length=3)
    passing_score: int | None = Field(default=None, ge=0, le=100)


class SpecializationGradeRead(BaseModel):
    id: uuid.UUID  # GradeSpecialization.id (Spec×Grade pair)
    grade_id: uuid.UUID
    grade_title: str
    # HRP-479: origin grades localize via reference.dictionary.grade.*.
    grade_i18n_key: str | None = None
    description: str | None = None
    requirements: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "RUB"
    passing_score: int | None = None
    sort_index: int = 0
    matrix_status: str = "empty"  # 'empty' | 'configured'
    competence_count: int = 0
    # HRP-288: the spec detail page renders an Inactive chip next to the
    # title when the underlying dictionary grade has been deactivated
    # (origin override or custom row), so consumers can tell at a glance
    # that the chain still references a hidden grade.
    grade_is_active: bool = True


class SpecializationRead(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    is_active: bool = True
    grade_count: int = 0
    position_count: int = 0
    assigned_count: int = 0
    headcount_total: int = 0
    created_at: datetime | None = None


class SpecializationDetail(SpecializationRead):
    grades: list[SpecializationGradeRead] = []


class PositionInDivision(BaseModel):
    id: uuid.UUID
    title: str
    grade_id: uuid.UUID | None = None
    grade_title: str | None = None
    headcount: int | None = None
    assigned: int = 0
    vacant: int = 0
    lifecycle_status: str = "active"


class DivisionPositionsBlock(BaseModel):
    division_id: uuid.UUID | None = None
    division_name: str | None = None
    positions: list[PositionInDivision] = []


class MatrixCellRead(BaseModel):
    competence_id: uuid.UUID
    competence_title: str | None = None
    skill_level_id: uuid.UUID
    skill_level_title: str | None = None


class MatrixCellWrite(BaseModel):
    competence_id: uuid.UUID
    skill_level_id: uuid.UUID


class MatrixUpsert(BaseModel):
    links: list[MatrixCellWrite]


class MatrixGradeBulk(BaseModel):
    """Per-grade payload for the bulk matrix endpoint.

    `links` fully replaces existing links for the specified Spec×Grade pair.
    """

    grade_id: uuid.UUID
    links: list[MatrixCellWrite]


class MatrixBulkUpsert(BaseModel):
    """Bulk replacement of the matrix across multiple grades of one spec.

    Grades omitted from the payload retain their current state in DB
    (partial bulk save is allowed). The server normalizes every competence
    so that levels are monotonically non-decreasing along grade.sort_index;
    cascading inserts are written for grades not present in the payload.
    """

    grades: list[MatrixGradeBulk]


class MatrixBulkGradeRead(BaseModel):
    grade_id: uuid.UUID
    grade_title: str | None = None
    grade_sort_index: int = 0
    links: list[MatrixCellRead] = []


class MatrixBulkRead(BaseModel):
    grades: list[MatrixBulkGradeRead] = []


# ---------------------------------------------------------------------------
# Grades CRUD (HRP-57 P1) — manage Spec×Grade pairs from the Specialization
# page without going through the legacy `/grade-system/chains` endpoint.
# ---------------------------------------------------------------------------


class GradesBulkAdd(BaseModel):
    """Add multiple grades to a specialization in one call.

    Pairs are created with `sort_index` running from the current max+1, in
    the order given. Existing pairs are skipped silently (idempotent).
    """

    grade_ids: list[uuid.UUID]


class GradeReorderEntry(BaseModel):
    grade_id: uuid.UUID
    sort_index: int = Field(ge=0)


class GradesReorder(BaseModel):
    orders: list[GradeReorderEntry]


class GradePatch(BaseModel):
    """In-place edit of a Spec×Grade pair from the matrix header."""

    description: str | None = None
    requirements: str | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    passing_score: int | None = Field(default=None, ge=0, le=100)
