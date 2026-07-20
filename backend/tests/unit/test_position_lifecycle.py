"""POS6 backend tests: occupancy + lifecycle status transitions."""

import uuid
from datetime import date

import pytest
from app.modules.auth.models import User
from app.modules.employee.models import Employee
from app.modules.position import service
from app.modules.position.models import Position
from app.modules.position.schemas import PositionUpdate
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_user(db: AsyncSession, tenant) -> User:
    """Cheap user factory; bypasses the auth fixtures."""
    from datetime import datetime, timezone

    from app.core.security import hash_password

    u = User(
        email=f"pos6-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name="POS",
        last_name="Six",
        tenant_id=tenant.id,
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


class TestPositionOccupancy:
    async def test_zero_assigned_when_no_employees(self, db: AsyncSession, tenant):
        pos = Position(
            tenant_id=tenant.id,
            title="Empty Role",
            headcount=3,
        )
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        result = await service.get_position_occupancy(db, tenant.id, pos.id)
        assert result["assigned"] == 0
        assert result["headcount"] == 3
        assert result["vacant"] == 3

    async def test_assigned_counted_against_headcount(self, db: AsyncSession, tenant):
        pos = Position(
            tenant_id=tenant.id,
            title="Filled Role",
            headcount=2,
        )
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        for _ in range(2):
            user = await _make_user(db, tenant)
            db.add(
                Employee(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    position_id=pos.id,
                    position_title=pos.title,
                    hire_date=date(2025, 1, 1),
                )
            )
        await db.commit()

        result = await service.get_position_occupancy(db, tenant.id, pos.id)
        assert result["assigned"] == 2
        assert result["headcount"] == 2
        assert result["vacant"] == 0

    async def test_vacant_clamps_to_zero_when_overfilled(
        self, db: AsyncSession, tenant
    ):
        pos = Position(
            tenant_id=tenant.id,
            title="Overfilled",
            headcount=1,
        )
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        for _ in range(3):
            user = await _make_user(db, tenant)
            db.add(
                Employee(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    position_id=pos.id,
                    position_title=pos.title,
                    hire_date=date(2025, 1, 1),
                )
            )
        await db.commit()

        result = await service.get_position_occupancy(db, tenant.id, pos.id)
        assert result["assigned"] == 3
        assert result["headcount"] == 1
        assert result["vacant"] == 0

    async def test_vacant_is_none_when_headcount_unset(self, db: AsyncSession, tenant):
        pos = Position(tenant_id=tenant.id, title="Open Slot")
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        result = await service.get_position_occupancy(db, tenant.id, pos.id)
        assert result["assigned"] == 0
        assert result["headcount"] is None
        assert result["vacant"] is None

    async def test_not_found_raises_404(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.get_position_occupancy(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404


class TestSetPositionStatus:
    async def test_change_status_to_each_lifecycle(self, db: AsyncSession, tenant):
        pos = Position(tenant_id=tenant.id, title="Status Cycle")
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        for next_status in ("on_hold", "frozen", "closed", "active"):
            result = await service.set_position_status(
                db, tenant.id, pos.id, next_status
            )
            assert result["lifecycle_status"] == next_status
            # is_active stays in sync with the canonical state
            assert result["is_active"] == (next_status == "active")

    async def test_invalid_status_rejected(self, db: AsyncSession, tenant):
        pos = Position(tenant_id=tenant.id, title="Invalid Status")
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        with pytest.raises(HTTPException) as exc:
            await service.set_position_status(db, tenant.id, pos.id, "garbage")
        assert exc.value.status_code == 400

    async def test_set_status_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.set_position_status(db, tenant.id, uuid.uuid4(), "active")
        assert exc.value.status_code == 404

    async def test_closed_position_blocks_field_edits(self, db: AsyncSession, tenant):
        pos = Position(
            tenant_id=tenant.id,
            title="Closed Slot",
            lifecycle_status="closed",
            is_active=False,
        )
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        # Title edit while closed must fail with 409.
        with pytest.raises(HTTPException) as exc:
            await service.update_position(
                db,
                tenant.id,
                pos.id,
                PositionUpdate(title="New Title"),
            )
        assert exc.value.status_code == 409

    async def test_closed_position_allows_lifecycle_only_update(
        self, db: AsyncSession, tenant
    ):
        pos = Position(
            tenant_id=tenant.id,
            title="Reopen Me",
            lifecycle_status="closed",
            is_active=False,
        )
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        # Reopening via PUT (lifecycle_status only) is permitted so HR can
        # edit title afterwards without going through the dedicated endpoint.
        result = await service.update_position(
            db,
            tenant.id,
            pos.id,
            PositionUpdate(lifecycle_status="active"),
        )
        assert result["lifecycle_status"] == "active"
        assert result["is_active"] is True


class TestPositionMatrixStatus:
    async def test_status_unconfigured_without_links(self, db: AsyncSession, tenant):
        from app.modules.dictionary.models import DictionaryItem

        spec = DictionaryItem(
            tenant_id=tenant.id, type="specialization", title="Backend"
        )
        grade = DictionaryItem(tenant_id=tenant.id, type="grade", title="Junior")
        db.add_all([spec, grade])
        await db.commit()
        await db.refresh(spec)
        await db.refresh(grade)

        pos = Position(
            tenant_id=tenant.id,
            title="BE Junior",
            specialization_id=spec.id,
            grade_id=grade.id,
        )
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        result = await service.get_matrix_status(db, tenant.id, pos.id)
        assert result["configured"] is False
        assert result["link_count"] == 0

    async def test_status_unconfigured_when_pair_missing(
        self, db: AsyncSession, tenant
    ):
        pos = Position(
            tenant_id=tenant.id,
            title="No spec/grade",
        )
        db.add(pos)
        await db.commit()
        await db.refresh(pos)

        result = await service.get_matrix_status(db, tenant.id, pos.id)
        assert result["configured"] is False
        assert result["grade_specialization_id"] is None
