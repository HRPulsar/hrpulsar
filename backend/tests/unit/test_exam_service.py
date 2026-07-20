import uuid

import pytest
from app.modules.exam import service
from app.modules.exam.schemas import (
    ExamAnswerSubmit,
    MassExamCreate,
    OptionCreate,
    PassMarkCreate,
    QuestionCreate,
    QuestionUpdate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# ---------- Helpers ----------


def _mass_exam_data(suffix: str | None = None) -> MassExamCreate:
    s = suffix or uuid.uuid4().hex[:6]
    return MassExamCreate(title=f"Exam {s}", description=f"Description {s}")


def _question_data(
    *,
    question_type: str = "single_choice",
    weight: int = 10,
    options: list[OptionCreate] | None = None,
) -> QuestionCreate:
    if options is None:
        options = [
            OptionCreate(title="Correct", sort_index=0, is_correct=True),
            OptionCreate(title="Wrong", sort_index=1, is_correct=False),
        ]
    return QuestionCreate(
        title=f"Q-{uuid.uuid4().hex[:6]}",
        question_type=question_type,
        sort_index=0,
        weight=weight,
        options=options,
    )


# ---------- MassExam CRUD ----------


class TestCreateMassExam:
    async def test_creates_mass_exam(self, db: AsyncSession, tenant, user):
        data = _mass_exam_data()
        result = await service.create_mass_exam(db, tenant.id, user.id, data)

        assert result["title"] == data.title
        assert result["description"] == data.description
        assert result["initiator_id"] == user.id
        assert result["tenant_id"] == tenant.id
        assert result["status"] == "draft"
        assert result["id"] is not None

    async def test_default_status_is_draft(self, db: AsyncSession, tenant, user):
        result = await service.create_mass_exam(
            db, tenant.id, user.id, _mass_exam_data()
        )
        assert result["status"] == "draft"
        assert result["started_at"] is None
        assert result["finished_at"] is None


class TestListMassExams:
    async def test_list_returns_created_exams(self, db: AsyncSession, tenant, user):
        await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data("a"))
        await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data("b"))

        exams = await service.list_mass_exams(db, tenant.id)
        assert len(exams) >= 2
        titles = [e["title"] for e in exams]
        assert "Exam a" in titles
        assert "Exam b" in titles

    async def test_list_filters_by_tenant(self, db: AsyncSession, tenant, user):
        await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        other_tenant_id = uuid.uuid4()
        exams = await service.list_mass_exams(db, other_tenant_id)
        assert len(exams) == 0


