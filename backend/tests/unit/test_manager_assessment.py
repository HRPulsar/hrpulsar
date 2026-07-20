"""Tests for GF6: Auto-assign manager as assessment reviewer + subtree visibility."""

import uuid
from datetime import date

from app.core.security import hash_password
from app.modules.assessment import service as assessment_service
from app.modules.assessment.models import AssessmentParticipant
from app.modules.auth.models import User
from app.modules.company.models import Division
from app.modules.employee import service as employee_service
from app.modules.employee.models import Employee
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class _Stub:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class TestAutoAssignManager:
    async def _create_manager_setup(self, db, tenant):
        """Create a manager user+employee, a division with that manager, and an employee in division."""
        # Manager user & employee
        mgr_user = User(
            email=f"mgr-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("test"),
            first_name="Manager",
            last_name="One",
            tenant_id=tenant.id,
        )
        db.add(mgr_user)
        await db.flush()
        mgr_emp = Employee(
            user_id=mgr_user.id,
            tenant_id=tenant.id,
            position_title="Manager",
            hire_date=date(2023, 1, 1),
        )
        db.add(mgr_emp)
        await db.flush()

        # Division with manager
        div = Division(tenant_id=tenant.id, name="Engineering", manager_id=mgr_emp.id)
        db.add(div)
        await db.flush()

        # Employee in division
        emp_user = User(
            email=f"emp-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("test"),
            first_name="Employee",
            last_name="One",
            tenant_id=tenant.id,
        )
        db.add(emp_user)
        await db.flush()
        emp = Employee(
            user_id=emp_user.id,
            tenant_id=tenant.id,
            position_title="Developer",
            hire_date=date(2023, 6, 1),
            division_id=div.id,
        )
        db.add(emp)
        await db.commit()

        return mgr_user, mgr_emp, div, emp_user, emp

    async def test_manager_auto_assigned(
        self, db: AsyncSession, tenant, assessment_statuses, assessment_types
    ):
        mgr_user, mgr_emp, div, emp_user, emp = await self._create_manager_setup(
            db, tenant
        )

        data = _Stub(
            type_code="360",
            title="Test Assessment",
            employee_id=emp.id,
            specialization_id=None,
            grade_id=None,
            scale_id=None,
            approver_id=None,
            ended_at=None,
        )
        result = await assessment_service.create_assessment(
            db, tenant.id, emp_user.id, data
        )

        # Check participants: self (evaluatee) + manager (auto-assigned for 360)
        parts = await db.execute(
            select(AssessmentParticipant).where(
                AssessmentParticipant.assessment_id == result["id"]
            )
        )
        participants = parts.scalars().all()
        manager_parts = [p for p in participants if p.role == "manager"]
        self_parts = [p for p in participants if p.role == "self"]
        assert len(manager_parts) == 1
        assert manager_parts[0].user_id == mgr_user.id
        assert len(self_parts) == 1
        assert self_parts[0].user_id == emp_user.id

    async def test_no_auto_assign_without_manager(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """If division has no manager, only the self-participant is created."""
        data = _Stub(
            type_code="360",
            title="Test",
            employee_id=employee.id,
            specialization_id=None,
            grade_id=None,
            scale_id=None,
            approver_id=None,
            ended_at=None,
        )
        result = await assessment_service.create_assessment(
            db, tenant.id, user.id, data
        )

        parts = await db.execute(
            select(AssessmentParticipant).where(
                AssessmentParticipant.assessment_id == result["id"]
            )
        )
        participants = parts.scalars().all()
        # Only self-participant; no manager (employee has no division manager)
        assert len(participants) == 1
        assert participants[0].role == "self"

    async def test_manager_not_assigned_as_own_reviewer(
        self, db: AsyncSession, tenant, assessment_statuses, assessment_types
    ):
        """If the assessed employee IS the manager, don't auto-assign manager — but self is still added."""
        mgr_user = User(
            email=f"selfmgr-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("test"),
            first_name="Self",
            last_name="Manager",
            tenant_id=tenant.id,
        )
        db.add(mgr_user)
        await db.flush()
        mgr_emp = Employee(
            user_id=mgr_user.id,
            tenant_id=tenant.id,
            position_title="Director",
            hire_date=date(2023, 1, 1),
        )
        db.add(mgr_emp)
        await db.flush()
        div = Division(tenant_id=tenant.id, name="Sales", manager_id=mgr_emp.id)
        db.add(div)
        await db.flush()
        mgr_emp.division_id = div.id
        await db.commit()

        data = _Stub(
            type_code="self",
            title="Self eval",
            employee_id=mgr_emp.id,
            specialization_id=None,
            grade_id=None,
            scale_id=None,
            approver_id=None,
            ended_at=None,
        )
        result = await assessment_service.create_assessment(
            db, tenant.id, mgr_user.id, data
        )

        parts = await db.execute(
            select(AssessmentParticipant).where(
                AssessmentParticipant.assessment_id == result["id"]
            )
        )
        participants = parts.scalars().all()
        # Only self-participant (no separate manager since the assessee IS the manager).
        # For type=self, manager auto-assignment is skipped entirely.
        assert len(participants) == 1
        assert participants[0].role == "self"
        assert participants[0].user_id == mgr_user.id


class TestManagerSubtreeVisibility:
    async def test_manager_sees_subtree_employees(self, db: AsyncSession, tenant):
        """Manager of a division sees employees from child divisions too."""
        # Manager
        mgr_user = User(
            email=f"mgr-sub-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("test"),
            first_name="Mgr",
            last_name="Sub",
            tenant_id=tenant.id,
        )
        db.add(mgr_user)
        await db.flush()
        mgr_emp = Employee(
            user_id=mgr_user.id,
            tenant_id=tenant.id,
            position_title="VP",
            hire_date=date(2023, 1, 1),
        )
        db.add(mgr_emp)
        await db.flush()

        # Parent division with manager
        parent_div = Division(tenant_id=tenant.id, name="Tech", manager_id=mgr_emp.id)
        db.add(parent_div)
        await db.flush()

        # Child division
        child_div = Division(
            tenant_id=tenant.id, name="Backend", parent_id=parent_div.id
        )
        db.add(child_div)
        await db.flush()

        # Employees in parent and child
        for i, div in enumerate([parent_div, child_div]):
            u = User(
                email=f"sub-emp-{i}-{uuid.uuid4().hex[:6]}@test.com",
                password_hash=hash_password("test"),
                first_name=f"Emp{i}",
                last_name="Test",
                tenant_id=tenant.id,
            )
            db.add(u)
            await db.flush()
            db.add(
                Employee(
                    user_id=u.id,
                    tenant_id=tenant.id,
                    position_title="Dev",
                    hire_date=date(2024, 1, 1),
                    division_id=div.id,
                )
            )
        await db.commit()

        from app.core.access_scope import get_managed_division_ids
        from app.modules.employee.models import Employee as EmployeeModel
        from sqlalchemy import select as sa_select

        div_ids = await get_managed_division_ids(db, tenant.id, mgr_emp.id)
        result = await db.execute(
            sa_select(EmployeeModel.id).where(
                EmployeeModel.tenant_id == tenant.id,
                EmployeeModel.division_id.in_(div_ids),
            )
        )
        scope = {mgr_emp.id, *result.scalars().all()}

        items, total = await employee_service.list_employees(
            db,
            tenant.id,
            visible_employee_ids=scope,
        )
        # mgr + 2 subtree employees
        assert total == 3

    async def test_non_manager_gets_only_self(self, db: AsyncSession, tenant, employee):
        """A regular employee scope contains only the employee itself."""
        items, total = await employee_service.list_employees(
            db,
            tenant.id,
            visible_employee_ids={employee.id},
        )
        assert total == 1
        assert items[0]["id"] == employee.id
