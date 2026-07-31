from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class GradeOptionRead(BaseModel):
    id: uuid.UUID
    title: str
    # HRP-479: options are dictionary rows — origin ones localize on the
    # frontend via reference.dictionary.grade.*.
    i18n_key: str | None = None


class GradeCompetenceLinkCreate(BaseModel):
    competence_id: uuid.UUID
    skill_level_id: uuid.UUID


class GradeCompetenceLinkRead(BaseModel):
    id: uuid.UUID
    competence_id: uuid.UUID
    competence_title: str | None = None
    skill_level_id: uuid.UUID
    skill_level_title: str | None = None

    model_config = {"from_attributes": True}


class GradeSpecializationCreate(BaseModel):
    grade_id: uuid.UUID
    specialization_id: uuid.UUID
    description: str | None = None
    requirements: str | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="RUB", min_length=3, max_length=3)
    sort_index: int = 0
    passing_score: int | None = Field(default=75, ge=0, le=100)
    competence_links: list[GradeCompetenceLinkCreate] = []


class GradeSpecializationUpdate(BaseModel):
    description: str | None = None
    requirements: str | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    sort_index: int | None = None
    passing_score: int | None = Field(default=None, ge=0, le=100)


class GradeSpecializationRead(BaseModel):
    id: uuid.UUID
    grade_id: uuid.UUID
    grade_title: str
    specialization_id: uuid.UUID
    description: str | None
    requirements: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "RUB"
    sort_index: int
    passing_score: int | None = None
    tenant_id: uuid.UUID
    created_at: datetime
    competence_links: list[GradeCompetenceLinkRead] = []

    model_config = {"from_attributes": True}
