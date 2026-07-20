"""HRP-328: employee exam-taking flow.

Covers the take-sheet payload (no answer key), answer upsert & guards,
finish preconditions, the review payload (answer key revealed) and the
automatic mass-exam completion when the last participant finishes.
"""

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


def _mass_exam_data() -> MassExamCreate:
    s = uuid.uuid4().hex[:6]
    return MassExamCreate(title=f"Exam {s}")


def _question(weight: int = 10, question_type: str = "single_choice") -> QuestionCreate:
    options = (
        []
        if question_type == "essay"
        else [
            OptionCreate(title="Correct", sort_index=0, is_correct=True),
            OptionCreate(title="Wrong", sort_index=1, is_correct=False),
        ]
    )
    return QuestionCreate(
        title=f"Q-{uuid.uuid4().hex[:6]}",
        question_type=question_type,
        sort_index=0,
        weight=weight,
        options=options,
    )


async def _sent_exam(db, tenant, user, employee, *, questions=1):
    me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
    qs = []
    for _ in range(questions):
        qs.append(await service.add_question(db, tenant.id, me["id"], _question()))
    exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
    await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
    return me, exams[0], qs


async def _make_second_employee(db: AsyncSession, tenant):
    from datetime import date, datetime, timezone

    from app.core.security import hash_password
    from app.modules.auth.models import User
    from app.modules.employee.models import Employee

    u = User(
        email=f"second-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Second",
        last_name="Emp",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.flush()
    emp = Employee(
        user_id=u.id,
        tenant_id=tenant.id,
        hire_date=date(2024, 1, 15),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


class TestTakePayload:
    async def test_questions_hide_answer_key(
        self, db: AsyncSession, tenant, user, employee
    ):
        _, exam, _ = await _sent_exam(db, tenant, user, employee)
        payload = await service.get_exam_questions(
            db, tenant.id, exam["id"], acting_employee_id=employee.id
        )
        assert payload["questions"], "questions must be listed"
        for q in payload["questions"]:
            for o in q["options"]:
                assert "is_correct" not in o

    async def test_saved_answers_returned_for_resume(
        self, db: AsyncSession, tenant, user, employee
    ):
        _, exam, qs = await _sent_exam(db, tenant, user, employee)
        q = qs[0]
        correct_id = next(o["id"] for o in q["options"] if o["is_correct"])
        await service.submit_answer(
            db,
            tenant.id,
            exam["id"],
            ExamAnswerSubmit(question_id=q["id"], selected_option_ids=[correct_id]),
            acting_employee_id=employee.id,
        )
        payload = await service.get_exam_questions(
            db, tenant.id, exam["id"], acting_employee_id=employee.id
        )
        assert payload["status"] == "in_progress"
        assert payload["answers"] == [
            {
                "question_id": q["id"],
                "selected_option_ids": [str(correct_id)],
                "text_answer": None,
            }
        ]

    async def test_foreign_employee_forbidden(
        self, db: AsyncSession, tenant, user, employee
    ):
        _, exam, _ = await _sent_exam(db, tenant, user, employee)
        stranger = await _make_second_employee(db, tenant)
        with pytest.raises(HTTPException) as exc:
            await service.get_exam_questions(
                db, tenant.id, exam["id"], acting_employee_id=stranger.id
            )
        assert exc.value.status_code == 403

    async def test_draft_exam_hidden(self, db: AsyncSession, tenant, user, employee):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question())
        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        with pytest.raises(HTTPException) as exc:
            await service.get_exam_questions(
                db, tenant.id, exams[0]["id"], acting_employee_id=employee.id
            )
        assert exc.value.status_code == 404


class TestAnswerUpsert:
    async def test_reanswer_replaces_previous_row(
        self, db: AsyncSession, tenant, user, employee
    ):
        _, exam, qs = await _sent_exam(db, tenant, user, employee)
        q = qs[0]
        correct_id = next(o["id"] for o in q["options"] if o["is_correct"])
        wrong_id = next(o["id"] for o in q["options"] if not o["is_correct"])

        await service.submit_answer(
            db,
            tenant.id,
            exam["id"],
            ExamAnswerSubmit(question_id=q["id"], selected_option_ids=[wrong_id]),
            acting_employee_id=employee.id,
        )
        await service.submit_answer(
            db,
            tenant.id,
            exam["id"],
            ExamAnswerSubmit(question_id=q["id"], selected_option_ids=[correct_id]),
            acting_employee_id=employee.id,
        )

        result = await service.finish_exam(
            db, tenant.id, exam["id"], acting_employee_id=employee.id
        )
        # A duplicate row would have summed 0 + 10; the upsert keeps one row.
        assert result["score"] == 10

    async def test_foreign_question_rejected(
        self, db: AsyncSession, tenant, user, employee
    ):
        _, exam, _ = await _sent_exam(db, tenant, user, employee)
        other_me = await service.create_mass_exam(
            db, tenant.id, user.id, _mass_exam_data()
        )
        foreign_q = await service.add_question(
            db, tenant.id, other_me["id"], _question()
        )
        with pytest.raises(HTTPException) as exc:
            await service.submit_answer(
                db,
                tenant.id,
                exam["id"],
                ExamAnswerSubmit(
                    question_id=foreign_q["id"],
                    selected_option_ids=[foreign_q["options"][0]["id"]],
                ),
                acting_employee_id=employee.id,
            )
        assert exc.value.status_code == 404

    async def test_answer_rejected_after_done(
        self, db: AsyncSession, tenant, user, employee
    ):
        _, exam, qs = await _sent_exam(db, tenant, user, employee)
        q = qs[0]
        correct_id = next(o["id"] for o in q["options"] if o["is_correct"])
        submit = ExamAnswerSubmit(
            question_id=q["id"], selected_option_ids=[correct_id]
        )
        await service.submit_answer(
            db, tenant.id, exam["id"], submit, acting_employee_id=employee.id
        )
        await service.finish_exam(
            db, tenant.id, exam["id"], acting_employee_id=employee.id
        )
        with pytest.raises(HTTPException) as exc:
            await service.submit_answer(
                db, tenant.id, exam["id"], submit, acting_employee_id=employee.id
            )
        assert exc.value.status_code == 409

    async def test_foreign_employee_cannot_answer(
        self, db: AsyncSession, tenant, user, employee
    ):
        _, exam, qs = await _sent_exam(db, tenant, user, employee)
        stranger = await _make_second_employee(db, tenant)
        q = qs[0]
        with pytest.raises(HTTPException) as exc:
            await service.submit_answer(
                db,
                tenant.id,
                exam["id"],
                ExamAnswerSubmit(
                    question_id=q["id"],
                    selected_option_ids=[q["options"][0]["id"]],
                ),
                acting_employee_id=stranger.id,
            )
        assert exc.value.status_code == 403


class TestReview:
    async def test_review_reveals_answer_key(
        self, db: AsyncSession, tenant, user, employee
    ):
        _, exam, qs = await _sent_exam(db, tenant, user, employee)
        q = qs[0]
        wrong_id = next(o["id"] for o in q["options"] if not o["is_correct"])
        await service.submit_answer(
            db,
            tenant.id,
            exam["id"],
            ExamAnswerSubmit(question_id=q["id"], selected_option_ids=[wrong_id]),
            acting_employee_id=employee.id,
        )
        await service.finish_exam(
            db, tenant.id, exam["id"], acting_employee_id=employee.id
        )

        review = await service.get_exam_review(
            db, tenant.id, exam["id"], acting_employee_id=employee.id
        )
        rq = review["questions"][0]
        assert any(o["is_correct"] for o in rq["options"])
        assert rq["answer"]["is_correct"] is False
        assert rq["answer"]["selected_option_ids"] == [str(wrong_id)]
        assert review["score"] == 0

    async def test_review_blocked_until_done(
        self, db: AsyncSession, tenant, user, employee
    ):
        _, exam, _ = await _sent_exam(db, tenant, user, employee)
        with pytest.raises(HTTPException) as exc:
            await service.get_exam_review(
                db, tenant.id, exam["id"], acting_employee_id=employee.id
            )
        assert exc.value.status_code == 409

    async def test_review_denied_outside_scope(
        self, db: AsyncSession, tenant, user, employee
    ):
        _, exam, qs = await _sent_exam(db, tenant, user, employee)
        q = qs[0]
        await service.submit_answer(
            db,
            tenant.id,
            exam["id"],
            ExamAnswerSubmit(
                question_id=q["id"], selected_option_ids=[q["options"][0]["id"]]
            ),
            acting_employee_id=employee.id,
        )
        await service.finish_exam(
            db, tenant.id, exam["id"], acting_employee_id=employee.id
        )
        stranger = await _make_second_employee(db, tenant)
        with pytest.raises(HTTPException) as exc:
            await service.get_exam_review(
                db,
                tenant.id,
                exam["id"],
                acting_employee_id=stranger.id,
                visible_employee_ids={stranger.id},
            )
        assert exc.value.status_code == 403


class TestGuards:
    async def test_answer_rejected_after_manager_closed_mass_exam(
        self, db: AsyncSession, tenant, user, employee
    ):
        """A manually completed exam accepts no further answers."""
        me, exam, qs = await _sent_exam(db, tenant, user, employee)
        q = qs[0]
        correct_id = next(o["id"] for o in q["options"] if o["is_correct"])
        submit = ExamAnswerSubmit(
            question_id=q["id"], selected_option_ids=[correct_id]
        )
        # First answer flips the mass exam to in_progress; the manager
        # then closes it manually.
        await service.submit_answer(
            db, tenant.id, exam["id"], submit, acting_employee_id=employee.id
        )
        await service.change_mass_exam_status(db, tenant.id, me["id"], "done")
        with pytest.raises(HTTPException) as exc:
            await service.submit_answer(
                db, tenant.id, exam["id"], submit, acting_employee_id=employee.id
            )
        assert exc.value.status_code == 409

    async def test_max_score_recomputed_on_send(
        self, db: AsyncSession, tenant, user, employee
    ):
        """Questions added after assignment count toward max_score once sent."""
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question(weight=10))
        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        assert exams[0]["max_score"] == 10
        # A second question lands while still in draft.
        await service.add_question(db, tenant.id, me["id"], _question(weight=5))
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")

        payload = await service.get_exam_questions(
            db, tenant.id, exams[0]["id"], acting_employee_id=employee.id
        )
        assert payload["max_score"] == 15


