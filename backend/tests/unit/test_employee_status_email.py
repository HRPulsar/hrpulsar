"""EMP1: status changes publish an event that maps to a user-facing email.

Verifies two layers:
1. `update_employee` emits the right event_type for each status transition.
2. The event payload routes to the right notification template via
   `EVENT_NOTIFICATION_MAP`, with `user_email` set to the employee's own
   user — not the admin who triggered the change.
"""

from datetime import date

import pytest
from app.core import events as events_module
from app.core.event_notifications import EVENT_NOTIFICATION_MAP
from app.modules.employee import service
from app.modules.employee.schemas import EmployeeUpdate
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def captured_events(monkeypatch):
    """Replace `app.core.events.publish` with a recorder."""
    bag: list[tuple[str, dict]] = []

    async def fake_publish(event: str, data: dict) -> None:
        bag.append((event, data))

    monkeypatch.setattr(events_module, "publish", fake_publish)
    return bag


class TestStatusEventDispatch:
    async def test_active_to_terminated_emits_termination(
        self, db: AsyncSession, tenant, employee, user, captured_events
    ):
        await service.update_employee(
            db, tenant.id, employee.id, EmployeeUpdate(status="terminated"), user
        )
        kinds = [e for e, _ in captured_events]
        assert "employee.event_created" in kinds
        last = next(
            payload
            for ev, payload in captured_events
            if payload.get("event_type") == "termination"
        )
        assert last["event_type"] == "termination"

    async def test_active_to_inactive_emits_status_inactive(
        self, db: AsyncSession, tenant, employee, user, captured_events
    ):
        await service.update_employee(
            db, tenant.id, employee.id, EmployeeUpdate(status="inactive"), user
        )
        types = [p["event_type"] for _, p in captured_events]
        assert "status_inactive" in types

    async def test_terminated_to_active_emits_reactivated(
        self, db: AsyncSession, tenant, employee, user, captured_events
    ):
        # Move to terminated first (without recording — we filter later).
        employee.status = "terminated"
        await db.commit()
        captured_events.clear()

        await service.update_employee(
            db, tenant.id, employee.id, EmployeeUpdate(status="active"), user
        )
        types = [p["event_type"] for _, p in captured_events]
        assert "status_reactivated" in types

    async def test_inactive_to_active_emits_reactivated(
        self, db: AsyncSession, tenant, employee, user, captured_events
    ):
        employee.status = "inactive"
        await db.commit()
        captured_events.clear()

        await service.update_employee(
            db, tenant.id, employee.id, EmployeeUpdate(status="active"), user
        )
        types = [p["event_type"] for _, p in captured_events]
        assert "status_reactivated" in types

    async def test_no_change_no_status_event(
        self, db: AsyncSession, tenant, employee, user, captured_events
    ):
        await service.update_employee(
            db, tenant.id, employee.id, EmployeeUpdate(status="active"), user
        )
        types = [p["event_type"] for _, p in captured_events]
        assert "termination" not in types
        assert "status_inactive" not in types
        assert "status_reactivated" not in types

    async def test_event_recipient_is_employee_user_email(
        self, db: AsyncSession, tenant, employee, user, captured_events
    ):
        await service.update_employee(
            db, tenant.id, employee.id, EmployeeUpdate(status="terminated"), user
        )
        payloads = [p for _, p in captured_events]
        assert any(p["user_email"] == user.email for p in payloads)


class TestNotificationMap:
    def test_map_covers_three_status_transitions(self):
        assert EVENT_NOTIFICATION_MAP["termination"] == "employee_terminated"
        assert EVENT_NOTIFICATION_MAP["status_inactive"] == "employee_inactive"
        assert EVENT_NOTIFICATION_MAP["status_reactivated"] == "employee_reactivated"


class TestEventDiff:
    async def test_status_event_carries_old_and_new_value(
        self, db: AsyncSession, tenant, employee, user
    ):
        await service.update_employee(
            db, tenant.id, employee.id, EmployeeUpdate(status="terminated"), user
        )
        events = await service.list_events(
            db, tenant.id, employee.id, event_type="termination"
        )
        assert len(events) == 1
        assert events[0]["old_value"] == {"status": "active"}
        assert events[0]["new_value"] == {"status": "terminated"}
        assert events[0]["event_date"] == date.today()
