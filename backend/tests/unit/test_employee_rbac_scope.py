"""EMP2: RBAC write-scope on /employees/* endpoints.

Matrix:
  - admin × any target (in/out/self) → ok.
  - platform_admin × any target → ok.
  - manager × in-scope (own division subtree) → ok.
  - manager × out-of-scope → 403 outside_division_scope.
  - manager × self → 403 cannot_edit_self_status.
  - employee role × any /employees write → 403 (router-level guard).

Covers update_employee, delete_employee, create_event, and child resources
(work-experience, education, courses, previous-employment, compensation).
Compensation follows the same matrix as the other child resources after
HRP-221 (REDO): managers can view / edit / delete compensation rows for
employees inside their division subtree, and get 403 outside of it.
"""

import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division
from app.modules.employee import service
from app.modules.employee.models import Employee
from app.modules.employee.schemas import (
    CourseCreate,
    EducationCreate,
    EmployeeEventCreate,
    EmployeeUpdate,
    PreviousEmploymentCreate,
    WorkExperienceCreate,
)
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


@pytest_asyncio.fixture
async def manager_role(db: AsyncSession):
    result = await db.execute(
        select(Role).where(Role.code == "manager", Role.is_system.is_(True))
    )
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(name="Manager", code="manager", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


@pytest_asyncio.fixture
async def employee_role(db: AsyncSession):
    result = await db.execute(
        select(Role).where(Role.code == "employee", Role.is_system.is_(True))
    )
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(name="Employee", code="employee", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


@pytest_asyncio.fixture
async def platform_admin_role(db: AsyncSession):
    result = await db.execute(
        select(Role).where(Role.code == "platform_admin", Role.is_system.is_(True))
    )
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(name="Platform admin", code="platform_admin", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


async def _make_user(
    db: AsyncSession, tenant_id: uuid.UUID, role: Role, *, prefix: str
) -> User:
    u = User(
        email=f"{prefix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name=prefix.capitalize(),
        last_name="User",
        tenant_id=tenant_id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    db.expunge(u)
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == u.id)
    )
    return result.scalar_one()


async def _make_employee(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    division_id: uuid.UUID | None,
) -> Employee:
    emp = Employee(
        tenant_id=tenant_id,
        user_id=user_id,
        division_id=division_id,
        hire_date=date(2024, 1, 1),
        status="active",
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


@pytest_asyncio.fixture
async def two_divisions(db: AsyncSession, tenant):
    parent = Division(name="Engineering", tenant_id=tenant.id)
    other = Division(name="Sales", tenant_id=tenant.id)
    db.add_all([parent, other])
    await db.commit()
    await db.refresh(parent)
    await db.refresh(other)
    child = Division(name="Backend", tenant_id=tenant.id, parent_id=parent.id)
    db.add(child)
    await db.commit()
    await db.refresh(child)
    return parent, child, other


@pytest_asyncio.fixture
async def manager_setup(db: AsyncSession, tenant, manager_role, two_divisions):
    """Manager user + employee card; manages parent division."""
    parent, child, other = two_divisions
    user = await _make_user(db, tenant.id, manager_role, prefix="manager")
    emp = await _make_employee(db, tenant.id, user.id, division_id=parent.id)
    parent.manager_id = emp.id
    await db.commit()
    await db.refresh(parent)
    return {
        "user": user,
        "employee": emp,
        "parent_division": parent,
        "child_division": child,
        "other_division": other,
    }


@pytest_asyncio.fixture
async def in_scope_target(db: AsyncSession, tenant, employee_role, manager_setup):
    target_user = await _make_user(db, tenant.id, employee_role, prefix="in-scope")
    return await _make_employee(
        db, tenant.id, target_user.id, manager_setup["child_division"].id
    )


@pytest_asyncio.fixture
async def out_of_scope_target(db: AsyncSession, tenant, employee_role, manager_setup):
    target_user = await _make_user(db, tenant.id, employee_role, prefix="out-scope")
    return await _make_employee(
        db, tenant.id, target_user.id, manager_setup["other_division"].id
    )


@pytest_asyncio.fixture
async def employee_user_setup(db: AsyncSession, tenant, employee_role):
    """Plain employee role user + their own employee card."""
    u = await _make_user(db, tenant.id, employee_role, prefix="emp")
    emp = await _make_employee(db, tenant.id, u.id, division_id=None)
    return {"user": u, "employee": emp}


@pytest_asyncio.fixture
async def rbac_position(db: AsyncSession, tenant):
    from app.modules.position.models import Position

    pos = Position(tenant_id=tenant.id, title="QA Engineer", source="manual")
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


# ---------------------------------------------------------------------------
# update_employee scope matrix
# ---------------------------------------------------------------------------


class TestUpdateEmployeeScope:
    async def test_admin_updates_any_employee(
        self, db: AsyncSession, tenant, user, out_of_scope_target
    ):
        result = await service.update_employee(
            db,
            tenant.id,
            out_of_scope_target.id,
            EmployeeUpdate(status="inactive"),
            user,
        )
        assert result["status"] == "inactive"

    async def test_admin_updates_self(self, db: AsyncSession, tenant, user, employee):
        # `employee` fixture wraps the admin `user`; self-edit must succeed.
        result = await service.update_employee(
            db,
            tenant.id,
            employee.id,
            EmployeeUpdate(status="inactive"),
            user,
        )
        assert result["status"] == "inactive"

    async def test_platform_admin_updates_any(
        self,
        db: AsyncSession,
        tenant,
        platform_admin_role,
        out_of_scope_target,
    ):
        pa = await _make_user(db, tenant.id, platform_admin_role, prefix="pa")
        result = await service.update_employee(
            db,
            tenant.id,
            out_of_scope_target.id,
            EmployeeUpdate(status="inactive"),
            pa,
        )
        assert result["status"] == "inactive"

    async def test_manager_updates_in_scope(
        self, db: AsyncSession, tenant, manager_setup, in_scope_target
    ):
        result = await service.update_employee(
            db,
            tenant.id,
            in_scope_target.id,
            EmployeeUpdate(status="inactive"),
            manager_setup["user"],
        )
        assert result["status"] == "inactive"

    async def test_manager_updates_in_subtree(
        self, db: AsyncSession, tenant, manager_setup, employee_role
    ):
        deep_user = await _make_user(db, tenant.id, employee_role, prefix="deep")
        deep_emp = await _make_employee(
            db, tenant.id, deep_user.id, manager_setup["child_division"].id
        )
        result = await service.update_employee(
            db,
            tenant.id,
            deep_emp.id,
            EmployeeUpdate(status="inactive"),
            manager_setup["user"],
        )
        assert result["status"] == "inactive"

    async def test_manager_blocked_out_of_scope(
        self, db: AsyncSession, tenant, manager_setup, out_of_scope_target
    ):
        with pytest.raises(HTTPException) as exc:
            await service.update_employee(
                db,
                tenant.id,
                out_of_scope_target.id,
                EmployeeUpdate(status="inactive"),
                manager_setup["user"],
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "outside_division_scope"

    async def test_manager_cannot_change_own_status(
        self, db: AsyncSession, tenant, manager_setup
    ):
        with pytest.raises(HTTPException) as exc:
            await service.update_employee(
                db,
                tenant.id,
                manager_setup["employee"].id,
                EmployeeUpdate(status="inactive"),
                manager_setup["user"],
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "cannot_edit_self_status"

    async def test_manager_cannot_change_own_position(
        self, db: AsyncSession, tenant, manager_setup, position
    ):
        with pytest.raises(HTTPException) as exc:
            await service.update_employee(
                db,
                tenant.id,
                manager_setup["employee"].id,
                EmployeeUpdate(position_id=position.id),
                manager_setup["user"],
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "cannot_edit_self_status"

    async def test_manager_cannot_self_edit_any_field_via_employees(
        self, db: AsyncSession, tenant, manager_setup
    ):
        # division_id is also blocked for managers on themselves; self-edit goes
        # through /auth/me (EMP1 allowlist).
        with pytest.raises(HTTPException) as exc:
            await service.update_employee(
                db,
                tenant.id,
                manager_setup["employee"].id,
                EmployeeUpdate(division_id=manager_setup["other_division"].id),
                manager_setup["user"],
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "cannot_edit_self_status"


# ---------------------------------------------------------------------------
# delete_employee scope matrix
# ---------------------------------------------------------------------------


class TestDeleteEmployeeScope:
    async def test_admin_deletes_out_of_scope(
        self, db: AsyncSession, tenant, user, out_of_scope_target
    ):
        target_id = out_of_scope_target.id
        result = await service.delete_employee(db, tenant.id, target_id, user)
        # HRP-65: hard delete — snapshot returned, row gone.
        assert result["id"] == target_id
        assert (await db.get(Employee, target_id)) is None

    async def test_manager_delete_out_of_scope_blocked(
        self, db: AsyncSession, tenant, manager_setup, out_of_scope_target
    ):
        with pytest.raises(HTTPException) as exc:
            await service.delete_employee(
                db, tenant.id, out_of_scope_target.id, manager_setup["user"]
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "outside_division_scope"


# ---------------------------------------------------------------------------
# create_event scope
# ---------------------------------------------------------------------------


class TestCreateEventScope:
    async def test_manager_creates_event_in_scope(
        self, db: AsyncSession, tenant, manager_setup, in_scope_target
    ):
        result = await service.create_event(
            db,
            tenant.id,
            in_scope_target.id,
            EmployeeEventCreate(
                event_type="note",
                description="ok",
                event_date=date.today(),
            ),
            manager_setup["user"],
        )
        assert result["event_type"] == "note"

    async def test_manager_event_blocked_out_of_scope(
        self, db: AsyncSession, tenant, manager_setup, out_of_scope_target
    ):
        with pytest.raises(HTTPException) as exc:
            await service.create_event(
                db,
                tenant.id,
                out_of_scope_target.id,
                EmployeeEventCreate(
                    event_type="note",
                    description="nope",
                    event_date=date.today(),
                ),
                manager_setup["user"],
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "outside_division_scope"


# ---------------------------------------------------------------------------
# Child-resource scope (one case per resource)
# ---------------------------------------------------------------------------


class TestChildResourceScope:
    async def test_manager_work_experience_in_scope(
        self,
        db: AsyncSession,
        tenant,
        manager_setup,
        in_scope_target,
        rbac_position,
    ):
        result = await service.create_work_experience(
            db,
            tenant.id,
            in_scope_target.id,
            WorkExperienceCreate(
                division_id=manager_setup["child_division"].id,
                position_id=rbac_position.id,
                start_date=date(2024, 1, 1),
            ),
            manager_setup["user"],
        )
        assert result["position_id"] == rbac_position.id

    async def test_manager_work_experience_out_of_scope_blocked(
        self,
        db: AsyncSession,
        tenant,
        manager_setup,
        out_of_scope_target,
        rbac_position,
    ):
        with pytest.raises(HTTPException) as exc:
            await service.create_work_experience(
                db,
                tenant.id,
                out_of_scope_target.id,
                WorkExperienceCreate(
                    division_id=manager_setup["other_division"].id,
                    position_id=rbac_position.id,
                    start_date=date(2024, 1, 1),
                ),
                manager_setup["user"],
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "outside_division_scope"

    async def test_manager_education_out_of_scope_blocked(
        self, db: AsyncSession, tenant, manager_setup, out_of_scope_target
    ):
        with pytest.raises(HTTPException) as exc:
            await service.create_education(
                db,
                tenant.id,
                out_of_scope_target.id,
                EducationCreate(
                    institution="X",
                    degree="Bachelor",
                    field_of_study="X",
                    start_date=date(2014, 9, 1),
                ),
                manager_setup["user"],
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "outside_division_scope"

    async def test_manager_course_out_of_scope_blocked(
        self, db: AsyncSession, tenant, manager_setup, out_of_scope_target
    ):
        with pytest.raises(HTTPException) as exc:
            await service.create_course(
                db,
                tenant.id,
                out_of_scope_target.id,
                CourseCreate(title="X", completed_date=date(2024, 1, 1)),
                manager_setup["user"],
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "outside_division_scope"

    async def test_manager_previous_employment_out_of_scope_blocked(
        self, db: AsyncSession, tenant, manager_setup, out_of_scope_target
    ):
        with pytest.raises(HTTPException) as exc:
            await service.create_previous_employment(
                db,
                tenant.id,
                out_of_scope_target.id,
                PreviousEmploymentCreate(
                    company_name="X",
                    position="X",
                    start_date=date(2020, 1, 1),
                    end_date=date(2020, 12, 31),
                ),
                manager_setup["user"],
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "outside_division_scope"


# ---------------------------------------------------------------------------
# Router-level guards: employee role and compensation
# ---------------------------------------------------------------------------


class TestRouterRoleGuards:
    async def test_employee_role_blocked_on_update(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        employee_user_setup,
    ):
        token = create_access_token(str(employee_user_setup["user"].id), str(tenant.id))
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.put(
            f"/api/employees/{employee_user_setup['employee'].id}",
            json={"status": "inactive"},
        )
        assert r.status_code == 403

    async def test_employee_role_blocked_on_delete(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        employee_user_setup,
    ):
        token = create_access_token(str(employee_user_setup["user"].id), str(tenant.id))
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.delete(
            f"/api/employees/{employee_user_setup['employee'].id}",
        )
        assert r.status_code == 403

    async def test_employee_role_blocked_on_work_experience(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        employee_user_setup,
    ):
        token = create_access_token(str(employee_user_setup["user"].id), str(tenant.id))
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.post(
            f"/api/employees/{employee_user_setup['employee'].id}/work-experience",
            json={"title": "X", "start_date": "2024-01-01"},
        )
        assert r.status_code == 403

    async def test_manager_creates_compensation_in_scope(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        manager_setup,
        in_scope_target,
    ):
        # HRP-221 (REDO): managers can now write Compensation on
        # employees inside their managed division subtree.
        token = create_access_token(str(manager_setup["user"].id), str(tenant.id))
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.post(
            f"/api/employees/{in_scope_target.id}/compensation",
            json={
                "type": "salary",
                "amount": 100000,
                "currency": "USD",
                "effective_date": "2024-01-01",
            },
        )
        assert r.status_code == 201, r.text

    async def test_manager_lists_compensation_in_scope(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        manager_setup,
        in_scope_target,
    ):
        # Read access must also clear — `_list_children` previously had
        # no scope check; HRP-221 (REDO) wires `assert_employee_write_scope`
        # into the list path too so admin/manager paths agree.
        token = create_access_token(str(manager_setup["user"].id), str(tenant.id))
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.get(f"/api/employees/{in_scope_target.id}/compensation")
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    async def test_manager_blocked_on_compensation_out_of_scope(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        manager_setup,
        out_of_scope_target,
    ):
        token = create_access_token(str(manager_setup["user"].id), str(tenant.id))
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.post(
            f"/api/employees/{out_of_scope_target.id}/compensation",
            json={
                "type": "salary",
                "amount": 100000,
                "currency": "USD",
                "effective_date": "2024-01-01",
            },
        )
        assert r.status_code == 403
        assert r.json()["detail"]["error_code"] == "outside_division_scope"

    async def test_manager_list_compensation_out_of_scope_blocked(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        manager_setup,
        out_of_scope_target,
    ):
        token = create_access_token(str(manager_setup["user"].id), str(tenant.id))
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.get(
            f"/api/employees/{out_of_scope_target.id}/compensation",
        )
        assert r.status_code == 403
        assert r.json()["detail"]["error_code"] == "outside_division_scope"
