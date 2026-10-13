"""HRP-436 / HRP-831: endpoint RBAC for the invitation registry.

HRP-436 made the registry (list, edit, cancel, resend) admin-only while
creation stayed on the inviter hierarchy. HRP-831 put the section on the
tenant's matrix: ``view`` reads the registry, ``manage`` runs it, and below
the admin level both are the caller's subtree - an invitation with no
division is outside it, so a manager sends into a division they head or
not at all. The inviter hierarchy still decides which role goes out, and
changing the role of a sent invitation stays the admin level's.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from app.core import rbac_hooks
from app.core.security import create_access_token, hash_password
from app.modules.auth import service
from app.modules.auth.models import Role, User, user_roles
from app.modules.auth.schemas import InvitationCreate
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _system_role(db: AsyncSession, code: str, name: str) -> Role:
    result = await db.execute(
        select(Role).where(Role.code == code, Role.is_system.is_(True))
    )
    # ``.first()``: the shared test DB accumulates duplicate system roles from
    # other modules, which makes ``scalar_one_or_none`` order-dependent.
    role = result.scalars().first()
    if not role:
        role = Role(name=name, code=code, is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


@pytest_asyncio.fixture
async def manager_role(db: AsyncSession) -> Role:
    return await _system_role(db, "manager", "Manager")


@pytest_asyncio.fixture
async def employee_role(db: AsyncSession) -> Role:
    return await _system_role(db, "employee", "Employee")


@pytest_asyncio.fixture
async def hr_role(db: AsyncSession) -> Role:
    return await _system_role(db, "hr", "HR")


async def _user_with_role(db: AsyncSession, tenant, role: Role, *, label: str) -> User:
    u = User(
        email=f"{label}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name=label.title(),
        last_name="User",
        tenant_id=tenant.id,
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


async def _headed_division(db: AsyncSession, tenant, head: User) -> Division:
    """A division ``head`` manages - the subtree a manager invites into."""
    emp = Employee(user_id=head.id, tenant_id=tenant.id, hire_date=date(2024, 1, 1))
    db.add(emp)
    await db.commit()
    division = Division(tenant_id=tenant.id, name=f"Headed {uuid.uuid4().hex[:4]}", manager_id=emp.id)
    db.add(division)
    await db.commit()
    await db.refresh(division)
    return division


def _as(client: AsyncClient, user: User, tenant) -> AsyncClient:
    client.headers["Authorization"] = (
        f"Bearer {create_access_token(str(user.id), str(tenant.id))}"
    )
    return client


async def _pending(db, tenant, user, division_id=None, role="admin") -> dict:
    return await service.create_invitation(
        db,
        tenant.id,
        user.id,
        InvitationCreate(
            email=f"target-{uuid.uuid4().hex[:6]}@test.com",
            name="Target Person",
            # ``admin`` because every caller already seeds the admin_role
            # fixture - and since HRP-831 because a role above the caller's
            # tier is exactly what the registry refuses to touch.
            role_code=role,
            division_id=division_id,
        ),
    )


def _code(resp) -> str:
    body = resp.json()
    return body.get("code") or body.get("error_code") or body.get("detail", {}).get("error_code", "")


# The full registry surface behind the Admin section. Each entry is
# (method, path template, json body) — the id is filled per test.
REGISTRY_ENDPOINTS = [
    ("get", "/api/invitations", None),
    ("patch", "/api/invitations/{id}", {"role_code": "employee"}),
    ("patch", "/api/invitations/{id}/email", {"email": "moved@test.com"}),
    ("post", "/api/invitations/{id}/cancel", None),
    ("post", "/api/invitations/{id}/resend", None),
]

async def _call(c: AsyncClient, method: str, path: str, body: dict | None, inv_id: str):
    url = path.format(id=inv_id)
    return await getattr(c, method)(url, json=body) if body else await getattr(c, method)(url)


class TestInvitationRegistryFollowsTheSection:
    """The {manager, employee, hr} x {every registry endpoint} matrix.

    Before HRP-436 manager reached list/cancel/resend/patch and hr reached
    patch; employee was refused but the UI swallowed the 403 into an empty
    table. Since HRP-831 the matrix decides: ``employee`` holds nothing,
    ``manager`` holds ``manage`` in their subtree and ``hr`` at the admin
    level - the whole registry short of the role change.
    """

    @pytest.mark.parametrize("method,path,body", REGISTRY_ENDPOINTS)
    async def test_employee_is_refused_by_the_section(
        self, client: AsyncClient, db: AsyncSession, user, tenant, admin_role, method, path, body
    ):
        inv = await _pending(db, tenant, user)
        caller = await _user_with_role(db, tenant, await _system_role(db, "employee", "Employee"), label="employee")
        resp = await _call(_as(client, caller, tenant), method, path, body, inv["id"])
        assert resp.status_code == 403 and _code(resp) == "auth_insufficient_permissions", resp.text

    @pytest.mark.parametrize("method,path,body", REGISTRY_ENDPOINTS[1:])
    async def test_manager_reaches_nothing_outside_the_subtree(
        self, client: AsyncClient, db: AsyncSession, user, tenant, admin_role, manager_role, method, path, body
    ):
        # No division on the invitation: nobody's subtree holds it.
        inv = await _pending(db, tenant, user)
        mgr = await _user_with_role(db, tenant, manager_role, label="mgr")
        await _headed_division(db, tenant, mgr)
        resp = await _call(_as(client, mgr, tenant), method, path, body, inv["id"])
        assert resp.status_code == 403 and _code(resp) == "outside_division_scope", resp.text

    async def test_manager_lists_and_runs_only_the_subtree(
        self, client: AsyncClient, db: AsyncSession, user, tenant, admin_role, manager_role
    ):
        mgr = await _user_with_role(db, tenant, manager_role, label="mgr")
        mine = await _headed_division(db, tenant, mgr)
        theirs = Division(tenant_id=tenant.id, name="Theirs")
        db.add(theirs)
        await db.commit()
        await _system_role(db, "employee", "Employee")
        inside = await _pending(db, tenant, user, mine.id, role="employee")
        outside = await _pending(db, tenant, user, theirs.id, role="employee")
        above = await _pending(db, tenant, user, mine.id)  # admin, in the subtree
        await _pending(db, tenant, user)

        c = _as(client, mgr, tenant)
        listed = await c.get("/api/invitations")
        assert listed.status_code == 200, listed.text
        assert {i["id"] for i in listed.json()["items"]} == {str(inside["id"]), str(above["id"])}
        assert listed.json()["total"] == 2
        moved = await c.patch(f"/api/invitations/{inside['id']}", json={"division_id": str(theirs.id)})
        assert moved.status_code == 403 and _code(moved) == "outside_division_scope"
        assert (await c.post(f"/api/invitations/{outside['id']}/cancel")).status_code == 403
        # In the subtree but above the tier: seen, not touched (re-addressing
        # an admin invitation to oneself is minting an admin).
        for path in (f"/api/invitations/{above['id']}/cancel", f"/api/invitations/{above['id']}/resend"):
            refused = await c.post(path)
            assert refused.status_code == 403 and _code(refused) == "role_above_inviter", refused.text
        readdressed = await c.patch(f"/api/invitations/{above['id']}/email", json={"email": "me@test.com"})
        assert readdressed.status_code == 403 and _code(readdressed) == "role_above_inviter"
        assert (await c.post(f"/api/invitations/{inside['id']}/cancel")).status_code == 200

    async def test_hr_runs_the_registry_within_their_tier(
        self, client: AsyncClient, db: AsyncSession, user, tenant, admin_role, hr_role
    ):
        await _system_role(db, "employee", "Employee")
        admin_inv = await _pending(db, tenant, user)
        inv = await _pending(db, tenant, user, role="employee")
        hr = await _user_with_role(db, tenant, hr_role, label="hr")
        c = _as(client, hr, tenant)
        assert (await c.get("/api/invitations")).json()["total"] >= 2
        # An admin invitation is above hr's tier: listed, never re-addressed.
        for method, path, body in REGISTRY_ENDPOINTS[1:]:
            refused = await _call(c, method, path, body, admin_inv["id"])
            assert refused.status_code == 403 and _code(refused) == "role_above_inviter", f"{method} {path}"
        role = await c.patch(f"/api/invitations/{inv['id']}", json={"role_code": "employee"})
        assert role.status_code == 403 and _code(role) == "only_admins_can_change_invitation_role"
        assert (await c.patch(f"/api/invitations/{inv['id']}/email", json={"email": "moved@test.com"})).status_code == 200
        assert (await c.post(f"/api/invitations/{inv['id']}/resend")).status_code == 200
        assert (await c.post(f"/api/invitations/{inv['id']}/cancel")).status_code == 200

    async def test_admin_lists_invitations(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        access_token,
    ):
        await _pending(db, tenant, user)
        client.headers["Authorization"] = f"Bearer {access_token}"
        resp = await client.get("/api/invitations")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    async def test_admin_cancels_invitation(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        access_token,
    ):
        inv = await _pending(db, tenant, user)
        client.headers["Authorization"] = f"Bearer {access_token}"
        resp = await client.post(f"/api/invitations/{inv['id']}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"


class TestInvitationCreateStillFollowsHierarchy:
    """Guard the deliberate carve-out: tightening the registry must not take
    away a manager's ability to invite an employee - into a division they
    head (HRP-831): an invitation with no division is the admin level's.
    """

    async def test_manager_can_still_bulk_create_employee_invitations(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        admin_role,
        manager_role,
        employee_role,
    ):
        mgr = await _user_with_role(db, tenant, manager_role, label="mgr")
        mine = await _headed_division(db, tenant, mgr)
        resp = await _as(client, mgr, tenant).post(
            "/api/invitations/bulk",
            json={
                "invitations": [
                    {
                        "email": f"bulk-{uuid.uuid4().hex[:6]}@test.com",
                        "name": "Bulk Hire",
                        "role_code": "employee",
                        "division_id": str(mine.id),
                    },
                    {
                        "email": f"nowhere-{uuid.uuid4().hex[:6]}@test.com",
                        "name": "Nowhere Hire",
                        "role_code": "employee",
                    },
                ]
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert len(body["created"]) == 1
        assert [f["error_code"] for f in body["failed"]] == ["outside_division_scope"]

    async def test_manager_can_still_create_employee_invitation(
        self,
        client: AsyncClient,
        db: AsyncSession,
        tenant,
        admin_role,
        manager_role,
        employee_role,
    ):
        mgr = await _user_with_role(db, tenant, manager_role, label="mgr")
        mine = await _headed_division(db, tenant, mgr)
        payload = {"email": f"invitee-{uuid.uuid4().hex[:6]}@test.com", "name": "New Hire", "role_code": "employee"}
        c = _as(client, mgr, tenant)
        nowhere = await c.post("/api/invitations", json=payload)
        assert nowhere.status_code == 403 and _code(nowhere) == "outside_division_scope", nowhere.text
        resp = await c.post("/api/invitations", json={**payload, "division_id": str(mine.id)})
        assert resp.status_code == 201, resp.text

    async def test_admin_can_invite_recruiter(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
    ):
        """HRP-618: recruiter/hiring_manager exist in ``roles`` but were not
        grantable — every invite came back 403 ``role_above_inviter``."""
        await _system_role(db, "recruiter", "Recruiter")
        resp = await _as(client, user, tenant).post(
            "/api/invitations",
            json={
                "email": f"invitee-{uuid.uuid4().hex[:6]}@test.com",
                "name": "New Recruiter",
                "role_code": "recruiter",
            },
        )
        assert resp.status_code == 201

    async def test_manager_cannot_invite_recruiter(
        self, client: AsyncClient, db: AsyncSession, tenant, admin_role, manager_role
    ):
        await _system_role(db, "recruiter", "Recruiter")
        mgr = await _user_with_role(db, tenant, manager_role, label="mgr")
        mine = await _headed_division(db, tenant, mgr)
        resp = await _as(client, mgr, tenant).post(
            "/api/invitations",
            json={
                "email": f"invitee-{uuid.uuid4().hex[:6]}@test.com",
                "name": "New Recruiter",
                "role_code": "recruiter",
                "division_id": str(mine.id),
            },
        )
        assert resp.status_code == 403 and _code(resp) == "role_above_inviter", resp.text

    async def test_hr_cannot_invite_admin(
        self, client: AsyncClient, db: AsyncSession, tenant, admin_role
    ):
        """HRP-618: hr used to be able to mint admins — an escalation with
        no product reason behind it."""
        hr_role = await _system_role(db, "hr", "HR")
        hr = await _user_with_role(db, tenant, hr_role, label="hr")
        resp = await _as(client, hr, tenant).post(
            "/api/invitations",
            json={
                "email": f"invitee-{uuid.uuid4().hex[:6]}@test.com",
                "name": "New Admin",
                "role_code": "admin",
            },
        )
        assert resp.status_code == 403

    async def test_hr_can_invite_recruiter(
        self, client: AsyncClient, db: AsyncSession, tenant, admin_role
    ):
        hr_role = await _system_role(db, "hr", "HR")
        await _system_role(db, "recruiter", "Recruiter")
        hr = await _user_with_role(db, tenant, hr_role, label="hr")
        resp = await _as(client, hr, tenant).post(
            "/api/invitations",
            json={
                "email": f"invitee-{uuid.uuid4().hex[:6]}@test.com",
                "name": "New Recruiter",
                "role_code": "recruiter",
            },
        )
        assert resp.status_code == 201

    async def test_manager_still_cannot_invite_admin(
        self, client: AsyncClient, db: AsyncSession, tenant, admin_role, manager_role
    ):
        mgr = await _user_with_role(db, tenant, manager_role, label="mgr")
        mine = await _headed_division(db, tenant, mgr)
        resp = await _as(client, mgr, tenant).post(
            "/api/invitations",
            json={
                "email": f"invitee-{uuid.uuid4().hex[:6]}@test.com",
                "name": "New Admin",
                "role_code": "admin",
                "division_id": str(mine.id),
            },
        )
        assert resp.status_code == 403 and _code(resp) == "role_above_inviter", resp.text


class TestBulkInvitationReportsPerItemFailures:
    """HRP-593: the batch answers with per-address outcomes.

    The old response was a plain list of the invitations that made it, so a
    refused address left no trace at all — the caller could not tell a
    duplicate from a role refusal, or notice that anything was missing.
    """

    async def test_duplicate_address_lands_in_failed_with_its_code(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        employee_role,
        access_token,
    ):
        dup = f"dup-{uuid.uuid4().hex[:6]}@test.com"
        fresh = f"fresh-{uuid.uuid4().hex[:6]}@test.com"
        client.headers["Authorization"] = f"Bearer {access_token}"
        resp = await client.post(
            "/api/invitations/bulk",
            json={
                "invitations": [
                    {"email": dup, "name": "First", "role_code": "employee"},
                    {"email": dup, "name": "Again", "role_code": "employee"},
                    {"email": fresh, "name": "Third", "role_code": "employee"},
                ]
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert [inv["email"] for inv in body["created"]] == [dup, fresh]
        assert body["failed"] == [
            {"email": dup, "error_code": "pending_invitation_already_exists"}
        ]

    async def test_batch_with_nothing_created_still_answers_with_the_object(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        employee_role,
        access_token,
    ):
        # Every address refused: the caller still gets the same shape, with
        # the reasons in it, rather than an empty list and no explanation.
        taken = f"taken-{uuid.uuid4().hex[:6]}@test.com"
        client.headers["Authorization"] = f"Bearer {access_token}"
        first = await client.post(
            "/api/invitations",
            json={"email": taken, "name": "Taken", "role_code": "employee"},
        )
        assert first.status_code == 201

        resp = await client.post(
            "/api/invitations/bulk",
            json={
                "invitations": [
                    {"email": taken, "name": "Taken", "role_code": "employee"},
                    {
                        "email": f"nosuchrole-{uuid.uuid4().hex[:6]}@test.com",
                        "name": "Bad Role",
                        "role_code": "no_such_role",
                    },
                ]
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["created"] == []
        assert [f["error_code"] for f in body["failed"]] == [
            "pending_invitation_already_exists",
            "role_code_not_found",
        ]

    async def test_unexpected_error_on_one_address_keeps_the_batch_going(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        employee_role,
        access_token,
        monkeypatch,
    ):
        """HRP-833: the rollback after an unexpected error expired the
        signed-in user, and reading its tenant for the next address
        answered the whole batch with a 500."""
        broken = f"broken-{uuid.uuid4().hex[:6]}@test.com"
        fresh = f"fresh-{uuid.uuid4().hex[:6]}@test.com"
        create_invitation = service.create_invitation

        async def fail_on_broken(db, tenant_id, inviter_id, data, **kwargs):
            if data.email == broken:
                raise RuntimeError("database went away")
            return await create_invitation(db, tenant_id, inviter_id, data, **kwargs)

        monkeypatch.setattr(service, "create_invitation", fail_on_broken)
        client.headers["Authorization"] = f"Bearer {access_token}"
        resp = await client.post(
            "/api/invitations/bulk",
            json={
                "invitations": [
                    {"email": broken, "name": "Broken", "role_code": "employee"},
                    {"email": fresh, "name": "Fresh", "role_code": "employee"},
                ]
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert [inv["email"] for inv in body["created"]] == [fresh]
        assert body["failed"] == [
            {"email": broken, "error_code": "invitation_create_failed"}
        ]


class TestRoleChangeUsesRbacSeam:
    async def test_admin_equivalent_codes_widen_the_role_change(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        manager_role,
        monkeypatch,
    ):
        """The seam is resolved per request, so the enterprise edition can
        add its platform-level role without core naming it. Since HRP-831 it
        rules the one admin piece left on the registry - the role change."""
        await _system_role(db, "employee", "Employee")
        mgr = await _user_with_role(db, tenant, manager_role, label="mgr")
        mine = await _headed_division(db, tenant, mgr)
        inv = await _pending(db, tenant, user, mine.id, role="employee")
        c = _as(client, mgr, tenant)
        refused = await c.patch(f"/api/invitations/{inv['id']}", json={"role_code": "employee"})
        assert refused.status_code == 403 and _code(refused) == "only_admins_can_change_invitation_role"
        # ``require_admin`` itself still guards the employee card's role change.
        emp_id = (await db.execute(select(Employee.id).where(Employee.user_id == mgr.id))).scalar_one()
        assert (await c.put(f"/api/employees/{emp_id}/role", json={"role_code": "employee"})).status_code == 403

        monkeypatch.setattr(
            rbac_hooks,
            "admin_equivalent_codes",
            lambda: frozenset({"admin", "manager"}),
        )
        assert (await c.patch(f"/api/invitations/{inv['id']}", json={"role_code": "employee"})).status_code == 200
        # Past the guard the call is refused for what it is - one's own role.
        own = await c.put(f"/api/employees/{emp_id}/role", json={"role_code": "employee"})
        assert own.status_code == 422 and _code(own) == "cannot_change_own_role", own.text
