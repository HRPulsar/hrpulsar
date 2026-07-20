"""EMP3 — POST /employees/{id}/downgrade-role."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest_asyncio
from app.core.security import hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.company import service as company_service
from app.modules.company.schemas import DivisionCreate
from app.modules.employee import service as employee_service
from app.modules.employee.models import Employee
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def manager_role(db: AsyncSession):
    result = await db.execute(
        select(Role).where(Role.code == "manager", Role.is_system == True)  # noqa: E712
    )
    role = result.scalar_one_or_none()
    if not role:
        role = Role(name="Manager", code="manager", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


@pytest_asyncio.fixture
async def employee_role(db: AsyncSession):
    result = await db.execute(
        select(Role).where(
            Role.code == "employee",
            Role.is_system == True,  # noqa: E712
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        role = Role(name="Employee", code="employee", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


async def _user_with(db, tenant, role: Role) -> User:
    u = User(
        email=f"u-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name="X",
        last_name="Y",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    return u


async def _make_emp(db, tenant, user: User) -> Employee:
    emp = Employee(user_id=user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _user_codes(db, user_id) -> set[str]:
    rows = await db.execute(
        select(Role.code)
        .join(user_roles, user_roles.c.role_id == Role.id)
        .where(user_roles.c.user_id == user_id)
    )
    return {c for (c,) in rows.all()}


class TestDowngradeRole:
    async def test_downgrade_after_auto_apply_is_idempotent(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        """HRP-196: update_division now auto-downgrades on last-division
        loss, so the explicit endpoint is a no-op when the role is gone.
        The endpoint must stay idempotent for clients that still call it
        (legacy UI flow + retries).
        """
        u = await _user_with(db, tenant, employee_role)
        emp = await _make_emp(db, tenant, u)
        # Assign + auto-upgrade
        d = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp.id)
        )
        # Unassign — HRP-196 auto-downgrades server-side.
        from app.modules.company.schemas import DivisionUpdate

        await company_service.update_division(
            db, tenant.id, d["id"], DivisionUpdate(manager_id=None)
        )
        codes = await _user_codes(db, u.id)
        assert "manager" not in codes  # already stripped by HRP-196
        assert "employee" in codes

        # Explicit endpoint is now a no-op (idempotent retry path).
        result = await employee_service.downgrade_employee_role(db, tenant.id, emp.id)
        assert result["downgraded"] is False
        codes = await _user_codes(db, u.id)
        assert "manager" not in codes
        assert "employee" in codes

    async def test_downgrade_strips_manager_when_role_still_present(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        """Direct endpoint call when the user still has `manager` (e.g.
        edge-case where they were granted the role outside of division
        assignment) — must strip it.
        """
        u = await _user_with(db, tenant, manager_role)
        emp = await _make_emp(db, tenant, u)
        # Sanity: user holds manager, no division reference
        codes = await _user_codes(db, u.id)
        assert "manager" in codes

        result = await employee_service.downgrade_employee_role(db, tenant.id, emp.id)
        assert result["downgraded"] is True
        codes = await _user_codes(db, u.id)
        assert "manager" not in codes

    async def test_downgrade_rejects_when_still_manages(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        u = await _user_with(db, tenant, employee_role)
        emp = await _make_emp(db, tenant, u)
        await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp.id)
        )
        import pytest

        with pytest.raises(HTTPException) as exc:
            await employee_service.downgrade_employee_role(db, tenant.id, emp.id)
        assert exc.value.status_code == 409
        assert exc.value.detail["error_code"] == "still_manages_divisions"

    async def test_downgrade_does_not_touch_admin(
        self, db: AsyncSession, tenant, admin_role
    ):
        u = await _user_with(db, tenant, admin_role)
        emp = await _make_emp(db, tenant, u)
        # No division assignment — but admin still cannot be downgraded by this endpoint
        import pytest

        with pytest.raises(HTTPException) as exc:
            await employee_service.downgrade_employee_role(db, tenant.id, emp.id)
        assert exc.value.status_code == 422
        assert exc.value.detail["error_code"] == "cannot_downgrade_admin"
        codes = await _user_codes(db, u.id)
        assert "admin" in codes

    async def test_downgrade_idempotent_when_no_manager_role(
        self, db: AsyncSession, tenant, employee_role
    ):
        u = await _user_with(db, tenant, employee_role)
        emp = await _make_emp(db, tenant, u)
        result = await employee_service.downgrade_employee_role(db, tenant.id, emp.id)
        assert result["downgraded"] is False
