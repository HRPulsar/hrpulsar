"""HRP-234 / HRP-236: status transition model.

- draft → sent / cancelled
- sent → cancelled (sent → in_progress is automatic via submit_answer)
- in_progress → done / cancelled
- done, cancelled — terminal
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.exam import service
from app.modules.exam.schemas import (
    ExamAnswerSubmit,
    MassExamCreate,
    OptionCreate,
    QuestionCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


def _question(weight: int = 5) -> QuestionCreate:
    return QuestionCreate(
        title=f"Q-{uuid.uuid4().hex[:6]}",
        question_type="single_choice",
        weight=weight,
        options=[
            OptionCreate(title="Right", is_correct=True),
            OptionCreate(title="Wrong", is_correct=False),
        ],
    )


async def _seed_draft_with_prereqs(db, tenant, user, employee):
    me = await service.create_mass_exam(
        db, tenant.id, user.id, MassExamCreate(title="HRP-234")
    )
    q = await service.add_question(db, tenant.id, me["id"], _question())
    exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
    return me, q, exams[0]


class TestForbiddenTransitions:
    async def test_draft_to_done_rejected(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-234 dts")
        )
        with pytest.raises(HTTPException) as exc:
            await service.change_mass_exam_status(db, tenant.id, me["id"], "done")
        assert exc.value.status_code == 400
        assert "Cannot transition" in exc.value.detail

    async def test_draft_to_in_progress_rejected(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-234 dti")
        )
        with pytest.raises(HTTPException) as exc:
            await service.change_mass_exam_status(
                db, tenant.id, me["id"], "in_progress"
            )
        assert exc.value.status_code == 400

    async def test_terminal_status_blocks_further_changes(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-234 term")
        )
        await service.change_mass_exam_status(db, tenant.id, me["id"], "cancelled")
        with pytest.raises(HTTPException) as exc:
            await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        assert exc.value.status_code == 400


class TestSendPrerequisites:
    async def test_no_questions_blocks_send(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-234 nq")
        )
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        with pytest.raises(HTTPException) as exc:
            await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        assert exc.value.status_code == 400
        assert "question" in exc.value.detail.lower()

    async def test_no_employees_blocks_send(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-234 ne")
        )
        await service.add_question(db, tenant.id, me["id"], _question())
        with pytest.raises(HTTPException) as exc:
            await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        assert exc.value.status_code == 400
        assert "employee" in exc.value.detail.lower()


class TestHappyFlow:
    async def test_full_lifecycle(
        self, db: AsyncSession, tenant, user, employee
    ):
        me, q, exam = await _seed_draft_with_prereqs(db, tenant, user, employee)

        sent = await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        assert sent["status"] == "sent"

        correct_id = next(o["id"] for o in q["options"] if o["is_correct"])
        await service.submit_answer(
            db,
            tenant.id,
            exam["id"],
            ExamAnswerSubmit(question_id=q["id"], selected_option_ids=[correct_id]),
        )

        progressed = await service.get_mass_exam_detail(db, tenant.id, me["id"])
        assert progressed["status"] == "in_progress"

        done = await service.change_mass_exam_status(db, tenant.id, me["id"], "done")
        assert done["status"] == "done"
        assert done["finished_at"] is not None

    async def test_cancel_from_sent(
        self, db: AsyncSession, tenant, user, employee
    ):
        me, _, _ = await _seed_draft_with_prereqs(db, tenant, user, employee)
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        cancelled = await service.change_mass_exam_status(
            db, tenant.id, me["id"], "cancelled"
        )
        assert cancelled["status"] == "cancelled"


# ---------------------------------------------------------------------------
# HRP-236 REDO (tasks 4-6): closing the procedure cascades to surveys.
# ---------------------------------------------------------------------------


async def _add_participant(db, tenant, position, mass_exam_id):
    """A second employee assigned to the same mass exam."""
    from datetime import date, datetime, timezone

    from app.core.security import hash_password
    from app.modules.auth.models import User
    from app.modules.employee.models import Employee

    u = User(
        email=f"emp-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("pass12345"),
        first_name="Second",
        last_name="Participant",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    emp = Employee(
        user_id=u.id,
        tenant_id=tenant.id,
        position_id=position.id,
        position_title=position.title,
        hire_date=date(2024, 1, 15),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    exams = await service.assign_employees(db, tenant.id, mass_exam_id, [emp.id])
    return emp, exams[0]


async def _reload_exam(db, exam_id):
    from app.modules.exam.models import Exam
    from sqlalchemy import select

    return (
        await db.execute(
            select(Exam)
            .where(Exam.id == exam_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


class TestTerminalCascade:
    async def test_cancel_voids_unfinished_survey(
        self, db: AsyncSession, tenant, user, employee
    ):
        me, q, exam = await _seed_draft_with_prereqs(db, tenant, user, employee)
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        await service.change_mass_exam_status(db, tenant.id, me["id"], "cancelled")

        row = await _reload_exam(db, exam["id"])
        assert row.status == "cancelled"

        with pytest.raises(HTTPException) as exc:
            await service.get_exam_questions(
                db, tenant.id, exam["id"], acting_employee_id=employee.id
            )
        assert exc.value.status_code == 409

        correct_id = next(o["id"] for o in q["options"] if o["is_correct"])
        with pytest.raises(HTTPException) as exc:
            await service.submit_answer(
                db,
                tenant.id,
                exam["id"],
                ExamAnswerSubmit(
                    question_id=q["id"], selected_option_ids=[correct_id]
                ),
            )
        assert exc.value.status_code == 409

        with pytest.raises(HTTPException) as exc:
            await service.finish_exam(
                db, tenant.id, exam["id"], acting_employee_id=employee.id
            )
        assert exc.value.status_code == 409

    async def test_cancel_voids_all_but_keeps_submitted_results(
        self, db: AsyncSession, tenant, user, employee, position
    ):
        me, q, exam1 = await _seed_draft_with_prereqs(db, tenant, user, employee)
        emp2, exam2 = await _add_participant(db, tenant, position, me["id"])
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")

        correct_id = next(o["id"] for o in q["options"] if o["is_correct"])
        await service.submit_answer(
            db,
            tenant.id,
            exam1["id"],
            ExamAnswerSubmit(question_id=q["id"], selected_option_ids=[correct_id]),
        )
        await service.finish_exam(
            db, tenant.id, exam1["id"], acting_employee_id=employee.id
        )
        assert (await _reload_exam(db, exam1["id"])).status == "done"

        await service.change_mass_exam_status(db, tenant.id, me["id"], "cancelled")

        row1 = await _reload_exam(db, exam1["id"])
        row2 = await _reload_exam(db, exam2["id"])
        assert row1.status == "cancelled"
        assert row2.status == "cancelled"
        # Submitted results survive the cancel...
        assert row1.score is not None
        assert row1.finished_at is not None
        review = await service.get_exam_review(
            db, tenant.id, exam1["id"], acting_employee_id=employee.id
        )
        assert review["score"] == row1.score
        # ...but a survey that was never submitted has none to show.
        with pytest.raises(HTTPException) as exc:
            await service.get_exam_review(
                db, tenant.id, exam2["id"], acting_employee_id=emp2.id
            )
        assert exc.value.status_code == 409

    async def test_complete_keeps_done_and_voids_unfinished(
        self, db: AsyncSession, tenant, user, employee, position
    ):
        me, q, exam1 = await _seed_draft_with_prereqs(db, tenant, user, employee)
        _, exam2 = await _add_participant(db, tenant, position, me["id"])
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")

        correct_id = next(o["id"] for o in q["options"] if o["is_correct"])
        await service.submit_answer(
            db,
            tenant.id,
            exam1["id"],
            ExamAnswerSubmit(question_id=q["id"], selected_option_ids=[correct_id]),
        )
        await service.finish_exam(
            db, tenant.id, exam1["id"], acting_employee_id=employee.id
        )

        await service.change_mass_exam_status(db, tenant.id, me["id"], "done")

        row1 = await _reload_exam(db, exam1["id"])
        row2 = await _reload_exam(db, exam2["id"])
        assert row1.status == "done"
        assert row2.status == "cancelled"
