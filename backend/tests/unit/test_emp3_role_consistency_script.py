"""EMP3 — role-consistency reconciliation logic."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest_asyncio
from app.core.security import hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division
from app.modules.employee.models import Employee
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


async def _user(db, tenant, role: Role) -> User:
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


async def _emp(db, tenant, user: User) -> Employee:
    emp = Employee(user_id=user.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _codes(db, user_id) -> set[str]:
    rows = await db.execute(
        select(Role.code)
        .join(user_roles, user_roles.c.role_id == Role.id)
        .where(user_roles.c.user_id == user_id)
    )
    return {c for (c,) in rows.all()}


async def _reconcile_in_session(
    db: AsyncSession, tenant_id, *, dry_run: bool = False
) -> int:
    """Inline copy of the script body, scoped to a single tenant.

    The shared test DB persists rows across tests, so scope by tenant_id to
    keep counts deterministic.
    """
    from sqlalchemy import select

    upgraded = 0
    manager_role = (
        await db.execute(
            select(Role).where(
                Role.code == "manager", Role.is_system == True  # noqa: E712
            )
        )
    ).scalar_one()

    divisions = (
        (await db.execute(select(Division).where(Division.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    employee_ids: set = set()
    for d in divisions:
        if d.manager_id is not None:
            employee_ids.add(d.manager_id)
        if d.deputy_manager_id is not None:
            employee_ids.add(d.deputy_manager_id)
    for emp_id in employee_ids:
        emp = await db.get(Employee, emp_id)
        if emp is None:
            continue
        codes = await _codes(db, emp.user_id)
        if codes & {"admin", "hr", "platform_admin"}:
            continue
        if codes & {"manager"}:
            continue
        if not dry_run:
            await db.execute(
                user_roles.insert().values(user_id=emp.user_id, role_id=manager_role.id)
            )
        upgraded += 1
    if not dry_run:
        await db.commit()
    return upgraded


class TestReconciliation:
    async def test_upgrades_employee_managing_division(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        u = await _user(db, tenant, employee_role)
        emp = await _emp(db, tenant, u)
        # Create division *without* the auto-sync — bypass service
        d = Division(name="Eng", tenant_id=tenant.id, manager_id=emp.id)
        db.add(d)
        await db.commit()

        upgraded = await _reconcile_in_session(db, tenant.id)
        assert upgraded == 1
        codes = await _codes(db, u.id)
        assert "manager" in codes

    async def test_skips_admin(
        self, db: AsyncSession, tenant, admin_role, manager_role
    ):
        u = await _user(db, tenant, admin_role)
        emp = await _emp(db, tenant, u)
        d = Division(name="Eng", tenant_id=tenant.id, manager_id=emp.id)
        db.add(d)
        await db.commit()
        upgraded = await _reconcile_in_session(db, tenant.id)
        assert upgraded == 0
        codes = await _codes(db, u.id)
        assert codes == {"admin"}

    async def test_idempotent(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        u = await _user(db, tenant, employee_role)
        emp = await _emp(db, tenant, u)
        d = Division(name="Eng", tenant_id=tenant.id, manager_id=emp.id)
        db.add(d)
        await db.commit()

        first = await _reconcile_in_session(db, tenant.id)
        second = await _reconcile_in_session(db, tenant.id)
        assert first == 1
        assert second == 0
