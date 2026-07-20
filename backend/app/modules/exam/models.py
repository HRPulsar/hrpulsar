import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import BaseModel, TenantMixin


class MassExam(BaseModel, TenantMixin):
    __tablename__ = "mass_exams"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    initiator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", server_default="draft"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    questions: Mapped[list["ExamQuestion"]] = relationship(
        back_populates="mass_exam",
        cascade="all, delete-orphan",
        order_by="ExamQuestion.sort_index",
    )
    pass_marks: Mapped[list["ExamPassMark"]] = relationship(
        back_populates="mass_exam", cascade="all, delete-orphan"
    )
    exams: Mapped[list["Exam"]] = relationship(
        back_populates="mass_exam", cascade="all, delete-orphan"
    )


class ExamQuestion(BaseModel):
    __tablename__ = "exam_questions"

    mass_exam_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mass_exams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    question_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # single_choice, multiple_choice, essay
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    weight: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    image_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )

    mass_exam: Mapped["MassExam"] = relationship(back_populates="questions")
    options: Mapped[list["QuestionOption"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="QuestionOption.sort_index",
    )


class QuestionOption(BaseModel):
    __tablename__ = "question_options"

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exam_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_correct: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    question: Mapped["ExamQuestion"] = relationship(back_populates="options")


class ExamPassMark(BaseModel):
    __tablename__ = "exam_pass_marks"

    mass_exam_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mass_exams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dictionary_items.id"), nullable=True
    )
    specialization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dictionary_items.id"), nullable=True
    )
    min_score_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_score_points: Mapped[int | None] = mapped_column(Integer, nullable=True)

    mass_exam: Mapped["MassExam"] = relationship(back_populates="pass_marks")


class Exam(BaseModel, TenantMixin):
    __tablename__ = "exams"

    mass_exam_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mass_exams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="assigned", server_default="assigned"
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    employee = relationship("Employee", lazy="selectin")
    mass_exam: Mapped["MassExam"] = relationship(back_populates="exams")
    answers: Mapped[list["ExamAnswer"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan"
    )


class ExamAnswer(BaseModel):
    __tablename__ = "exam_answers"
    __table_args__ = (
        # HRP-328: one answer row per question per exam — the take sheet
        # re-answers via upsert, and concurrent autosaves must not stack.
        UniqueConstraint(
            "exam_id", "question_id", name="uq_exam_answer_exam_question"
        ),
    )

    exam_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_questions.id"), nullable=False
    )
    selected_option_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    text_answer: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    exam: Mapped["Exam"] = relationship(back_populates="answers")
