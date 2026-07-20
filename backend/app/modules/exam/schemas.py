from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.validators import not_past_deadline

# --- Status flow ---

TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "cancelled"})

# Manager-driven transitions only. The sent → in_progress hop is automatic,
# fired by the first participant's answer in `service.submit_answer`.
ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"sent", "cancelled"},
    "sent": {"cancelled"},
    "in_progress": {"done", "cancelled"},
    "done": set(),
    "cancelled": set(),
}


# --- MassExam ---


class MassExamCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=250)
    ended_at: datetime | None = None

    _validate_ended_at = field_validator("ended_at")(not_past_deadline)


class MassExamUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=250)
    ended_at: datetime | None = None

    _validate_ended_at = field_validator("ended_at")(not_past_deadline)


class MassExamRead(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    initiator_id: uuid.UUID
    status: str
    tenant_id: uuid.UUID
    started_at: datetime | None
    ended_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    model_config = {"from_attributes": True}


class MassExamDetail(MassExamRead):
    questions: list[QuestionRead] = []
    pass_marks: list[PassMarkRead] = []
    assigned_count: int = 0


# --- Questions ---


class OptionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    sort_index: int = 0
    is_correct: bool = False


class QuestionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=2000)
    question_type: str = Field(pattern="^(single_choice|multiple_choice|essay)$")
    sort_index: int = 0
    weight: int = 1
    image_file_id: uuid.UUID | None = None
    options: list[OptionCreate] = []

    @model_validator(mode="after")
    def _validate_options(self) -> QuestionCreate:
        if self.question_type == "essay":
            return self
        non_empty = [o for o in self.options if o.title.strip()]
        if len(non_empty) < 2:
            raise ValueError(
                "Choice questions require at least 2 options"
            )
        correct = [o for o in non_empty if o.is_correct]
        if not correct:
            raise ValueError(
                "Choice questions require at least one correct option"
            )
        if self.question_type == "single_choice" and len(correct) > 1:
            raise ValueError(
                "Single choice questions allow only one correct option"
            )
        return self


class QuestionUpdate(BaseModel):
    """HRP-228: manager-driven edit of an exam question while the exam is
    still in draft. ``options`` (when provided) replaces the option set
    wholesale — same shape and validation as ``QuestionCreate.options``.
    """

    title: str | None = Field(default=None, min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=2000)
    question_type: str | None = Field(
        default=None, pattern="^(single_choice|multiple_choice|essay)$"
    )
    weight: int | None = Field(default=None, ge=1)
    image_file_id: uuid.UUID | None = None
    options: list[OptionCreate] | None = None

    @model_validator(mode="after")
    def _validate_options(self) -> QuestionUpdate:
        # Only run shape checks here when ``question_type`` is also supplied.
        # When it's omitted, the service layer re-validates against the
        # persisted type so we don't reject partial updates prematurely.
        if self.options is None or self.question_type is None:
            return self
        if self.question_type == "essay":
            return self
        non_empty = [o for o in self.options if o.title.strip()]
        if len(non_empty) < 2:
            raise ValueError("Choice questions require at least 2 options")
        correct = [o for o in non_empty if o.is_correct]
        if not correct:
            raise ValueError("Choice questions require at least one correct option")
        if self.question_type == "single_choice" and len(correct) > 1:
            raise ValueError("Single choice questions allow only one correct option")
        return self


class QuestionRead(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    question_type: str
    sort_index: int
    weight: int
    is_active: bool
    image_file_id: uuid.UUID | None = None
    image_url: str | None = None
    options: list[OptionRead] = []
    model_config = {"from_attributes": True}


class OptionRead(BaseModel):
    id: uuid.UUID
    title: str
    sort_index: int
    is_correct: bool
    model_config = {"from_attributes": True}


# --- PassMark ---


class PassMarkCreate(BaseModel):
    grade_id: uuid.UUID | None = None
    specialization_id: uuid.UUID | None = None
    min_score_percent: int | None = Field(default=None, ge=0, le=100)
    min_score_points: int | None = Field(default=None, ge=0)


class PassMarkUpdate(PassMarkCreate):
    """HRP-226 redo: partial edit of the existing pass mark.

    Same field set as ``PassMarkCreate`` (subclassed so the two can't
    drift); the service applies ``exclude_unset`` semantics.
    """


class PassMarkRead(BaseModel):
    id: uuid.UUID
    grade_id: uuid.UUID | None
    specialization_id: uuid.UUID | None
    min_score_percent: int | None
    min_score_points: int | None
    model_config = {"from_attributes": True}


# --- Exam (individual) ---


class ExamRead(BaseModel):
    id: uuid.UUID
    mass_exam_id: uuid.UUID
    employee_id: uuid.UUID
    status: str
    score: int | None
    max_score: int | None
    started_at: datetime | None
    finished_at: datetime | None
    tenant_id: uuid.UUID
    created_at: datetime
    mass_exam_title: str | None = None
    model_config = {"from_attributes": True}


class ExamAnswerSubmit(BaseModel):
    question_id: uuid.UUID
    selected_option_ids: list[uuid.UUID] | None = None
    text_answer: str | None = Field(default=None, max_length=5000)


# --- HRP-328: employee take & review payloads ---


class TakeOptionRead(BaseModel):
    """Option as shown while taking the exam — no answer key."""

    id: uuid.UUID
    title: str
    sort_index: int


class TakeQuestionRead(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    question_type: str
    sort_index: int
    weight: int
    image_url: str | None = None
    options: list[TakeOptionRead] = []


class SavedAnswerRead(BaseModel):
    question_id: uuid.UUID
    selected_option_ids: list[str] = []
    text_answer: str | None = None


class ExamTakeRead(BaseModel):
    exam_id: uuid.UUID
    status: str
    score: int | None
    max_score: int | None
    mass_exam_title: str | None = None
    questions: list[TakeQuestionRead] = []
    answers: list[SavedAnswerRead] = []


class ReviewAnswerRead(BaseModel):
    selected_option_ids: list[str] = []
    text_answer: str | None = None
    is_correct: bool | None = None
    score: int = 0


class ReviewQuestionRead(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    question_type: str
    sort_index: int
    weight: int
    image_url: str | None = None
    options: list[OptionRead] = []
    answer: ReviewAnswerRead | None = None


class ExamReviewRead(BaseModel):
    exam_id: uuid.UUID
    status: str
    score: int | None
    max_score: int | None
    finished_at: datetime | None = None
    mass_exam_title: str | None = None
    questions: list[ReviewQuestionRead] = []


class ExamResultRead(BaseModel):
    exam_id: uuid.UUID
    score: int
    max_score: int
    passed: bool
    model_config = {"from_attributes": True}


class MassExamResultRead(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str | None = None
    # HRP-333: EmployeeSummaryLine inputs; ``status`` below stays the
    # exam's own state.
    position_title: str | None = None
    employee_status: str | None = None
    can_view_profile: bool = False
    status: str
    score: int | None
    max_score: int | None
    passed: bool | None
    started_at: datetime | None
    finished_at: datetime | None
    model_config = {"from_attributes": True}
