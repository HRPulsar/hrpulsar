"""HRP-436: endpoint RBAC for the invitation registry.

The Invitations page moved into the admin-only sidebar section, so the API that
backs it must refuse managers and employees instead of quietly answering with a
tenant-wide list (or, for employees, a 403 the UI used to swallow into an empty
table). Creating an invitation is deliberately *not* tightened here — that stays
on the inviter hierarchy so a manager can still invite an employee.
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from app.core import rbac_hooks
from app.core.security import create_access_token, hash_password
from app.modules.auth import service
from app.modules.auth.models import Role, User, user_roles
from app.modules.auth.schemas import InvitationCreate
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


def _as(client: AsyncClient, user: User, tenant) -> AsyncClient:
    client.headers["Authorization"] = (
        f"Bearer {create_access_token(str(user.id), str(tenant.id))}"
    )
    return client


async def _pending(db, tenant, user) -> dict:
    return await service.create_invitation(
        db,
        tenant.id,
        user.id,
        InvitationCreate(
            email=f"target-{uuid.uuid4().hex[:6]}@test.com",
            name="Target Person",
            # ``admin`` because every caller already seeds the admin_role
            # fixture; the invited role is irrelevant to these RBAC assertions.
            role_code="admin",
        ),
    )


# The full registry surface behind the Admin section. Each entry is
# (method, path template, json body) — the id is filled per test.
REGISTRY_ENDPOINTS = [
    ("get", "/api/invitations", None),
    ("patch", "/api/invitations/{id}", {"role_code": "employee"}),
    ("patch", "/api/invitations/{id}/email", {"email": "moved@test.com"}),
    ("post", "/api/invitations/{id}/cancel", None),
    ("post", "/api/invitations/{id}/resend", None),
]

NON_ADMIN_ROLES = ["manager", "employee", "hr"]


class TestInvitationRegistryIsAdminOnly:
    """The {manager, employee, hr} x {every registry endpoint} matrix.

    Before HRP-436 manager reached list/cancel/resend/patch and hr reached
    patch; employee was refused but the UI swallowed the 403 into an empty
    table.
    """

    @pytest.mark.parametrize("role_code", NON_ADMIN_ROLES)
    @pytest.mark.parametrize("method,path,body", REGISTRY_ENDPOINTS)
    async def test_non_admin_is_refused(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        role_code: str,
        method: str,
        path: str,
        body: dict | None,
    ):
        inv = await _pending(db, tenant, user)
        role = await _system_role(db, role_code, role_code.title())
        caller = await _user_with_role(db, tenant, role, label=role_code)

        c = _as(client, caller, tenant)
        url = path.format(id=inv["id"])
        resp = (
            await getattr(c, method)(url, json=body)
            if body
            else await getattr(c, method)(url)
        )

        assert resp.status_code == 403, f"{role_code} {method.upper()} {url}"

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
    away a manager's ability to invite an employee.

    Note this is an API-level capability — the product exposes no invite
    affordance to managers today (the Invitations page is admin-only and the
    Employees dialog gates its Invite link on admin).
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
        resp = await _as(client, mgr, tenant).post(
            "/api/invitations/bulk",
            json={
                "invitations": [
                    {
                        "email": f"bulk-{uuid.uuid4().hex[:6]}@test.com",
                        "name": "Bulk Hire",
                        "role_code": "employee",
                    }
                ]
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert len(body["created"]) == 1
        assert body["failed"] == []

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
        resp = await _as(client, mgr, tenant).post(
            "/api/invitations",
            json={
                "email": f"invitee-{uuid.uuid4().hex[:6]}@test.com",
                "name": "New Hire",
                "role_code": "employee",
            },
        )
        assert resp.status_code == 201

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
        resp = await _as(client, mgr, tenant).post(
            "/api/invitations",
            json={
                "email": f"invitee-{uuid.uuid4().hex[:6]}@test.com",
                "name": "New Recruiter",
                "role_code": "recruiter",
            },
        )
        assert resp.status_code == 403

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
        resp = await _as(client, mgr, tenant).post(
            "/api/invitations",
            json={
                "email": f"invitee-{uuid.uuid4().hex[:6]}@test.com",
                "name": "New Admin",
                "role_code": "admin",
            },
        )
        assert resp.status_code == 403


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


class TestRequireAdminUsesRbacSeam:
    async def test_admin_equivalent_codes_widen_access(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        manager_role,
        monkeypatch,
    ):
        """``require_admin`` resolves the seam per request, so the enterprise
        edition can add its platform-level role without core naming it."""
        await _pending(db, tenant, user)
        mgr = await _user_with_role(db, tenant, manager_role, label="mgr")
        c = _as(client, mgr, tenant)
        assert (await c.get("/api/invitations")).status_code == 403

        monkeypatch.setattr(
            rbac_hooks,
            "admin_equivalent_codes",
            lambda: frozenset({"admin", "manager"}),
        )
        assert (await c.get("/api/invitations")).status_code == 200
