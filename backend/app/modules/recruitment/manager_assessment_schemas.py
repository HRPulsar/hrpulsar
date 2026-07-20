"""HRP-186: pydantic schemas for the manager-assessment subsystem."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ScaleLevelIn(BaseModel):
    value: int = Field(ge=0, le=99)
    label: str = Field(min_length=1, max_length=100)
    description: str | None = None
    weight: int = Field(ge=0, le=100)
    color: str | None = Field(default=None, max_length=30)
    sort_order: int = 0


class ScaleLevelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    value: int
    label: str
    description: str | None
    weight: int
    color: str | None
    sort_order: int


class ScaleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    is_default: bool = False
    divergence_threshold: int = Field(default=2, ge=1, le=10)
    levels: list[ScaleLevelIn]

    @field_validator("levels")
    @classmethod
    def _check_levels(cls, levels: list[ScaleLevelIn]) -> list[ScaleLevelIn]:
        if not 2 <= len(levels) <= 10:
            raise ValueError("Scale must have between 2 and 10 levels")
        values = [lvl.value for lvl in levels]
        if len(set(values)) != len(values):
            raise ValueError("Level values must be unique within the scale")
        return levels


class ScaleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    is_default: bool | None = None
    divergence_threshold: int | None = Field(default=None, ge=1, le=10)
    levels: list[ScaleLevelIn] | None = None

    @field_validator("levels")
    @classmethod
    def _check_levels(
        cls, levels: list[ScaleLevelIn] | None
    ) -> list[ScaleLevelIn] | None:
        if levels is None:
            return None
        if not 2 <= len(levels) <= 10:
            raise ValueError("Scale must have between 2 and 10 levels")
        values = [lvl.value for lvl in levels]
        if len(set(values)) != len(values):
            raise ValueError("Level values must be unique within the scale")
        return levels


class ScaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    is_default: bool
    archived_at: datetime | None
    divergence_threshold: int
    version: int
    created_at: datetime
    updated_at: datetime
    levels: list[ScaleLevelOut] = []


class RoundCreate(BaseModel):
    type: Literal["pre_interview", "interview", "final"]
    # ``round_number`` is server-assigned for ``interview``; ignored
    # for the other types. Clients may still pass it for idempotency.
    round_number: int | None = Field(default=None, ge=1, le=50)


class RoundEvaluatorAdd(BaseModel):
    user_id: uuid.UUID


class RoundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_vacancy_id: uuid.UUID
    type: str
    round_number: int | None
    status: str
    created_by: uuid.UUID | None
    completed_at: datetime | None
    archived_at: datetime | None
    archived_reason: str | None
    created_at: datetime
    updated_at: datetime


class CompetenceScoreIn(BaseModel):
    score_value: int | None = Field(default=None, ge=0, le=99)
    score_source: Literal["manual", "computed_from_indicators"] = "manual"
    comment: str | None = None


class CompetenceScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    assessment_id: uuid.UUID
    competence_id: uuid.UUID
    score_value: int | None
    score_source: str
    comment: str | None
    created_at: datetime
    updated_at: datetime


class IndicatorScoreIn(BaseModel):
    competence_id: uuid.UUID
    score_value: int | None = Field(default=None, ge=0, le=99)
    comment: str | None = None


class IndicatorScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    assessment_id: uuid.UUID
    indicator_id: uuid.UUID
    competence_id: uuid.UUID
    score_value: int | None
    comment: str | None
    created_at: datetime
    updated_at: datetime


class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    round_id: uuid.UUID
    evaluator_type: str
    evaluator_user_id: uuid.UUID | None
    evaluator_invite_id: uuid.UUID | None
    evaluator_display_name: str | None
    status: str
    submitted_at: datetime | None
    final_notes: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    competence_scores: list[CompetenceScoreOut] = []
    indicator_scores: list[IndicatorScoreOut] = []


class ManagerAssessmentInviteIn(BaseModel):
    # HRP-350: full RFC-style validation — a bare "Aaa" must be rejected
    # server-side, not only by the browser's type="email" hint.
    email: EmailStr = Field(max_length=255)
    name: str = Field(min_length=2, max_length=255)
    round_id: uuid.UUID | None = None


class ManagerAssessmentInviteCreate(BaseModel):
    invitees: list[ManagerAssessmentInviteIn] = Field(min_length=1, max_length=20)
    round_id: uuid.UUID | None = None
    expires_in_days: int = Field(default=7, ge=1, le=30)
    allow_reediting: bool = True
    personal_message: str | None = Field(default=None, max_length=500)


class ManagerInviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_vacancy_id: uuid.UUID
    round_id: uuid.UUID | None
    email: str
    evaluator_name: str | None
    status: str
    allow_reediting: bool
    expires_at: datetime
    opened_at: datetime | None
    submitted_at: datetime | None
    declined_at: datetime | None
    revoked_at: datetime | None
    delivery_status: str
    delivery_error: str | None
    delivery_retry_count: int
    created_at: datetime


class ExtendInviteIn(BaseModel):
    additional_days: int = Field(ge=1, le=30)


class PublicEvaluatorNameUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)


class PublicAssessmentSubmit(BaseModel):
    confirm: bool = True


__all__ = [
    "ScaleCreate",
    "ScaleUpdate",
    "ScaleOut",
    "ScaleLevelIn",
    "ScaleLevelOut",
    "RoundCreate",
    "RoundEvaluatorAdd",
    "RoundOut",
    "CompetenceScoreIn",
    "CompetenceScoreOut",
    "IndicatorScoreIn",
    "IndicatorScoreOut",
    "AssessmentOut",
    "ManagerAssessmentInviteIn",
    "ManagerAssessmentInviteCreate",
    "ManagerInviteOut",
    "ExtendInviteIn",
    "PublicEvaluatorNameUpdate",
    "PublicAssessmentSubmit",
]
