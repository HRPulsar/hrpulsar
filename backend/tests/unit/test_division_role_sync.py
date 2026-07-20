"""EMP3 — Division manager assignment auto-syncs user roles."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest_asyncio
from app.core.security import hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.company import service as company_service
from app.modules.company.schemas import DivisionCreate, DivisionUpdate
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


@pytest_asyncio.fixture
async def platform_admin_role(db: AsyncSession):
    result = await db.execute(
        select(Role).where(
            Role.code == "platform_admin", Role.is_system == True  # noqa: E712
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        role = Role(name="Platform Admin", code="platform_admin", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


async def _make_user(db, tenant, role: Role) -> User:
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


async def _make_employee(db, tenant, user: User) -> Employee:
    emp = Employee(
        user_id=user.id,
        tenant_id=tenant.id,
        hire_date=date(2024, 1, 1),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _user_codes(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    rows = await db.execute(
        select(Role.code)
        .join(user_roles, user_roles.c.role_id == Role.id)
        .where(user_roles.c.user_id == user_id)
    )
    return {c for (c,) in rows.all()}


class TestAssignUpgrade:
    async def test_assign_manager_upgrades_employee_to_manager(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        u = await _make_user(db, tenant, employee_role)
        emp = await _make_employee(db, tenant, u)
        await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp.id)
        )
        codes = await _user_codes(db, u.id)
        assert "manager" in codes
        assert "employee" in codes  # original role preserved

    async def test_assign_manager_does_not_touch_admin(
        self, db: AsyncSession, tenant, admin_role, manager_role
    ):
        u = await _make_user(db, tenant, admin_role)
        emp = await _make_employee(db, tenant, u)
        await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Ops", manager_id=emp.id)
        )
        codes = await _user_codes(db, u.id)
        assert codes == {"admin"}

    async def test_assign_manager_does_not_touch_platform_admin(
        self, db: AsyncSession, tenant, platform_admin_role, manager_role
    ):
        u = await _make_user(db, tenant, platform_admin_role)
        emp = await _make_employee(db, tenant, u)
        await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Ops", manager_id=emp.id)
        )
        codes = await _user_codes(db, u.id)
        assert codes == {"platform_admin"}

    async def test_deputy_assign_also_upgrades(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        u = await _make_user(db, tenant, employee_role)
        emp = await _make_employee(db, tenant, u)
        await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", deputy_manager_id=emp.id)
        )
        codes = await _user_codes(db, u.id)
        assert "manager" in codes

    async def test_update_assign_upgrades(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        u = await _make_user(db, tenant, employee_role)
        emp = await _make_employee(db, tenant, u)
        created = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng")
        )
        await company_service.update_division(
            db, tenant.id, created["id"], DivisionUpdate(manager_id=emp.id)
        )
        codes = await _user_codes(db, u.id)
        assert "manager" in codes

    async def test_update_assign_returns_role_upgrade_entry(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        # HRP-196: the upgrade now surfaces in the response so the UI
        # can toast "<Name> promoted to manager". Previously the
        # operator had to navigate elsewhere to verify the change.
        u = await _make_user(db, tenant, employee_role)
        emp = await _make_employee(db, tenant, u)
        created = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng")
        )
        result = await company_service.update_division(
            db, tenant.id, created["id"], DivisionUpdate(manager_id=emp.id)
        )
        upgrades = result["role_upgrades"]
        assert len(upgrades) == 1
        assert upgrades[0]["employee_id"] == emp.id
        assert upgrades[0]["user_id"] == u.id
        assert upgrades[0]["new_role"] == "manager"

    async def test_create_division_returns_role_upgrade_entry(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        u = await _make_user(db, tenant, employee_role)
        emp = await _make_employee(db, tenant, u)
        result = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp.id)
        )
        assert len(result["role_upgrades"]) == 1
        assert result["role_upgrades"][0]["employee_id"] == emp.id

    async def test_role_upgrade_skipped_when_already_manager(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        # Reassigning an existing manager to another division must not
        # generate a duplicate toast.
        u = await _make_user(db, tenant, employee_role)
        emp = await _make_employee(db, tenant, u)
        await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp.id)
        )
        result = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Ops", manager_id=emp.id)
        )
        assert result["role_upgrades"] == []

    async def test_role_upgrade_deduplicated_when_same_person_in_both_slots(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        # Same employee picked as both Manager and Deputy Manager — the
        # sync helper runs twice but the API must report a single entry
        # so the UI does not show "promoted to manager" twice.
        u = await _make_user(db, tenant, employee_role)
        emp = await _make_employee(db, tenant, u)
        result = await company_service.create_division(
            db,
            tenant.id,
            DivisionCreate(
                name="Eng", manager_id=emp.id, deputy_manager_id=emp.id
            ),
        )
        assert len(result["role_upgrades"]) == 1
        assert result["role_upgrades"][0]["employee_id"] == emp.id


class TestPendingDowngrade:
    async def test_reassign_marks_pending_when_no_other_division(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        u_a = await _make_user(db, tenant, employee_role)
        emp_a = await _make_employee(db, tenant, u_a)
        u_b = await _make_user(db, tenant, employee_role)
        emp_b = await _make_employee(db, tenant, u_b)

        created = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp_a.id)
        )
        # Re-fetch user roles eagerly so subsequent role checks see the upgrade
        result = await company_service.update_division(
            db, tenant.id, created["id"], DivisionUpdate(manager_id=emp_b.id)
        )
        pending = result["pending_role_downgrade"]
        assert len(pending) == 1
        assert pending[0]["employee_id"] == emp_a.id
        assert pending[0]["current_role"] == "manager"

        codes_b = await _user_codes(db, u_b.id)
        assert "manager" in codes_b

    async def test_reassign_no_pending_when_a_still_manages_other(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        u_a = await _make_user(db, tenant, employee_role)
        emp_a = await _make_employee(db, tenant, u_a)
        u_b = await _make_user(db, tenant, employee_role)
        emp_b = await _make_employee(db, tenant, u_b)

        # A manages two divisions
        d1 = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp_a.id)
        )
        await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Ops", manager_id=emp_a.id)
        )
        # Reassign d1 to B
        result = await company_service.update_division(
            db, tenant.id, d1["id"], DivisionUpdate(manager_id=emp_b.id)
        )
        assert result["pending_role_downgrade"] == []

    async def test_unassign_to_null_marks_pending(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        u = await _make_user(db, tenant, employee_role)
        emp = await _make_employee(db, tenant, u)
        d = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp.id)
        )
        result = await company_service.update_division(
            db, tenant.id, d["id"], DivisionUpdate(manager_id=None)
        )
        assert len(result["pending_role_downgrade"]) == 1
        assert result["pending_role_downgrade"][0]["employee_id"] == emp.id

    async def test_no_pending_when_still_deputy_of_same_division(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        # Employee is both manager and deputy of the same division.
        # Clearing only manager_id → must NOT mark pending: they still
        # operate as deputy of this very division.
        u = await _make_user(db, tenant, employee_role)
        emp = await _make_employee(db, tenant, u)
        d = await company_service.create_division(
            db,
            tenant.id,
            DivisionCreate(name="Eng", manager_id=emp.id, deputy_manager_id=emp.id),
        )
        result = await company_service.update_division(
            db, tenant.id, d["id"], DivisionUpdate(manager_id=None)
        )
        assert result["pending_role_downgrade"] == []

    async def test_pending_excludes_admin(
        self, db: AsyncSession, tenant, admin_role, manager_role
    ):
        # admin user assigned, then unassigned — must NOT appear in pending
        u = await _make_user(db, tenant, admin_role)
        emp = await _make_employee(db, tenant, u)
        d = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp.id)
        )
        result = await company_service.update_division(
            db, tenant.id, d["id"], DivisionUpdate(manager_id=None)
        )
        assert result["pending_role_downgrade"] == []


class TestHrp196AutoDowngrade:
    """HRP-196: spec §5 — previous manager is auto-set to Employee when
    they lose their last division. No confirm dialog."""

    async def test_unassign_auto_downgrades_to_employee(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        u = await _make_user(db, tenant, employee_role)
        emp = await _make_employee(db, tenant, u)
        d = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp.id)
        )
        # Sanity: assignment upgraded employee → manager
        codes = await _user_codes(db, u.id)
        assert "manager" in codes

        result = await company_service.update_division(
            db, tenant.id, d["id"], DivisionUpdate(manager_id=None)
        )
        # Pending entry surfaces so the client can show a toast.
        assert len(result["pending_role_downgrade"]) == 1
        entry = result["pending_role_downgrade"][0]
        assert entry["employee_id"] == emp.id
        assert entry["downgraded"] is True

        # Role already stripped server-side — no client confirm needed.
        codes = await _user_codes(db, u.id)
        assert "manager" not in codes
        assert "employee" in codes

    async def test_reassign_auto_downgrades_previous_manager(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        u_a = await _make_user(db, tenant, employee_role)
        emp_a = await _make_employee(db, tenant, u_a)
        u_b = await _make_user(db, tenant, employee_role)
        emp_b = await _make_employee(db, tenant, u_b)

        created = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp_a.id)
        )
        result = await company_service.update_division(
            db, tenant.id, created["id"], DivisionUpdate(manager_id=emp_b.id)
        )
        # Spec §5: previous manager auto-downgraded to Employee
        assert len(result["pending_role_downgrade"]) == 1
        assert result["pending_role_downgrade"][0]["downgraded"] is True
        codes_a = await _user_codes(db, u_a.id)
        assert "manager" not in codes_a
        assert "employee" in codes_a
        # Spec §3.i: new manager auto-upgraded
        codes_b = await _user_codes(db, u_b.id)
        assert "manager" in codes_b

    async def test_auto_downgrade_skipped_when_still_manages_other(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        # Spec §5 only triggers when the link to the LAST division breaks.
        u = await _make_user(db, tenant, employee_role)
        emp = await _make_employee(db, tenant, u)
        d1 = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp.id)
        )
        await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Ops", manager_id=emp.id)
        )
        result = await company_service.update_division(
            db, tenant.id, d1["id"], DivisionUpdate(manager_id=None)
        )
        assert result["pending_role_downgrade"] == []
        codes = await _user_codes(db, u.id)
        # Still manages Ops → manager role preserved.
        assert "manager" in codes

    async def test_auto_downgrade_does_not_touch_admin(
        self, db: AsyncSession, tenant, admin_role, manager_role
    ):
        # Spec §6: Admin / Platform admin keep their role.
        u = await _make_user(db, tenant, admin_role)
        emp = await _make_employee(db, tenant, u)
        d = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp.id)
        )
        result = await company_service.update_division(
            db, tenant.id, d["id"], DivisionUpdate(manager_id=None)
        )
        assert result["pending_role_downgrade"] == []
        codes = await _user_codes(db, u.id)
        assert "admin" in codes
        assert "manager" not in codes

    async def test_invitation_role_unchanged_on_auto_downgrade(
        self, db: AsyncSession, tenant, manager_role, employee_role
    ):
        """Spec §7: invitation role must stay as the invited role.

        We never touch the Invitation table on downgrade — this guard is
        a regression pin in case future code wants to keep them in sync.
        """
        from datetime import datetime, timedelta, timezone

        from app.modules.auth.models import Invitation
        from sqlalchemy import select as sa_select

        u = await _make_user(db, tenant, employee_role)
        emp = await _make_employee(db, tenant, u)
        # Pretend this user was originally invited as manager.
        inv = Invitation(
            email=u.email,
            name=f"{u.first_name} {u.last_name}".strip() or "User",
            tenant_id=tenant.id,
            role_code="manager",
            invited_by=u.id,
            token=f"tok-{uuid.uuid4().hex}",
            status="accepted",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.add(inv)
        await db.commit()

        d = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Eng", manager_id=emp.id)
        )
        await company_service.update_division(
            db, tenant.id, d["id"], DivisionUpdate(manager_id=None)
        )

        rows = (
            await db.execute(
                sa_select(Invitation.role_code).where(Invitation.email == u.email)
            )
        ).all()
        assert len(rows) == 1
        # Invitation role_code unchanged after auto-downgrade.
        assert rows[0][0] == "manager"
