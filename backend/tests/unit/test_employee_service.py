import uuid
from datetime import date

import pytest
from app.modules.employee import service
from app.modules.employee.schemas import (
    EmployeeCreate,
    EmployeeEventCreate,
    EmployeeUpdate,
)
from sqlalchemy.ext.asyncio import AsyncSession


class TestEmployeeCRUD:
    async def test_create_employee(self, db: AsyncSession, user, tenant):
        data = EmployeeCreate(
            user_id=user.id,
            position_title="Engineer",
            hire_date=date(2024, 1, 15),
        )
        emp = await service.create_employee(db, tenant.id, data)
        assert emp["position_title"] == "Engineer"
        assert emp["user_id"] == user.id

    async def test_create_employee_invalid_user(self, db: AsyncSession, tenant):
        from fastapi import HTTPException

        data = EmployeeCreate(
            user_id=uuid.uuid4(),
            position_title="Ghost",
            hire_date=date(2024, 1, 1),
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_employee(db, tenant.id, data)
        assert exc.value.status_code == 400

    async def test_list_employees(self, db: AsyncSession, employee, tenant):
        items, total = await service.list_employees(db, tenant.id)
        assert total >= 1
        assert any(e["id"] == employee.id for e in items)

    async def test_list_employees_pagination(self, db: AsyncSession, employee, tenant):
        items, total = await service.list_employees(db, tenant.id, skip=0, limit=1)
        assert len(items) <= 1
        assert total >= 1

    async def test_get_employee(self, db: AsyncSession, employee, tenant):
        emp = await service.get_employee(db, tenant.id, employee.id)
        assert emp["id"] == employee.id
        assert emp["position_title"] == "Software Engineer"

    async def test_get_employee_not_found(self, db: AsyncSession, tenant):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await service.get_employee(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_update_employee(self, db: AsyncSession, employee, tenant, user):
        from app.modules.position.models import Position

        new_pos = Position(
            tenant_id=tenant.id, title="Senior Engineer", source="manual"
        )
        db.add(new_pos)
        await db.commit()
        await db.refresh(new_pos)

        data = EmployeeUpdate(position_id=new_pos.id)
        emp = await service.update_employee(db, tenant.id, employee.id, data, user)
        assert emp["position_title"] == "Senior Engineer"


class TestUpdateEmployeeName:
    """HRP-121: Edit dialog now drives first_name / last_name on the User."""

    async def test_updates_first_and_last_name(
        self, db: AsyncSession, employee, tenant, user
    ):
        from app.modules.auth.models import User as UserModel

        data = EmployeeUpdate(first_name="Alicia", last_name="Reyes")
        emp = await service.update_employee(db, tenant.id, employee.id, data, user)

        assert emp["user_name"] == "Alicia Reyes"
        refreshed = await db.get(UserModel, employee.user_id)
        assert refreshed is not None
        assert refreshed.first_name == "Alicia"
        assert refreshed.last_name == "Reyes"

    async def test_trims_whitespace(self, db: AsyncSession, employee, tenant, user):
        data = EmployeeUpdate(first_name="  Bob  ", last_name="  Smith ")
        emp = await service.update_employee(db, tenant.id, employee.id, data, user)
        assert emp["user_name"] == "Bob Smith"

    async def test_rejects_blank_first_name(
        self, db: AsyncSession, employee, tenant, user
    ):
        from fastapi import HTTPException

        data = EmployeeUpdate(first_name="   ", last_name="Stays")
        with pytest.raises(HTTPException) as exc:
            await service.update_employee(db, tenant.id, employee.id, data, user)
        assert exc.value.status_code == 400

    async def test_partial_update_only_first_name(
        self, db: AsyncSession, employee, tenant, user
    ):
        from app.modules.auth.models import User as UserModel

        before = await db.get(UserModel, employee.user_id)
        assert before is not None
        original_last = before.last_name

        data = EmployeeUpdate(first_name="OnlyFirst")
        emp = await service.update_employee(db, tenant.id, employee.id, data, user)

        assert emp["user_name"].startswith("OnlyFirst ")
        refreshed = await db.get(UserModel, employee.user_id)
        assert refreshed is not None
        assert refreshed.first_name == "OnlyFirst"
        assert refreshed.last_name == original_last

    async def test_name_change_does_not_clobber_status(
        self, db: AsyncSession, employee, tenant, user
    ):
        data = EmployeeUpdate(
            first_name="Carla", last_name="Doe", status="on_leave"
        )
        emp = await service.update_employee(db, tenant.id, employee.id, data, user)
        assert emp["user_name"] == "Carla Doe"
        assert emp["status"] == "on_leave"

    async def test_name_change_logs_audit_event(
        self, db: AsyncSession, employee, tenant, user
    ):
        from app.modules.employee.models import EmployeeEvent
        from sqlalchemy import select

        data = EmployeeUpdate(first_name="Diana", last_name="Vega")
        await service.update_employee(db, tenant.id, employee.id, data, user)

        events = (
            await db.execute(
                select(EmployeeEvent)
                .where(EmployeeEvent.employee_id == employee.id)
                .where(EmployeeEvent.event_type == "name_change")
            )
        ).scalars().all()
        assert len(events) == 1
        assert events[0].new_value == {"first_name": "Diana", "last_name": "Vega"}

    async def test_name_change_skipped_when_unchanged(
        self, db: AsyncSession, employee, tenant, user
    ):
        from app.modules.auth.models import User as UserModel
        from app.modules.employee.models import EmployeeEvent
        from sqlalchemy import select

        original = await db.get(UserModel, employee.user_id)
        assert original is not None
        data = EmployeeUpdate(
            first_name=original.first_name, last_name=original.last_name
        )
        await service.update_employee(db, tenant.id, employee.id, data, user)

        events = (
            await db.execute(
                select(EmployeeEvent)
                .where(EmployeeEvent.employee_id == employee.id)
                .where(EmployeeEvent.event_type == "name_change")
            )
        ).scalars().all()
        assert events == []


class TestEmployeeEvents:
    async def test_add_event(self, db: AsyncSession, employee, tenant, user):
        data = EmployeeEventCreate(
            event_type="promotion",
            description="Promoted to senior",
            event_date=date(2024, 6, 1),
        )
        event = await service.create_event(db, tenant.id, employee.id, data, user)
        assert event["event_type"] == "promotion"
        assert event["employee_id"] == employee.id

    async def test_list_events(self, db: AsyncSession, employee, tenant, user):
        # Add an event first (the employee fixture inserts directly, skipping service)
        data = EmployeeEventCreate(
            event_type="hire",
            description="Hired",
            event_date=date(2024, 1, 15),
        )
        await service.create_event(db, tenant.id, employee.id, data, user)
        events = await service.list_events(db, tenant.id, employee.id)
        assert len(events) >= 1


class TestDeleteEmployeeHRP65:
    """HRP-65: hard delete with relation guard.

    Old behaviour was a soft-delete (status=terminated) that left the row in
    the listing — the toast said "deleted" but the employee still showed up.
    """

    async def test_hard_deletes_employee_without_connections(
        self, db: AsyncSession, employee, tenant, user
    ):
        from app.modules.employee.models import Employee

        emp_id = employee.id
        result = await service.delete_employee(db, tenant.id, emp_id, user)
        assert result["id"] == emp_id
        assert (await db.get(Employee, emp_id)) is None

    async def test_hard_deletes_employee_with_events(
        self, db: AsyncSession, employee, tenant, user
    ):
        # Regression: Employee.events lacked a delete cascade, so SQLAlchemy
        # tried to NULL employee_id (NOT NULL column) on parent delete and
        # raised IntegrityError in production.
        from app.modules.employee.models import Employee, EmployeeEvent
        from sqlalchemy import select

        await service.create_event(
            db,
            tenant.id,
            employee.id,
            EmployeeEventCreate(
                event_type="hire",
                description="Hired as SDR",
                event_date=date(2023, 2, 19),
            ),
            user,
        )

        emp_id = employee.id
        await service.delete_employee(db, tenant.id, emp_id, user)
        assert (await db.get(Employee, emp_id)) is None
        leftover = (
            await db.execute(
                select(EmployeeEvent).where(EmployeeEvent.employee_id == emp_id)
            )
        ).scalars().all()
        assert leftover == []

    async def test_blocks_delete_when_assessment_exists(
        self,
        db: AsyncSession,
        employee,
        tenant,
        user,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.assessment.models import Assessment
        from fastapi import HTTPException

        a = Assessment(
            title="Connected",
            employee_id=employee.id,
            tenant_id=tenant.id,
            initiator_id=employee.user_id,
            type_id=assessment_types["360"].id,
            status_id=assessment_statuses["draft"].id,
        )
        db.add(a)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_employee(db, tenant.id, employee.id, user)
        assert exc.value.status_code == 409
        assert exc.value.detail["error_code"] == "has_connections"
        assert user.first_name in exc.value.detail["message"]
        assert user.last_name in exc.value.detail["message"]
        assert "Action is not possible" in exc.value.detail["message"]

    async def test_blocks_delete_when_employee_manages_division(
        self, db: AsyncSession, employee, tenant, user
    ):
        # Division.manager_id has ondelete=SET NULL — without this guard we
        # would silently demote the division (no event, no warning).
        from app.modules.company.models import Division
        from fastapi import HTTPException

        div = Division(
            tenant_id=tenant.id,
            name="Engineering",
            manager_id=employee.id,
        )
        db.add(div)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.delete_employee(db, tenant.id, employee.id, user)
        assert exc.value.status_code == 409
        assert exc.value.detail["error_code"] == "has_connections"
