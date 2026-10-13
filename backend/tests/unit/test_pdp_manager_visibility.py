"""HRP-142: division managers see PDP plans in ``draft`` status within
their division scope, alongside admins/HR/platform_admin. Regular
employees still don't.

This is a router-level test: the branch lives in
``backend/app/modules/assessment/router.list_pdps`` (it picks
``hide_drafts`` based on the caller's role).
"""

import uuid
from datetime import UTC, date, datetime

import pytest_asyncio
from app.core.security import create_access_token, hash_password
from app.modules.assessment import pdp_service
from app.modules.assessment.schemas import PDPCreate
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _get_or_create_role(db: AsyncSession, code: str, name: str) -> Role:
    result = await db.execute(
        select(Role).where(Role.code == code, Role.is_system.is_(True))
    )
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(name=name, code=code, is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


@pytest_asyncio.fixture
async def manager_role(db: AsyncSession) -> Role:
    return await _get_or_create_role(db, "manager", "Manager")


@pytest_asyncio.fixture
async def employee_role(db: AsyncSession) -> Role:
    return await _get_or_create_role(db, "employee", "Employee")


async def _make_user_with_role(
    db: AsyncSession, tenant_id: uuid.UUID, role: Role, *, prefix: str
) -> User:
    u = User(
        email=f"{prefix}-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name=prefix.capitalize(),
        last_name="User",
        tenant_id=tenant_id,
        email_verified_at=datetime.now(UTC),
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
    division_id: uuid.UUID | None = None,
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


def _auth_headers(user: User, tenant_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(str(user.id), str(tenant_id))
    return {"Authorization": f"Bearer {token}"}


class TestManagerSeesDraftPDPs:
    async def test_manager_sees_draft_in_own_division(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        manager_role: Role,
    ) -> None:
        # Manager owns Engineering; one employee sits inside it. A draft PDP
        # exists for that employee — the manager must see it (HRP-142).
        manager_user = await _make_user_with_role(
            db, tenant.id, manager_role, prefix="mgr"
        )
        manager_emp = await _make_employee(db, tenant.id, manager_user.id)
        division = Division(
            tenant_id=tenant.id, name="Engineering", manager_id=manager_emp.id
        )
        db.add(division)
        await db.commit()
        await db.refresh(division)
        # Re-link manager_emp to its own division (mirrors real signup).
        manager_emp.division_id = division.id
        await db.commit()

        report_user = await _make_user_with_role(
            db, tenant.id, manager_role, prefix="report"
        )
        report_emp = await _make_employee(
            db, tenant.id, report_user.id, division_id=division.id
        )

        draft = await pdp_service.create_pdp(
            db,
            tenant.id,
            manager_user.id,
            PDPCreate(title="Onboarding plan", employee_id=report_emp.id),
        )

        resp = await client.get(
            "/api/pdp", headers=_auth_headers(manager_user, tenant.id)
        )
        assert resp.status_code == 200, resp.text
        ids = {str(p["id"]) for p in resp.json()}
        assert str(draft["id"]) in ids

    async def test_manager_does_not_see_draft_outside_division(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        manager_role: Role,
    ) -> None:
        # HRP-142 scope invariant: opening drafts up to managers must NOT
        # break the visibility scope. A manager of Division A should not
        # see drafts authored for employees of an unrelated Division B.
        manager_a_user = await _make_user_with_role(
            db, tenant.id, manager_role, prefix="mgrA"
        )
        manager_a_emp = await _make_employee(db, tenant.id, manager_a_user.id)
        division_a = Division(
            tenant_id=tenant.id, name="Division A", manager_id=manager_a_emp.id
        )
        db.add(division_a)
        await db.commit()
        await db.refresh(division_a)
        manager_a_emp.division_id = division_a.id
        await db.commit()

        # Standalone division B with its own employee — manager A has no
        # reach into it.
        division_b = Division(tenant_id=tenant.id, name="Division B")
        db.add(division_b)
        await db.commit()
        await db.refresh(division_b)
        foreign_user = await _make_user_with_role(
            db, tenant.id, manager_role, prefix="foreign"
        )
        foreign_emp = await _make_employee(
            db, tenant.id, foreign_user.id, division_id=division_b.id
        )

        draft = await pdp_service.create_pdp(
            db,
            tenant.id,
            manager_a_user.id,
            PDPCreate(title="Other team's plan", employee_id=foreign_emp.id),
        )

        resp = await client.get(
            "/api/pdp", headers=_auth_headers(manager_a_user, tenant.id)
        )
        assert resp.status_code == 200, resp.text
        ids = {str(p["id"]) for p in resp.json()}
        assert str(draft["id"]) not in ids

    async def test_employee_does_not_see_draft(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        employee_role: Role,
    ) -> None:
        # A plain employee viewing their own list must still NOT see drafts —
        # those are authoring artefacts, not yet sent to them. Guards HRP-19.
        emp_user = await _make_user_with_role(
            db, tenant.id, employee_role, prefix="emp"
        )
        emp = await _make_employee(db, tenant.id, emp_user.id)

        draft = await pdp_service.create_pdp(
            db,
            tenant.id,
            emp_user.id,
            PDPCreate(title="Self plan", employee_id=emp.id),
        )

        resp = await client.get("/api/pdp", headers=_auth_headers(emp_user, tenant.id))
        assert resp.status_code == 200, resp.text
        ids = {str(p["id"]) for p in resp.json()}
        assert str(draft["id"]) not in ids


class TestEmployeeCannotAuthorTheirOwnPlan:
    """HRP-768: the "take a plan yourself" gate, pinned where it lives.

    Reported from the demo as a greyed-out button. It is not a bug: a
    development plan is authored and reviewed by an admin or a manager,
    and ``POST /pdp`` has always said so. The employee-side fix was to
    make the denial legible instead of rendering nothing at all — so the
    rule the tooltip now states has to keep being true, or the tooltip
    starts lying about a request that would succeed.
    """

    async def test_employee_post_pdp_is_denied(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        employee_role: Role,
    ) -> None:
        emp_user = await _make_user_with_role(
            db, tenant.id, employee_role, prefix="selfplan"
        )
        emp = await _make_employee(db, tenant.id, emp_user.id)

        resp = await client.post(
            "/api/pdp",
            json={"title": "My own plan", "employee_id": str(emp.id)},
            headers=_auth_headers(emp_user, tenant.id),
        )
        assert resp.status_code == 403, resp.text

    async def test_admin_post_pdp_is_allowed(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        employee_role: Role,
    ) -> None:
        """The other half of the claim: the tooltip names an administrator
        or the employee's manager as the people to ask, so one of them has
        to actually be able to. Admin, because a manager also answers to
        the division scope and that is a different rule."""
        admin_role = await _get_or_create_role(db, "admin", "Admin")
        admin_user = await _make_user_with_role(
            db, tenant.id, admin_role, prefix="admin-author"
        )
        emp_user = await _make_user_with_role(
            db, tenant.id, employee_role, prefix="admin-authored"
        )
        emp = await _make_employee(db, tenant.id, emp_user.id)

        resp = await client.post(
            "/api/pdp",
            json={"title": "Plan for a report", "employee_id": str(emp.id)},
            headers=_auth_headers(admin_user, tenant.id),
        )
        assert resp.status_code == 201, resp.text


class TestPDPDetailScope:
    """HRP-818: ``GET /pdp/{id}`` answers only inside the reading scope.

    ``GET /pdp`` was already trimmed through ``get_visible_employee_ids``,
    but the detail route filtered by tenant alone — any colleague could
    read any plan by id. The gate is ``pdp_status_scope``, the one
    ``/status``, ``/comments`` and ``/versions`` already sit behind, so
    the named reviewer keeps reading the plan they were named for. The
    item ``/pass`` route joins it: its service check refused a stranger,
    but answered ``409`` with the plan's status first.
    """

    async def test_stranger_is_refused_and_scoped_readers_pass(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        manager_role: Role,
        employee_role: Role,
    ) -> None:
        manager_user = await _make_user_with_role(
            db, tenant.id, manager_role, prefix="mgr"
        )
        manager_emp = await _make_employee(db, tenant.id, manager_user.id)
        division = Division(
            tenant_id=tenant.id, name="Engineering", manager_id=manager_emp.id
        )
        db.add(division)
        await db.commit()
        await db.refresh(division)
        manager_emp.division_id = division.id
        await db.commit()

        report_user = await _make_user_with_role(
            db, tenant.id, employee_role, prefix="report"
        )
        report_emp = await _make_employee(
            db, tenant.id, report_user.id, division_id=division.id
        )
        # No Employee row: the reviewer's visible set is empty, so only the
        # ``reviewer_id`` clause can let them in.
        reviewer_user = await _make_user_with_role(
            db, tenant.id, employee_role, prefix="reviewer"
        )
        stranger_user = await _make_user_with_role(
            db, tenant.id, employee_role, prefix="stranger"
        )
        await _make_employee(db, tenant.id, stranger_user.id)

        plan = await pdp_service.create_pdp(
            db,
            tenant.id,
            manager_user.id,
            PDPCreate(
                title="Plan", employee_id=report_emp.id, reviewer_id=reviewer_user.id
            ),
        )
        url = f"/api/pdp/{plan['id']}"
        stranger = _auth_headers(stranger_user, tenant.id)

        resp = await client.get(url, headers=stranger)
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["error_code"] == "outside_division_scope"
        resp = await client.post(f"{url}/items/{uuid.uuid4()}/pass", headers=stranger)
        assert resp.status_code == 403, resp.text

        for reader in (report_user, manager_user, reviewer_user):
            resp = await client.get(url, headers=_auth_headers(reader, tenant.id))
            assert resp.status_code == 200, (reader.email, resp.text)
        # Past the gate the service speaks: a draft cannot be ticked (409),
        # which is the answer the reviewer always got — not the new 403.
        resp = await client.post(
            f"{url}/items/{uuid.uuid4()}/pass",
            headers=_auth_headers(reviewer_user, tenant.id),
        )
        assert resp.status_code == 409, resp.text
