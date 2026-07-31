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
        assert len(resp.json()) == 1

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