class TestAutoCompletion:
    async def test_mass_exam_done_when_all_participants_finish(
        self, db: AsyncSession, tenant, user, employee
    ):
        second = await _make_second_employee(db, tenant)
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(db, tenant.id, me["id"], _question())
        exams = await service.assign_employees(
            db, tenant.id, me["id"], [employee.id, second.id]
        )
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        correct_id = next(o["id"] for o in q["options"] if o["is_correct"])

        by_emp = {e["employee_id"]: e for e in exams}
        for emp_id in (employee.id, second.id):
            exam = by_emp[emp_id]
            await service.submit_answer(
                db,
                tenant.id,
                exam["id"],
                ExamAnswerSubmit(
                    question_id=q["id"], selected_option_ids=[correct_id]
                ),
                acting_employee_id=emp_id,
            )

        await service.finish_exam(
            db, tenant.id, by_emp[employee.id]["id"], acting_employee_id=employee.id
        )
        detail = await service.get_mass_exam_detail(db, tenant.id, me["id"])
        assert detail["status"] == "in_progress"

        await service.finish_exam(
            db, tenant.id, by_emp[second.id]["id"], acting_employee_id=second.id
        )
        detail = await service.get_mass_exam_detail(db, tenant.id, me["id"])
        assert detail["status"] == "done"
        assert detail["finished_at"] is not None
