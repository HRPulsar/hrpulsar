"""Tests for GF5: Salary & Compensation."""

import uuid
from datetime import date

import pytest
from app.modules.employee import service
from app.modules.employee.schemas import (
    CompensationCreate,
    CompensationUpdate,
)
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession


class TestCompensation:
    async def test_create_salary(self, db: AsyncSession, employee, tenant, user):
        data = CompensationCreate(
            type="salary",
            amount=500000,
            currency="USD",
            effective_date=date(2024, 1, 1),
            notes="Annual salary",
        )
        result = await service.create_compensation(
            db, tenant.id, employee.id, data, user
        )
        assert result["type"] == "salary"
        assert result["amount"] == 500000
        assert result["currency"] == "USD"
        assert result["notes"] == "Annual salary"
        assert result["employee_id"] == employee.id

    async def test_create_bonus(self, db: AsyncSession, employee, tenant, user):
        data = CompensationCreate(
            type="bonus",
            amount=100000,
            currency="EUR",
            effective_date=date(2024, 6, 1),
        )
        result = await service.create_compensation(
            db, tenant.id, employee.id, data, user
        )
        assert result["type"] == "bonus"
        assert result["currency"] == "EUR"

    async def test_create_allowance(self, db: AsyncSession, employee, tenant, user):
        data = CompensationCreate(
            type="allowance",
            amount=25000,
            currency="USD",
            effective_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        result = await service.create_compensation(
            db, tenant.id, employee.id, data, user
        )
        assert result["type"] == "allowance"
        assert str(result["end_date"]) == "2024-12-31"

    async def test_list(self, db: AsyncSession, employee, tenant, user):
        for comp_type in ["salary", "bonus", "allowance"]:
            await service.create_compensation(
                db,
                tenant.id,
                employee.id,
                CompensationCreate(
                    type=comp_type,
                    amount=100000,
                    currency="USD",
                    effective_date=date(2024, 1, 1),
                ),
                user,
            )
        items = await service.list_compensations(db, tenant.id, employee.id, user)
        assert len(items) >= 3

    async def test_update(self, db: AsyncSession, employee, tenant, user):
        created = await service.create_compensation(
            db,
            tenant.id,
            employee.id,
            CompensationCreate(
                type="salary",
                amount=400000,
                currency="USD",
                effective_date=date(2024, 1, 1),
            ),
            user,
        )
        updated = await service.update_compensation(
            db,
            tenant.id,
            created["id"],
            CompensationUpdate(amount=450000),
            user,
        )
        assert updated["amount"] == 450000
        assert updated["type"] == "salary"  # unchanged

    async def test_delete(self, db: AsyncSession, employee, tenant, user):
        created = await service.create_compensation(
            db,
            tenant.id,
            employee.id,
            CompensationCreate(
                type="salary",
                amount=300000,
                currency="USD",
                effective_date=date(2024, 1, 1),
            ),
            user,
        )
        deleted = await service.delete_compensation(db, tenant.id, created["id"], user)
        assert deleted["id"] == created["id"]
        items = await service.list_compensations(db, tenant.id, employee.id, user)
        assert all(item["id"] != created["id"] for item in items)

    async def test_create_auto_event(self, db: AsyncSession, employee, tenant, user):
        """Creating compensation should auto-create an employee event."""
        await service.create_compensation(
            db,
            tenant.id,
            employee.id,
            CompensationCreate(
                type="salary",
                amount=600000,
                currency="USD",
                effective_date=date(2024, 3, 1),
            ),
            user,
        )
        events = await service.list_events(db, tenant.id, employee.id)
        comp_events = [e for e in events if e["event_type"] == "compensation_change"]
        assert len(comp_events) >= 1

    async def test_create_invalid_employee(self, db: AsyncSession, tenant, user):
        data = CompensationCreate(
            type="salary",
            amount=100000,
            currency="USD",
            effective_date=date(2024, 1, 1),
        )
        with pytest.raises(HTTPException) as exc:
            await service.create_compensation(db, tenant.id, uuid.uuid4(), data, user)
        assert exc.value.status_code == 404

    async def test_delete_not_found(self, db: AsyncSession, tenant, user):
        with pytest.raises(HTTPException) as exc:
            await service.delete_compensation(db, tenant.id, uuid.uuid4(), user)
        assert exc.value.status_code == 404

    async def test_create_amount_exceeds_int32(
        self, db: AsyncSession, employee, tenant, user
    ):
        """HRP-221: amount column is BIGINT — values past INT32_MAX must persist."""
        big_amount = 5_000_000_000  # $50M in cents, ~2.3x INT32_MAX
        result = await service.create_compensation(
            db,
            tenant.id,
            employee.id,
            CompensationCreate(
                type="bonus",
                amount=big_amount,
                currency="USD",
                effective_date=date(2024, 1, 1),
            ),
            user,
        )
        assert result["amount"] == big_amount

    async def test_update_with_date_change_serializes_event(
        self, db: AsyncSession, employee, tenant, user
    ):
        """HRP-221: updating dates must not break JSONB encode of the event."""
        created = await service.create_compensation(
            db,
            tenant.id,
            employee.id,
            CompensationCreate(
                type="salary",
                amount=400000,
                currency="USD",
                effective_date=date(2024, 1, 1),
            ),
            user,
        )
        # Update both amount (triggers event) and dates (used to crash on JSONB).
        updated = await service.update_compensation(
            db,
            tenant.id,
            created["id"],
            CompensationUpdate(
                amount=450000,
                effective_date=date(2024, 6, 30),
                end_date=date(2024, 7, 31),
            ),
            user,
        )
        assert updated["amount"] == 450000
        events = await service.list_events(db, tenant.id, employee.id)
        comp_events = [e for e in events if e["event_type"] == "compensation_change"]
        assert any(
            (e.get("new_value") or {}).get("effective_date") == "2024-06-30"
            and (e.get("new_value") or {}).get("end_date") == "2024-07-31"
            for e in comp_events
        )

    def test_create_end_before_effective_rejected_by_schema(self) -> None:
        """HRP-221: schema validation blocks end_date < effective_date on Create."""
        with pytest.raises(ValidationError):
            CompensationCreate(
                type="salary",
                amount=100000,
                currency="USD",
                effective_date=date(2024, 6, 1),
                end_date=date(2024, 5, 1),
            )

    def test_update_end_before_effective_rejected_by_schema(self) -> None:
        """HRP-221: schema validation blocks end < effective when both supplied."""
        with pytest.raises(ValidationError):
            CompensationUpdate(
                effective_date=date(2024, 6, 1),
                end_date=date(2024, 5, 1),
            )

    async def test_update_end_before_existing_effective_rejected(
        self, db: AsyncSession, employee, tenant, user
    ):
        """HRP-221: service rejects partial update where end_date < stored effective."""
        created = await service.create_compensation(
            db,
            tenant.id,
            employee.id,
            CompensationCreate(
                type="salary",
                amount=100000,
                currency="USD",
                effective_date=date(2024, 6, 1),
            ),
            user,
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_compensation(
                db,
                tenant.id,
                created["id"],
                CompensationUpdate(end_date=date(2024, 5, 1)),
                user,
            )
        assert exc.value.status_code == 422

    async def test_tenant_isolation(self, db: AsyncSession, employee, tenant, user):
        created = await service.create_compensation(
            db,
            tenant.id,
            employee.id,
            CompensationCreate(
                type="salary",
                amount=500000,
                currency="USD",
                effective_date=date(2024, 1, 1),
            ),
            user,
        )
        other_tenant_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            await service.delete_compensation(db, other_tenant_id, created["id"], user)
        assert exc.value.status_code == 404

    # HRP-221 validations -----------------------------------------------

    def test_create_rejects_effective_after_end(self):
        with pytest.raises(ValueError):
            CompensationCreate(
                type="salary",
                amount=500000,
                currency="USD",
                effective_date=date(2024, 6, 1),
                end_date=date(2024, 1, 1),
            )

    def test_update_rejects_effective_after_end(self):
        with pytest.raises(ValueError):
            CompensationUpdate(
                effective_date=date(2024, 6, 1),
                end_date=date(2024, 1, 1),
            )

    def test_update_allows_partial_without_dates(self):
        # HRP-221 Bug 2: editing fields like amount must not be blocked
        # by the date validator when both dates aren't being touched.
        # No exception expected.
        u = CompensationUpdate(amount=999)
        assert u.amount == 999

    async def test_update_keeps_existing_record_when_dates_unchanged(
        self, db: AsyncSession, employee, tenant, user
    ):
        # HRP-221 Bug 2: a happy-path edit returns the updated record and
        # does not surface a backend error to the toast handler.
        created = await service.create_compensation(
            db,
            tenant.id,
            employee.id,
            CompensationCreate(
                type="salary",
                amount=400000,
                currency="USD",
                effective_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
            ),
            user,
        )
        updated = await service.update_compensation(
            db,
            tenant.id,
            created["id"],
            CompensationUpdate(amount=500000, notes="raise"),
            user,
        )
        assert updated["amount"] == 500000
        assert updated["notes"] == "raise"
        assert str(updated["effective_date"]) == "2024-01-01"
        assert str(updated["end_date"]) == "2024-12-31"
