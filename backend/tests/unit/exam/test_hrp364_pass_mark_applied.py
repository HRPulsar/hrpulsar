"""HRP-364: the configured Pass Mark drives pass/fail.

Both finish_exam and list_mass_exam_results used a hardcoded 60% — the
Pass Mark was purely cosmetic. ``passed`` is derived at read time, so a
mark edited on an active exam (HRP-226) re-grades finished participants
transparently.
"""

from __future__ import annotations

from app.modules.exam import service
from app.modules.exam.models import ExamPassMark
from app.modules.exam.schemas import (
    ExamAnswerSubmit,
    MassExamCreate,
    OptionCreate,
    PassMarkCreate,
    PassMarkUpdate,
    QuestionCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession


class TestExamPassedHelper:
    def _pm(self, percent=None, points=None) -> ExamPassMark:
        return ExamPassMark(min_score_percent=percent, min_score_points=points)

    def test_default_60_without_mark(self):
        assert service._exam_passed(6, 10, None) is True
        assert service._exam_passed(5, 10, None) is False

    def test_percent_threshold(self):
        assert service._exam_passed(8, 10, self._pm(percent=80)) is True
        assert service._exam_passed(7, 10, self._pm(percent=80)) is False

    def test_points_threshold(self):
        assert service._exam_passed(4, 10, self._pm(points=4)) is True
        assert service._exam_passed(3, 10, self._pm(points=4)) is False

    def test_both_thresholds_must_hold(self):
        pm = self._pm(percent=50, points=7)
        assert service._exam_passed(7, 10, pm) is True
        # 60% >= 50% but 6 < 7 points.
        assert service._exam_passed(6, 10, pm) is False

    def test_unknowns(self):
        assert service._exam_passed(None, 10, None) is None
        assert service._exam_passed(5, 0, None) is None
        # Percent threshold undecidable without a max score.
        assert service._exam_passed(5, None, self._pm(percent=50)) is None
        # Points-only threshold works without a max score.
        assert service._exam_passed(5, None, self._pm(points=5)) is True


async def _second_employee(db: AsyncSession, tenant, position):
    import uuid as uuid_mod
    from datetime import date, datetime, timezone

    from app.core.security import hash_password
    from app.modules.auth.models import User as AuthUser
    from app.modules.employee.models import Employee

    u = AuthUser(
        email=f"hrp364-{uuid_mod.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass"),
        first_name="Second",
        last_name="Member",
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
    return emp


async def _finished_exam(db: AsyncSession, tenant, user, employee, *, weight=10):
    me = await service.create_mass_exam(
        db, tenant.id, user.id, MassExamCreate(title="HRP-364")
    )
    q = await service.add_question(
        db,
        tenant.id,
        me["id"],
        QuestionCreate(
            title="Q1",
            question_type="single_choice",
            weight=weight,
            options=[
                OptionCreate(title="Right", is_correct=True),
                OptionCreate(title="Wrong", is_correct=False),
            ],
        ),
    )
    exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
    await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
    correct_id = next(o["id"] for o in q["options"] if o["is_correct"])
    await service.submit_answer(
        db,
        tenant.id,
        exams[0]["id"],
        ExamAnswerSubmit(question_id=q["id"], selected_option_ids=[correct_id]),
    )
    return me, exams[0]


class TestPassMarkApplied:
    async def test_finish_uses_pass_mark(
        self, db: AsyncSession, tenant, user, employee
    ):
        me, exam = await _finished_exam(db, tenant, user, employee)
        # Full score (10/10) but the mark demands more points than exist —
        # the hardcoded 60% would have said passed.
        await service.add_pass_mark(
            db, tenant.id, me["id"], PassMarkCreate(min_score_points=11)
        )
        result = await service.finish_exam(
            db, tenant.id, exam["id"], acting_employee_id=employee.id
        )
        assert result["score"] == 10
        assert result["passed"] is False

    async def test_results_regrade_after_mark_edit(
        self, db: AsyncSession, tenant, user, employee, position
    ):
        me, exam = await _finished_exam(db, tenant, user, employee)
        # A second (unfinished) participant keeps the exam active so the
        # pass mark stays editable after the first submission (HRP-226).
        emp2 = await _second_employee(db, tenant, position)
        await service.assign_employees(db, tenant.id, me["id"], [emp2.id])

        pm = await service.add_pass_mark(
            db, tenant.id, me["id"], PassMarkCreate(min_score_percent=100)
        )
        await service.finish_exam(
            db, tenant.id, exam["id"], acting_employee_id=employee.id
        )

        rows = await service.list_mass_exam_results(db, tenant.id, me["id"])
        finished_row = next(r for r in rows if r["id"] == exam["id"])
        assert finished_row["passed"] is True  # 10/10 = 100%

        # Raising the bar on an active exam re-grades the finished row.
        await service.update_pass_mark(
            db,
            tenant.id,
            me["id"],
            pm["id"],
            PassMarkUpdate(min_score_percent=None, min_score_points=11),
        )
        rows = await service.list_mass_exam_results(db, tenant.id, me["id"])
        finished_row = next(r for r in rows if r["id"] == exam["id"])
        assert finished_row["passed"] is False

    async def test_default_without_mark(
        self, db: AsyncSession, tenant, user, employee
    ):
        me, exam = await _finished_exam(db, tenant, user, employee)
        result = await service.finish_exam(
            db, tenant.id, exam["id"], acting_employee_id=employee.id
        )
        assert result["passed"] is True  # 100% >= default 60%
        rows = await service.list_mass_exam_results(db, tenant.id, me["id"])
        assert rows[0]["passed"] is True
