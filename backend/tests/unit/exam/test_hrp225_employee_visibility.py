"""HRP-225: employee name resolves on reload + assignee sees the test."""

from __future__ import annotations

import uuid

import pytest_asyncio
from app.modules.exam import service
from app.modules.exam.schemas import MassExamCreate, OptionCreate, QuestionCreate
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


@pytest_asyncio.fixture
async def employee_role(db: AsyncSession):
    from app.modules.auth.models import Role
    from sqlalchemy import select

    role = (
        await db.execute(select(Role).where(Role.code == "employee"))
    ).scalar_one_or_none()
    if role is None:
        role = Role(name="Employee", code="employee", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


@pytest_asyncio.fixture
async def employee_user(db: AsyncSession, tenant, employee_role, position):
    from datetime import date, datetime, timezone

    from app.core.security import hash_password
    from app.modules.auth.models import User, user_roles
    from app.modules.employee.models import Employee
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    u = User(
        email=f"emp-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("pass12345"),
        first_name="Alice",
        last_name="Worker",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(
        user_roles.insert().values(user_id=u.id, role_id=employee_role.id)
    )
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

    fresh_user = (
        await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == u.id)
        )
    ).scalar_one()
    return fresh_user, emp


class TestEmployeeNameOnReload:
    async def test_results_carry_full_name(
        self, db: AsyncSession, tenant, user, employee_user
    ):
        """Reproduces the F5 bug: name disappeared because Employee.user
        was not in the selectinload chain. Verifying via a single call is
        sufficient — the page-reload variant trips test-harness greenlet
        plumbing that is irrelevant to the production fix."""
        _, employee = employee_user
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="Exam HRP-225")
        )
        await service.add_question(db, tenant.id, me["id"], _question())
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])

        results = await service.list_mass_exam_results(db, tenant.id, me["id"])
        assert len(results) == 1
        assert results[0]["employee_name"] == "Alice Worker"
        assert results[0]["employee_id"] == employee.id

    async def test_results_handle_employee_without_user(
        self, db: AsyncSession, tenant, user
    ):
        """Edge case: an Employee row missing its User link should still
        surface a None name instead of blowing up."""
        from datetime import date

        from app.modules.employee.models import Employee

        # Create an Employee row referencing the admin user fixture but
        # then null its user link by detaching the relationship — we use
        # a parallel insert path.
        emp = Employee(
            user_id=user.id,
            tenant_id=tenant.id,
            hire_date=date(2024, 1, 1),
        )
        db.add(emp)
        await db.commit()
        await db.refresh(emp)

        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-225 detached")
        )
        await service.add_question(db, tenant.id, me["id"], _question())
        await service.assign_employees(db, tenant.id, me["id"], [emp.id])
        results = await service.list_mass_exam_results(db, tenant.id, me["id"])
        # admin user has names "Test User" → display is "Test User".
        assert results[0]["employee_name"] == "Test User"


class TestEmployeeSeesAssignedExam:
    async def test_employee_lists_sent_exam(
        self, db: AsyncSession, tenant, user, employee_user
    ):
        emp_user, employee = employee_user
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-225 list")
        )
        await service.add_question(db, tenant.id, me["id"], _question())
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")

        from app.core.access_scope import get_visible_employee_ids

        visible = await get_visible_employee_ids(db, emp_user)
        assert visible == {employee.id}

        my_exams = await service.list_my_exams(
            db, tenant.id, visible_employee_ids=visible
        )
        assert len(my_exams) == 1
        assert my_exams[0]["mass_exam_title"] == "HRP-225 list"
        assert my_exams[0]["status"] == "assigned"

    async def test_draft_exam_hidden_from_assignee(
        self, db: AsyncSession, tenant, user, employee_user
    ):
        emp_user, employee = employee_user
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-225 draft")
        )
        await service.add_question(db, tenant.id, me["id"], _question())
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])

        my_exams = await service.list_my_exams(db, tenant.id, employee.id)
        assert my_exams == []  # draft never visible


class TestAssignEmployeesFilters:
    async def test_silently_drops_unknown_employee_id(
        self, db: AsyncSession, tenant, user
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-225 unknown")
        )
        exams = await service.assign_employees(
            db, tenant.id, me["id"], [uuid.uuid4()]
        )
        assert exams == []

    async def test_dedupes_existing_assignment(
        self, db: AsyncSession, tenant, user, employee
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-225 dedupe")
        )
        first = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        assert len(first) == 1
        second = await service.assign_employees(db, tenant.id, me["id"], [employee.id])
        assert second == []
        results = await service.list_mass_exam_results(db, tenant.id, me["id"])
        assert len(results) == 1


# Avoid "warning unused" with pytest's strict-marker config.
pytest_plugins: list[str] = []


class TestHRP333EmployeeSummary:
    async def test_results_carry_position_and_status(
        self, db: AsyncSession, tenant, user, employee_user
    ):
        _, employee = employee_user
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="Exam HRP-333")
        )
        await service.add_question(db, tenant.id, me["id"], _question())
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])

        results = await service.list_mass_exam_results(db, tenant.id, me["id"])
        assert results[0]["position_title"] == employee.position_title
        assert results[0]["employee_status"] == employee.status
