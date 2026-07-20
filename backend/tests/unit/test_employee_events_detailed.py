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
            db, tenant.id, employee.id, event_type="position_change"
        )
        assert len(events) == 1
        event = events[0]
        assert event["event_type"] == "position_change"
        assert event["old_value"] == {"position_title": "Software Engineer"}
        assert event["new_value"] == {"position_title": "Senior Engineer"}

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
            db, tenant.id, employee.id, event_type="division_change"
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
            db, tenant.id, employee.id, event_type="compensation_change"
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
            db, tenant.id, employee.id, event_type="compensation_change"
        )
        # Should have 2 events: create + update
        assert len(events) == 2
        update_event = events[0]  # most recent
        assert update_event["old_value"]["amount"] == 500000
        assert update_event["new_value"]["amount"] == 600000

    async def test_filter_events_by_type(self, db: AsyncSession, employee, tenant):
        # Employee already has a 'hire' event from creation
        all_events = await service.list_events(db, tenant.id, employee.id)
        hire_events = await service.list_events(
            db, tenant.id, employee.id, event_type="hire"
        )
        assert len(hire_events) <= len(all_events)
        for e in hire_events:
            assert e["event_type"] == "hire"

    async def test_filter_returns_empty_for_unknown_type(
        self, db: AsyncSession, employee, tenant
    ):
        events = await service.list_events(
            db, tenant.id, employee.id, event_type="nonexistent"
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
            db, tenant.id, employee.id, event_type="termination"
        )
        assert len(events) == 1
