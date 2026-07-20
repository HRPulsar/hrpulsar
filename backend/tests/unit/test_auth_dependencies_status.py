"""EMP1: Employee.status enforcement on auth-guard and token-issuance paths.

Users whose Employee record carries status `terminated` or `inactive` must
not be able to use existing access tokens, refresh tokens, log in, select
a tenant, or switch tenants. Tenant admins without an Employee card must
keep working.
"""

from datetime import date

import pytest
from app.modules.auth import service as auth_service
from app.modules.auth.dependencies import get_current_user
from app.modules.employee.models import Employee
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _set_status(db: AsyncSession, emp: Employee, new_status: str) -> None:
    emp.status = new_status
    await db.commit()
    await db.refresh(emp)


class TestAuthGuardEmployeeStatus:
    async def test_active_employee_passes(
        self, db: AsyncSession, user, employee, access_token
    ):
        from app.core.security import decode_token

        decode_token(access_token)
        loaded = await get_current_user(token=access_token, db=db)
        assert loaded.id == user.id

    async def test_admin_without_employee_card_passes(
        self, db: AsyncSession, user, access_token
    ):
        loaded = await get_current_user(token=access_token, db=db)
        assert loaded.id == user.id

    @pytest.mark.parametrize("blocked_status", ["terminated", "inactive"])
    async def test_blocked_status_rejects_guard(
        self,
        db: AsyncSession,
        user,
        employee,
        access_token,
        blocked_status,
    ):
        await _set_status(db, employee, blocked_status)

        with pytest.raises(HTTPException) as excinfo:
            await get_current_user(token=access_token, db=db)
        assert excinfo.value.status_code == 401
        assert excinfo.value.detail["error_code"] == "employee_status_blocked"
        assert excinfo.value.detail["status"] == blocked_status

    async def test_on_leave_status_passes(
        self, db: AsyncSession, user, employee, access_token
    ):
        await _set_status(db, employee, "on_leave")
        loaded = await get_current_user(token=access_token, db=db)
        assert loaded.id == user.id


class TestTokenIssuancePathsBlocked:
    async def test_login_rejects_terminated(self, db: AsyncSession, user, employee):
        await _set_status(db, employee, "terminated")
        with pytest.raises(HTTPException) as excinfo:
            await auth_service.login(db, user.email, "testpass123")
        assert excinfo.value.status_code == 401
        assert excinfo.value.detail["error_code"] == "employee_status_blocked"

    async def test_login_rejects_inactive(self, db: AsyncSession, user, employee):
        await _set_status(db, employee, "inactive")
        with pytest.raises(HTTPException) as excinfo:
            await auth_service.login(db, user.email, "testpass123")
        assert excinfo.value.status_code == 401

    async def test_refresh_rejects_blocked(self, db: AsyncSession, user, employee):
        await _set_status(db, employee, "terminated")
        with pytest.raises(HTTPException) as excinfo:
            await auth_service.refresh_tokens(db, user.id)
        assert excinfo.value.status_code == 401
        assert excinfo.value.detail["error_code"] == "employee_status_blocked"

    async def test_select_tenant_rejects_blocked(
        self, db: AsyncSession, user, employee, tenant
    ):
        await _set_status(db, employee, "inactive")
        with pytest.raises(HTTPException) as excinfo:
            await auth_service.select_tenant(db, user.email, "testpass123", tenant.id)
        assert excinfo.value.status_code == 401
        assert excinfo.value.detail["error_code"] == "employee_status_blocked"

    async def test_switch_tenant_rejects_blocked(
        self, db: AsyncSession, user, employee, tenant
    ):
        await _set_status(db, employee, "terminated")
        with pytest.raises(HTTPException) as excinfo:
            await auth_service.switch_tenant(db, user.id, user.email, tenant.id)
        assert excinfo.value.status_code == 401
        assert excinfo.value.detail["error_code"] == "employee_status_blocked"


class TestAuthMeBlockedViaHttp:
    async def test_get_me_returns_401_when_terminated(
        self,
        db: AsyncSession,
        employee,
        auth_client: AsyncClient,
    ):
        await _set_status(db, employee, "terminated")
        resp = await auth_client.get("/api/auth/me")
        assert resp.status_code == 401
        body = resp.json()
        assert body["detail"]["error_code"] == "employee_status_blocked"
        assert body["detail"]["status"] == "terminated"

    async def test_get_me_passes_when_active(
        self,
        db: AsyncSession,
        employee,
        auth_client: AsyncClient,
    ):
        # Sanity: with an active Employee card, /auth/me returns 200.
        # The `employee` fixture creates an active record by default.
        assert employee.status == "active"
        # touch hire_date to silence unused-fixture warnings if any
        assert isinstance(employee.hire_date, date)
        resp = await auth_client.get("/api/auth/me")
        assert resp.status_code == 200