class TestGetMassExamDetail:
    async def test_returns_detail_with_questions_and_pass_marks(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        detail = await service.get_mass_exam_detail(db, tenant.id, me["id"])

        assert detail["id"] == me["id"]
        assert detail["title"] == me["title"]
        assert "questions" in detail
        assert "pass_marks" in detail
        assert detail["questions"] == []
        assert detail["pass_marks"] == []

    async def test_not_found_raises_404(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.get_mass_exam_detail(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_wrong_tenant_raises_404(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        with pytest.raises(HTTPException) as exc:
            await service.get_mass_exam_detail(db, uuid.uuid4(), me["id"])
        assert exc.value.status_code == 404


class TestChangeMassExamStatus:
    async def test_cancel_from_draft(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        updated = await service.change_mass_exam_status(
            db, tenant.id, me["id"], "cancelled"
        )
        assert updated["status"] == "cancelled"
        assert updated["finished_at"] is not None

    async def test_send_requires_question_and_employee(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        with pytest.raises(HTTPException) as exc:
            await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        assert exc.value.status_code == 400

    async def test_send_with_prereqs(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question_data(weight=5))
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        updated = await service.change_mass_exam_status(
            db, tenant.id, me["id"], "sent"
        )
        assert updated["status"] == "sent"

    async def test_submit_answer_auto_transitions_mass_exam(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(
            db, tenant.id, me["id"], _question_data(weight=5)
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

        updated = await service.get_mass_exam_detail(db, tenant.id, me["id"])
        assert updated["status"] == "in_progress"
        assert updated["started_at"] is not None

    async def test_complete_from_in_progress(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(
            db, tenant.id, me["id"], _question_data(weight=5)
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

        updated = await service.change_mass_exam_status(db, tenant.id, me["id"], "done")
        assert updated["status"] == "done"
        assert updated["finished_at"] is not None

    async def test_forbidden_transition(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        with pytest.raises(HTTPException) as exc:
            await service.change_mass_exam_status(db, tenant.id, me["id"], "done")
        assert exc.value.status_code == 400

    async def test_not_found_raises_404(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.change_mass_exam_status(
                db, tenant.id, uuid.uuid4(), "cancelled"
            )
        assert exc.value.status_code == 404

    async def test_wrong_tenant_raises_404(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        with pytest.raises(HTTPException) as exc:
            await service.change_mass_exam_status(
                db, uuid.uuid4(), me["id"], "cancelled"
            )
        assert exc.value.status_code == 404


# ---------- Questions ----------


class TestAddQuestion:
    async def test_add_question_with_options(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q_data = _question_data(weight=5)

        result = await service.add_question(db, tenant.id, me["id"], q_data)

        assert result["title"] == q_data.title
        assert result["question_type"] == "single_choice"
        assert result["weight"] == 5
        assert result["is_active"] is True
        assert len(result["options"]) == 2
        correct = [o for o in result["options"] if o["is_correct"]]
        assert len(correct) == 1
        assert correct[0]["title"] == "Correct"

    async def test_add_question_no_options(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q_data = _question_data(question_type="essay", options=[])

        result = await service.add_question(db, tenant.id, me["id"], q_data)
        assert result["question_type"] == "essay"
        assert result["options"] == []

    async def test_add_question_mass_exam_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.add_question(db, tenant.id, uuid.uuid4(), _question_data())
        assert exc.value.status_code == 404

    async def test_add_question_wrong_tenant(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        with pytest.raises(HTTPException) as exc:
            await service.add_question(db, uuid.uuid4(), me["id"], _question_data())
        assert exc.value.status_code == 404

    async def test_question_appears_in_detail(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question_data())

        detail = await service.get_mass_exam_detail(db, tenant.id, me["id"])
        assert len(detail["questions"]) == 1
        assert len(detail["questions"][0]["options"]) == 2


# ---------- Update / Delete Question (HRP-228) ----------


class TestUpdateQuestion:
    async def test_updates_title_and_description(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(db, tenant.id, me["id"], _question_data())

        updated = await service.update_question(
            db,
            tenant.id,
            me["id"],
            q["id"],
            QuestionUpdate(title="New title", description="New description"),
        )
        assert updated["title"] == "New title"
        assert updated["description"] == "New description"

    async def test_replaces_options_when_supplied(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(db, tenant.id, me["id"], _question_data())
        new_options = [
            OptionCreate(title="A", sort_index=0, is_correct=False),
            OptionCreate(title="B", sort_index=1, is_correct=True),
            OptionCreate(title="C", sort_index=2, is_correct=False),
        ]

        updated = await service.update_question(
            db,
            tenant.id,
            me["id"],
            q["id"],
            QuestionUpdate(options=new_options),
        )

        assert [o["title"] for o in updated["options"]] == ["A", "B", "C"]
        correct = [o for o in updated["options"] if o["is_correct"]]
        assert len(correct) == 1
        assert correct[0]["title"] == "B"

    async def test_leaves_options_untouched_when_not_supplied(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(db, tenant.id, me["id"], _question_data())

        updated = await service.update_question(
            db,
            tenant.id,
            me["id"],
            q["id"],
            QuestionUpdate(title="Renamed"),
        )
        assert len(updated["options"]) == 2

    async def test_rejects_after_send(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(db, tenant.id, me["id"], _question_data(weight=5))
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")

        with pytest.raises(HTTPException) as exc:
            await service.update_question(
                db, tenant.id, me["id"], q["id"], QuestionUpdate(title="Late edit")
            )
        assert exc.value.status_code == 400

    async def test_rejects_single_choice_with_multiple_correct(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(db, tenant.id, me["id"], _question_data())

        bad_options = [
            OptionCreate(title="A", sort_index=0, is_correct=True),
            OptionCreate(title="B", sort_index=1, is_correct=True),
        ]
        with pytest.raises(HTTPException) as exc:
            await service.update_question(
                db, tenant.id, me["id"], q["id"], QuestionUpdate(options=bad_options)
            )
        assert exc.value.status_code == 400

    async def test_question_not_found_raises_404(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        with pytest.raises(HTTPException) as exc:
            await service.update_question(
                db,
                tenant.id,
                me["id"],
                uuid.uuid4(),
                QuestionUpdate(title="x"),
            )
        assert exc.value.status_code == 404


class TestDeleteQuestion:
    async def test_removes_question(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(db, tenant.id, me["id"], _question_data())

        await service.delete_question(db, tenant.id, me["id"], q["id"])
        detail = await service.get_mass_exam_detail(db, tenant.id, me["id"])
        assert detail["questions"] == []

    async def test_rejects_after_send(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(db, tenant.id, me["id"], _question_data(weight=5))
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")

        with pytest.raises(HTTPException) as exc:
            await service.delete_question(db, tenant.id, me["id"], q["id"])
        assert exc.value.status_code == 400

    async def test_not_found_raises_404(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        with pytest.raises(HTTPException) as exc:
            await service.delete_question(db, tenant.id, me["id"], uuid.uuid4())
        assert exc.value.status_code == 404


# ---------- PassMark ----------


class TestAddPassMark:
    async def test_add_pass_mark(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        pm_data = PassMarkCreate(min_score_percent=70, min_score_points=7)

        result = await service.add_pass_mark(db, tenant.id, me["id"], pm_data)

        assert result["min_score_percent"] == 70
        assert result["min_score_points"] == 7
        assert result["grade_id"] is None
        assert result["specialization_id"] is None
        assert result["id"] is not None

    async def test_add_pass_mark_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.add_pass_mark(
                db, tenant.id, uuid.uuid4(), PassMarkCreate(min_score_percent=50)
            )
        assert exc.value.status_code == 404

    async def test_add_pass_mark_wrong_tenant(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        with pytest.raises(HTTPException) as exc:
            await service.add_pass_mark(
                db, uuid.uuid4(), me["id"], PassMarkCreate(min_score_percent=50)
            )
        assert exc.value.status_code == 404

    async def test_pass_mark_appears_in_detail(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_pass_mark(
            db, tenant.id, me["id"], PassMarkCreate(min_score_percent=80)
        )

        detail = await service.get_mass_exam_detail(db, tenant.id, me["id"])
        assert len(detail["pass_marks"]) == 1
        assert detail["pass_marks"][0]["min_score_percent"] == 80

# ---------- Assign Employees ----------


class TestAssignEmployees:
    async def test_assign_single_employee(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question_data(weight=10))

        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])

        assert len(exams) == 1
        assert exams[0]["employee_id"] == employee.id
        assert exams[0]["mass_exam_id"] == me["id"]
        assert exams[0]["status"] == "assigned"
        assert exams[0]["max_score"] == 10
        assert exams[0]["score"] is None

    async def test_assign_calculates_max_score_from_active_questions(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question_data(weight=10))
        await service.add_question(db, tenant.id, me["id"], _question_data(weight=5))

        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        assert exams[0]["max_score"] == 15

    async def test_assign_no_questions_gives_zero_max_score(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        assert exams[0]["max_score"] == 0

    async def test_assign_mass_exam_not_found(self, db: AsyncSession, tenant, employee):
        with pytest.raises(HTTPException) as exc:
            await service.assign_employees(db, tenant.id, uuid.uuid4(), [employee.id])
        assert exc.value.status_code == 404

    async def test_assign_wrong_tenant(self, db: AsyncSession, tenant, user, employee):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        with pytest.raises(HTTPException) as exc:
            await service.assign_employees(db, uuid.uuid4(), me["id"], [employee.id])
        assert exc.value.status_code == 404


# ---------- Mass Exam Results ----------


class TestListMassExamResults:
    async def test_returns_assigned_exams(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question_data(weight=10))
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])

        results = await service.list_mass_exam_results(db, tenant.id, me["id"])
        assert len(results) == 1
        assert results[0]["employee_id"] == employee.id
        assert results[0]["status"] == "assigned"
        assert results[0]["passed"] is None  # not yet scored

    async def test_empty_when_no_assignments(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        results = await service.list_mass_exam_results(db, tenant.id, me["id"])
        assert results == []

    async def test_not_found_raises_404(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.list_mass_exam_results(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404


# ---------- My Exams ----------


class TestListMyExams:
    async def test_returns_exams_for_employee(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question_data(weight=5))
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")

        my_exams = await service.list_my_exams(db, tenant.id, employee.id)
        assert len(my_exams) >= 1
        assert my_exams[0]["employee_id"] == employee.id
        assert my_exams[0]["mass_exam_title"] == me["title"]

    async def test_drafts_hidden_from_assignee(
        self, db: AsyncSession, tenant, user, employee
    ):
        """HRP-225: end users only see exams once the manager hits send."""
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question_data(weight=5))
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])

        my_exams = await service.list_my_exams(db, tenant.id, employee.id)
        assert my_exams == []

    async def test_drafts_hidden_from_visible_scope_too(
        self, db: AsyncSession, tenant, user, employee
    ):
        """HRP-225: the in-prod UI calls /exams without employee_id, which
        routes the request to the `visible_employee_ids` branch. Drafts
        must be hidden there as well — earlier code only filtered drafts
        when employee_id was passed."""
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question_data(weight=5))
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])

        my_exams = await service.list_my_exams(
            db, tenant.id, employee_id=None, visible_employee_ids={employee.id}
        )
        assert my_exams == []

    async def test_empty_for_unassigned_employee(
        self, db: AsyncSession, tenant, employee
    ):
        my_exams = await service.list_my_exams(db, tenant.id, employee.id)
        assert my_exams == []


# ---------- Submit Answer ----------


class TestSubmitAnswer:
    async def _setup_exam_with_question(self, db, tenant, user, employee):
        """Create mass exam, add a question, assign employee, send, return (exam, question)."""
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(
            db, tenant.id, me["id"], _question_data(weight=10)
        )
        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        # HRP-328: answers are only accepted once the exam is sent.
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        return exams[0], q

    async def test_correct_single_choice_answer(
        self, db: AsyncSession, tenant, user, employee
    ):
        exam, q = await self._setup_exam_with_question(db, tenant, user, employee)
        correct_option_id = next(o["id"] for o in q["options"] if o["is_correct"])

        data = ExamAnswerSubmit(
            question_id=q["id"],
            selected_option_ids=[correct_option_id],
        )
        result = await service.submit_answer(db, tenant.id, exam["id"], data)

        assert result["is_correct"] is True
        assert result["score"] == 10

    async def test_incorrect_single_choice_answer(
        self, db: AsyncSession, tenant, user, employee
    ):
        exam, q = await self._setup_exam_with_question(db, tenant, user, employee)
        wrong_option_id = next(o["id"] for o in q["options"] if not o["is_correct"])

        data = ExamAnswerSubmit(
            question_id=q["id"],
            selected_option_ids=[wrong_option_id],
        )
        result = await service.submit_answer(db, tenant.id, exam["id"], data)

        assert result["is_correct"] is False
        assert result["score"] == 0

    async def test_submit_transitions_status_to_in_progress(
        self, db: AsyncSession, tenant, user, employee
    ):
        exam, q = await self._setup_exam_with_question(db, tenant, user, employee)
        correct_option_id = next(o["id"] for o in q["options"] if o["is_correct"])

        data = ExamAnswerSubmit(
            question_id=q["id"], selected_option_ids=[correct_option_id]
        )
        await service.submit_answer(db, tenant.id, exam["id"], data)

        # Verify status changed
        my_exams = await service.list_my_exams(db, tenant.id, employee.id)
        this_exam = next(e for e in my_exams if e["id"] == exam["id"])
        assert this_exam["status"] == "in_progress"
        assert this_exam["started_at"] is not None

    async def test_essay_answer_no_auto_score(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(
            db,
            tenant.id,
            me["id"],
            _question_data(question_type="essay", weight=10, options=[]),
        )
        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")

        data = ExamAnswerSubmit(question_id=q["id"], text_answer="My essay answer")
        result = await service.submit_answer(db, tenant.id, exams[0]["id"], data)

        assert result["is_correct"] is None
        assert result["score"] == 0

    async def test_submit_exam_not_found(self, db: AsyncSession, tenant):
        data = ExamAnswerSubmit(question_id=uuid.uuid4(), selected_option_ids=[])
        with pytest.raises(HTTPException) as exc:
            await service.submit_answer(db, tenant.id, uuid.uuid4(), data)
        assert exc.value.status_code == 404

    async def test_submit_question_not_found(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question_data(weight=10))
        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")

        data = ExamAnswerSubmit(question_id=uuid.uuid4(), selected_option_ids=[])
        with pytest.raises(HTTPException) as exc:
            await service.submit_answer(db, tenant.id, exams[0]["id"], data)
        assert exc.value.status_code == 404


# ---------- Finish Exam ----------


class TestFinishExam:
    async def test_finish_calculates_total_score(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q1 = await service.add_question(
            db, tenant.id, me["id"], _question_data(weight=10)
        )
        q2 = await service.add_question(
            db, tenant.id, me["id"], _question_data(weight=5)
        )
        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        exam = exams[0]

        # Answer q1 correctly
        correct_id_1 = next(o["id"] for o in q1["options"] if o["is_correct"])
        await service.submit_answer(
            db,
            tenant.id,
            exam["id"],
            ExamAnswerSubmit(question_id=q1["id"], selected_option_ids=[correct_id_1]),
        )

        # Answer q2 incorrectly
        wrong_id_2 = next(o["id"] for o in q2["options"] if not o["is_correct"])
        await service.submit_answer(
            db,
            tenant.id,
            exam["id"],
            ExamAnswerSubmit(question_id=q2["id"], selected_option_ids=[wrong_id_2]),
        )

        result = await service.finish_exam(db, tenant.id, exam["id"])

        assert result["score"] == 10  # only q1 correct
        assert result["max_score"] == 15
        assert result["passed"] is True  # 10/15 = 66.7% >= 60%

    async def test_finish_all_wrong_fails(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(
            db, tenant.id, me["id"], _question_data(weight=10)
        )
        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")

        wrong_id = next(o["id"] for o in q["options"] if not o["is_correct"])
        await service.submit_answer(
            db,
            tenant.id,
            exams[0]["id"],
            ExamAnswerSubmit(question_id=q["id"], selected_option_ids=[wrong_id]),
        )

        result = await service.finish_exam(db, tenant.id, exams[0]["id"])
        assert result["score"] == 0
        assert result["passed"] is False

    async def test_finish_sets_status_done(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(db, tenant.id, me["id"], _question_data(weight=10))
        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        wrong_id = next(o["id"] for o in q["options"] if not o["is_correct"])
        await service.submit_answer(
            db,
            tenant.id,
            exams[0]["id"],
            ExamAnswerSubmit(question_id=q["id"], selected_option_ids=[wrong_id]),
        )

        result = await service.finish_exam(db, tenant.id, exams[0]["id"])
        assert result["exam_id"] == exams[0]["id"]

        # Verify via list
        my_exams = await service.list_my_exams(db, tenant.id, employee.id)
        this_exam = next(e for e in my_exams if e["id"] == exams[0]["id"])
        assert this_exam["status"] == "done"
        assert this_exam["finished_at"] is not None

    async def test_finish_requires_all_questions_answered(
        self, db: AsyncSession, tenant, user, employee
    ):
        """HRP-328: results cannot be submitted with unanswered questions."""
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question_data(weight=10))
        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")

        with pytest.raises(HTTPException) as exc:
            await service.finish_exam(db, tenant.id, exams[0]["id"])
        assert exc.value.status_code == 400

    async def test_finish_exam_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.finish_exam(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_finish_wrong_tenant(self, db: AsyncSession, tenant, user, employee):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        await service.add_question(db, tenant.id, me["id"], _question_data(weight=10))
        exams = await service.assign_employees(db, tenant.id, me["id"], [employee.id])

        with pytest.raises(HTTPException) as exc:
            await service.finish_exam(db, uuid.uuid4(), exams[0]["id"])
        assert exc.value.status_code == 404

    async def test_finish_result_appears_in_mass_exam_results(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(db, tenant.id, user.id, _mass_exam_data())
        q = await service.add_question(
            db, tenant.id, me["id"], _question_data(weight=10)
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
        await service.finish_exam(db, tenant.id, exams[0]["id"])

        results = await service.list_mass_exam_results(db, tenant.id, me["id"])
        assert len(results) == 1
        assert results[0]["status"] == "done"
        assert results[0]["score"] == 10
        assert results[0]["passed"] is True  # 10/10 = 100% >= 60%
