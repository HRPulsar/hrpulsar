"""Tests for GF11: Detailed Employee Events."""

from datetime import date

from app.modules.employee import service
from app.modules.employee.schemas import (
    CompensationCreate,
    CompensationUpdate,
    EmployeeEventCreate,
    EmployeeUpdate,
)
from sqlalchemy.ext.asyncio import AsyncSession


class TestDetailedEmployeeEvents:
    async def test_position_change_creates_event_with_diff(
        self, db: AsyncSession, employee, tenant, user
    ):
        from app.modules.position.models import Position

        new_pos = Position(
            tenant_id=tenant.id, title="Senior Engineer", source="manual"
        )
        db.add(new_pos)
        await db.commit()
        await db.refresh(new_pos)

        data = EmployeeUpdate(position_id=new_pos.id)
        await service.update_employee(db, tenant.id, employee.id, data, user)

        events = await service.list_events(
            db, tenant.id, employee.id, event_type="position_change", current_user=user
        )
        assert len(events) == 1
        event = events[0]
        assert event["event_type"] == "position_change"
        assert event["old_value"]["position_title"] == "Software Engineer"
        assert event["new_value"]["position_title"] == "Senior Engineer"
        # HRP-732: the diff also carries ids, so a later report can ask
        # "did the grade move?" without matching on a renameable title.
        assert event["new_value"]["position_id"] == str(new_pos.id)
        assert "grade_id" in event["new_value"]

    async def test_division_change_creates_event_with_diff(
        self, db: AsyncSession, employee, tenant, user
    ):
        from app.modules.company.models import Division

        div = Division(name="Engineering", tenant_id=tenant.id)
        db.add(div)
        await db.commit()
        await db.refresh(div)

        data = EmployeeUpdate(division_id=div.id)
        await service.update_employee(db, tenant.id, employee.id, data, user)

        events = await service.list_events(
            db, tenant.id, employee.id, event_type="division_change", current_user=user
        )
        assert len(events) == 1
        event = events[0]
        assert event["old_value"]["division_id"] is None
        assert event["new_value"]["division_id"] == str(div.id)

    async def test_compensation_create_event_with_new_value(
        self, db: AsyncSession, employee, tenant, user
    ):
        data = CompensationCreate(
            type="salary",
            amount=600000,
            currency="USD",
            effective_date=date(2024, 1, 1),
        )
        await service.create_compensation(db, tenant.id, employee.id, data, user)

        events = await service.list_events(
            db, tenant.id, employee.id, event_type="compensation_change", current_user=user
        )
        assert len(events) == 1
        event = events[0]
        assert event["new_value"]["amount"] == 600000
        assert event["old_value"] is None

    async def test_compensation_update_event_with_old_new(
        self, db: AsyncSession, employee, tenant, user
    ):
        data = CompensationCreate(
            type="salary",
            amount=500000,
            currency="USD",
            effective_date=date(2024, 1, 1),
        )
        result = await service.create_compensation(
            db, tenant.id, employee.id, data, user
        )

        update = CompensationUpdate(amount=600000)
        await service.update_compensation(db, tenant.id, result["id"], update, user)

        events = await service.list_events(
            db, tenant.id, employee.id, event_type="compensation_change", current_user=user
        )
        # Should have 2 events: create + update
        assert len(events) == 2
        update_event = events[0]  # most recent
        assert update_event["old_value"]["amount"] == 500000
        assert update_event["new_value"]["amount"] == 600000

    async def test_filter_events_by_type(self, db: AsyncSession, employee, tenant, user):
        # Employee already has a 'hire' event from creation
        all_events = await service.list_events(db, tenant.id, employee.id, None, user)
        hire_events = await service.list_events(
            db, tenant.id, employee.id, event_type="hire", current_user=user
        )
        assert len(hire_events) <= len(all_events)
        for e in hire_events:
            assert e["event_type"] == "hire"

    async def test_filter_returns_empty_for_unknown_type(
        self, db: AsyncSession, employee, tenant, user
    ):
        events = await service.list_events(
            db, tenant.id, employee.id, event_type="nonexistent", current_user=user
        )
        assert events == []

    async def test_manual_event_creation(
        self, db: AsyncSession, employee, tenant, user
    ):
        data = EmployeeEventCreate(
            event_type="certification_earned",
            description="AWS Solutions Architect",
            event_date=date(2024, 6, 1),
            metadata={"cert": "AWS SAA"},
        )
        result = await service.create_event(db, tenant.id, employee.id, data, user)
        assert result["event_type"] == "certification_earned"
        assert result["description"] == "AWS Solutions Architect"

    async def test_termination_event(self, db: AsyncSession, employee, tenant, user):
        data = EmployeeUpdate(status="terminated")
        await service.update_employee(db, tenant.id, employee.id, data, user)

        events = await service.list_events(
            db, tenant.id, employee.id, event_type="termination", current_user=user
        )
        assert len(events) == 1


async def test_hire_event_keeps_the_position_as_a_value(
    db: AsyncSession, user, tenant
):
    """HRP-999: the timeline words the hire in the viewer's language from
    ``new_value``; the English description stays for the API."""
    from app.modules.employee.schemas import EmployeeCreate

    emp = await service.create_employee(
        db,
        tenant.id,
        EmployeeCreate(
            user_id=user.id, position_title="Engineer", hire_date=date(2024, 1, 15)
        ),
    )
    [hire] = await service.list_events(
        db, tenant.id, emp["id"], event_type="hire", current_user=user
    )
    assert hire["description"] == "Hired as Engineer"
    assert hire["new_value"] == {"position_title": "Engineer"}
