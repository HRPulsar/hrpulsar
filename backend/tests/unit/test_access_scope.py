"""Tests for app.core.access_scope — scope helper used across modules."""

from datetime import date, datetime, timezone

import pytest_asyncio
from app.core import access_scope
from app.core.security import hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def employee_role(db: AsyncSession):
    result = await db.execute(select(Role).where(Role.code == "employee"))
    role = result.scalar_one_or_none()
    if not role:
        role = Role(name="Employee", code="employee", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


async def _make_user(db: AsyncSession, tenant, role: Role, email_suffix: str) -> User:
    u = User(
        email=f"{email_suffix}@test.com",
        password_hash=hash_password("x"),
        first_name=email_suffix,
        last_name="X",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    db.expunge(u)
    result = await db.execute(select(User).where(User.id == u.id))
    return result.scalar_one()


async def _make_employee(db: AsyncSession, tenant, user, division=None) -> Employee:
    emp = Employee(
        user_id=user.id,
        tenant_id=tenant.id,
        hire_date=date(2024, 1, 1),
        division_id=division.id if division else None,
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


class TestAccessScope:
    async def test_admin_returns_none(self, db: AsyncSession, user):
        # 'user' fixture has admin role
        scope = await access_scope.get_visible_employee_ids(db, user)
        assert scope is None

    async def test_employee_without_employee_row_returns_empty(
        self, db: AsyncSession, tenant, employee_role
    ):
        u = await _make_user(db, tenant, employee_role, "alice")
        scope = await access_scope.get_visible_employee_ids(db, u)
        assert scope == set()

    async def test_employee_sees_only_self(
        self, db: AsyncSession, tenant, employee_role
    ):
        u = await _make_user(db, tenant, employee_role, "bob")
        emp = await _make_employee(db, tenant, u)
        # And another, unrelated employee
        u2 = await _make_user(db, tenant, employee_role, "carol")
        await _make_employee(db, tenant, u2)

        scope = await access_scope.get_visible_employee_ids(db, u)
        assert scope == {emp.id}

    async def test_division_manager_sees_subtree(
        self, db: AsyncSession, tenant, employee_role
    ):
        manager_user = await _make_user(db, tenant, employee_role, "mgr")
        manager_emp = await _make_employee(db, tenant, manager_user)

        root = Division(tenant_id=tenant.id, name="Eng", manager_id=manager_emp.id)
        db.add(root)
        await db.commit()
        await db.refresh(root)

        child = Division(tenant_id=tenant.id, name="Backend", parent_id=root.id)
        db.add(child)
        await db.commit()
        await db.refresh(child)

        # employees in subtree
        eng_user = await _make_user(db, tenant, employee_role, "eng")
        eng_emp = await _make_employee(db, tenant, eng_user, division=root)
        be_user = await _make_user(db, tenant, employee_role, "be")
        be_emp = await _make_employee(db, tenant, be_user, division=child)
        # outsider
        out_user = await _make_user(db, tenant, employee_role, "out")
        await _make_employee(db, tenant, out_user)

        scope = await access_scope.get_visible_employee_ids(db, manager_user)
        assert scope is not None
        assert manager_emp.id in scope
        assert eng_emp.id in scope
        assert be_emp.id in scope
        assert len(scope) == 3

    async def test_deputy_manager_sees_subtree(
        self, db: AsyncSession, tenant, employee_role
    ):
        deputy_user = await _make_user(db, tenant, employee_role, "dep")
        deputy_emp = await _make_employee(db, tenant, deputy_user)

        div = Division(tenant_id=tenant.id, name="HR", deputy_manager_id=deputy_emp.id)
        db.add(div)
        await db.commit()
        await db.refresh(div)

        member_user = await _make_user(db, tenant, employee_role, "hrmem")
        member_emp = await _make_employee(db, tenant, member_user, division=div)

        scope = await access_scope.get_visible_employee_ids(db, deputy_user)
        assert scope == {deputy_emp.id, member_emp.id}

    async def test_get_managed_division_ids_empty_for_non_manager(
        self, db: AsyncSession, tenant, employee
    ):
        ids = await access_scope.get_managed_division_ids(db, tenant.id, employee.id)
        assert ids == []
