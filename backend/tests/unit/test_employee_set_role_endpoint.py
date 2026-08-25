"""HRP-620 — PUT /employees/{id}/role (replaced EMP3's downgrade-role)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from app.core.security import hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.company import service as company_service
from app.modules.company.schemas import DivisionCreate
from app.modules.employee import service as employee_service
from app.modules.employee.models import Employee, EmployeeEvent
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _system_role(db: AsyncSession, code: str, name: str) -> Role:
    result = await db.execute(
        select(Role).where(Role.code == code, Role.is_system.is_(True))
    )
    role = result.scalars().first()
    if not role:
        role = Role(name=name, code=code, is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


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


class TestSetEmployeeRole:
    async def test_sets_manager_on_a_plain_employee(
        self, db: AsyncSession, tenant, user, manager_role, employee_role
    ):
        u = await _user_with(db, tenant, employee_role)
        emp = await _make_emp(db, tenant, u)

        result = await employee_service.set_employee_role(
            db, tenant.id, emp.id, "manager", user
        )

        assert result["changed"] is True
        assert await _user_codes(db, u.id) == {"manager"}

    async def test_strips_manager_when_no_division_is_left(
        self, db: AsyncSession, tenant, user, manager_role, employee_role
    ):
        u = await _user_with(db, tenant, manager_role)
        emp = await _make_emp(db, tenant, u)

        result = await employee_service.set_employee_role(
            db, tenant.id, emp.id, "employee", user
        )

        assert result["changed"] is True
        assert await _user_codes(db, u.id) == {"employee"}

    async def test_same_role_is_a_no_op(
        self, db: AsyncSession, tenant, user, employee_role
    ):
        u = await _user_with(db, tenant, employee_role)
        emp = await _make_emp(db, tenant, u)

        result = await employee_service.set_employee_role(
            db, tenant.id, emp.id, "employee", user
        )

        assert result["changed"] is False

    async def test_records_a_role_changed_event(
        self, db: AsyncSession, tenant, user, manager_role, employee_role
    ):
        u = await _user_with(db, tenant, employee_role)
        emp = await _make_emp(db, tenant, u)

        await employee_service.set_employee_role(db, tenant.id, emp.id, "manager", user)

        events = (
            (
                await db.execute(
                    select(EmployeeEvent).where(
                        EmployeeEvent.employee_id == emp.id,
                        EmployeeEvent.event_type == "role_changed",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].old_value == {"roles": ["employee"]}
        assert events[0].new_value == {"roles": ["manager"]}

    async def test_refuses_to_change_own_role(
        self, db: AsyncSession, tenant, user, employee_role
    ):
        """The admin editing the list is the one person they must not be able
        to lock out of the workspace."""
        emp = await _make_emp(db, tenant, user)

        with pytest.raises(HTTPException) as exc:
            await employee_service.set_employee_role(
                db, tenant.id, emp.id, "employee", user
            )
        assert exc.value.status_code == 422
        assert exc.value.code == "cannot_change_own_role"

    async def test_refuses_to_demote_the_last_admin(
        self, db: AsyncSession, tenant, user, admin_role, employee_role
    ):
        other_admin = await _user_with(db, tenant, admin_role)
        emp = await _make_emp(db, tenant, other_admin)
        # ``user`` (the caller) is an admin of the same tenant but inactive
        # admins do not count — deactivate them and the target is the last one.
        user.is_active = False
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await employee_service.set_employee_role(
                db, tenant.id, emp.id, "employee", user
            )
        assert exc.value.status_code == 422
        assert exc.value.code == "last_admin"

        user.is_active = True
        await db.commit()

    async def test_demotes_an_admin_while_another_one_remains(
        self, db: AsyncSession, tenant, user, admin_role, employee_role
    ):
        other_admin = await _user_with(db, tenant, admin_role)
        emp = await _make_emp(db, tenant, other_admin)

        result = await employee_service.set_employee_role(
            db, tenant.id, emp.id, "employee", user
        )

        assert result["changed"] is True
        assert await _user_codes(db, other_admin.id) == {"employee"}

    async def test_refuses_while_the_employee_still_leads_a_division(
        self, db: AsyncSession, tenant, user, manager_role, employee_role
    ):
        u = await _user_with(db, tenant, employee_role)
        emp = await _make_emp(db, tenant, u)
        await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp.id)
        )

        with pytest.raises(HTTPException) as exc:
            await employee_service.set_employee_role(
                db, tenant.id, emp.id, "employee", user
            )
        assert exc.value.status_code == 422
        assert exc.value.code == "still_division_manager"

    async def test_refuses_to_demote_an_hr_who_leads_a_division(
        self, db: AsyncSession, tenant, user, admin_role, employee_role
    ):
        """The guard keys off the target role, not the current one — an hr or
        admin running a division never holds the ``manager`` code, and the
        subtree scope follows ``Division.manager_id`` regardless of role."""
        hr_role = await _system_role(db, "hr", "HR")
        u = await _user_with(db, tenant, hr_role)
        emp = await _make_emp(db, tenant, u)
        await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Ops", manager_id=emp.id)
        )

        with pytest.raises(HTTPException) as exc:
            await employee_service.set_employee_role(
                db, tenant.id, emp.id, "employee", user
            )
        assert exc.value.code == "still_division_manager"

    async def test_promotes_a_sitting_division_head_to_hr(
        self, db: AsyncSession, tenant, user, admin_role, manager_role, employee_role
    ):
        """The mirror case: hr may lead a division, so the promotion must not
        be blocked by the same guard."""
        await _system_role(db, "hr", "HR")
        u = await _user_with(db, tenant, employee_role)
        emp = await _make_emp(db, tenant, u)
        await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Ops", manager_id=emp.id)
        )

        result = await employee_service.set_employee_role(
            db, tenant.id, emp.id, "hr", user
        )

        assert result["changed"] is True
        assert await _user_codes(db, u.id) == {"hr"}

    async def test_rejects_an_unknown_role_code(
        self, db: AsyncSession, tenant, user, employee_role
    ):
        u = await _user_with(db, tenant, employee_role)
        emp = await _make_emp(db, tenant, u)

        with pytest.raises(HTTPException) as exc:
            await employee_service.set_employee_role(
                db, tenant.id, emp.id, "wizard", user
            )
        assert exc.value.status_code == 400
        assert exc.value.code == "role_code_not_found"

    async def test_platform_admin_is_not_assignable(
        self, db: AsyncSession, tenant, user, employee_role
    ):
        """It is granted platform-side; a tenant admin must not mint one."""
        existing = (
            (await db.execute(select(Role).where(Role.code == "platform_admin")))
            .scalars()
            .first()
        )
        if existing is None:
            db.add(Role(name="Platform Admin", code="platform_admin", is_system=True))
            await db.commit()
        u = await _user_with(db, tenant, employee_role)
        emp = await _make_emp(db, tenant, u)

        with pytest.raises(HTTPException) as exc:
            await employee_service.set_employee_role(
                db, tenant.id, emp.id, "platform_admin", user
            )
        assert exc.value.status_code == 400
        assert exc.value.code == "role_code_not_found"
