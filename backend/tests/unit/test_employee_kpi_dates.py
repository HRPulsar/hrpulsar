"""HRP-246: Employee profile KPI tile data sources.

Pins the new ``employees.status_changed_at`` and ``users.first_login_at``
stamping so the profile header tiles can show "since {last status
change}" / "joined {first auth date}" without re-deriving them from the
events log on every render.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from app.modules.auth import service as auth_service
from app.modules.employee import service as employee_service
from app.modules.employee.schemas import EmployeeCreate, EmployeeUpdate
from sqlalchemy.ext.asyncio import AsyncSession


class TestStatusChangedAt:
    async def test_update_employee_stamps_status_changed_at(
        self, db: AsyncSession, tenant, employee, user
    ) -> None:
        before = employee.status_changed_at
        await employee_service.update_employee(
            db,
            tenant.id,
            employee.id,
            EmployeeUpdate(status="inactive"),
            user,
        )
        await db.refresh(employee)
        assert employee.status_changed_at is not None
        assert employee.status_changed_at != before

    async def test_update_without_status_change_keeps_timestamp(
        self, db: AsyncSession, tenant, employee, user
    ) -> None:
        # Seed a known value so we can verify it does not move.
        employee.status_changed_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        await db.commit()
        await db.refresh(employee)
        seeded = employee.status_changed_at

        await employee_service.update_employee(
            db,
            tenant.id,
            employee.id,
            EmployeeUpdate(status="active"),  # same as current
            user,
        )
        await db.refresh(employee)
        assert employee.status_changed_at == seeded

    async def test_status_changed_at_renders_in_read_payload(
        self, db: AsyncSession, tenant, employee, user
    ) -> None:
        await employee_service.update_employee(
            db,
            tenant.id,
            employee.id,
            EmployeeUpdate(status="terminated"),
            user,
        )
        payload = await employee_service.get_employee(db, tenant.id, employee.id)
        assert "status_changed_at" in payload
        assert payload["status_changed_at"] is not None
        assert payload["status"] == "terminated"

    async def test_create_employee_seeds_status_changed_at(
        self, db: AsyncSession, tenant, admin_role, position
    ) -> None:
        from app.core.security import hash_password
        from app.modules.auth.models import User, user_roles

        u = User(
            email="kpi-create@test.com",
            password_hash=hash_password("x"),
            first_name="Kpi",
            last_name="Create",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await db.execute(
            user_roles.insert().values(user_id=u.id, role_id=admin_role.id)
        )
        await db.commit()

        payload = await employee_service.create_employee(
            db,
            tenant.id,
            EmployeeCreate(
                user_id=u.id, hire_date=date(2024, 1, 15), position_id=position.id
            ),
        )
        assert payload["status_changed_at"] is not None


class TestFirstLoginAt:
    async def test_login_stamps_first_login_at_once(
        self, db: AsyncSession, tenant, admin_role
    ) -> None:
        from app.core.security import hash_password
        from app.modules.auth.models import User, user_roles

        u = User(
            email="first-login@test.com",
            password_hash=hash_password("pw-12345"),
            first_name="First",
            last_name="Login",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await db.execute(
            user_roles.insert().values(user_id=u.id, role_id=admin_role.id)
        )
        await db.commit()

        assert u.first_login_at is None

        await auth_service.login(db, "first-login@test.com", "pw-12345")
        await db.refresh(u)
        first_stamp = u.first_login_at
        assert first_stamp is not None

        # Second login must not move the timestamp.
        await auth_service.login(db, "first-login@test.com", "pw-12345")
        await db.refresh(u)
        assert u.first_login_at == first_stamp

    async def test_failed_login_does_not_stamp(
        self, db: AsyncSession, tenant, admin_role
    ) -> None:
        from app.core.security import hash_password
        from app.modules.auth.models import User, user_roles
        from fastapi import HTTPException

        u = User(
            email="failed-login@test.com",
            password_hash=hash_password("correct"),
            first_name="Failed",
            last_name="Login",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await db.execute(
            user_roles.insert().values(user_id=u.id, role_id=admin_role.id)
        )
        await db.commit()

        with pytest.raises(HTTPException):
            await auth_service.login(db, "failed-login@test.com", "wrong")

        await db.refresh(u)
        assert u.first_login_at is None

    async def test_first_login_renders_in_employee_read(
        self, db: AsyncSession, tenant, employee, user
    ) -> None:
        # Stamp manually — covers the read path even when the user is
        # never funnelled through the login fixture.
        user.first_login_at = datetime(2025, 9, 1, 12, 0, tzinfo=timezone.utc)
        await db.commit()

        payload = await employee_service.get_employee(db, tenant.id, employee.id)
        assert "user_first_login_at" in payload
        assert payload["user_first_login_at"] == user.first_login_at
