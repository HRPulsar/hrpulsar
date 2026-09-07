"""EMP1: PUT /auth/me strict allowlist.

`UserUpdate` has `extra='forbid'` and only `first_name` / `last_name` /
`language` (i18n F0) are written by `update_profile`. Privileged fields
(status, role_code, is_active, email, tenant_id, id) must never be
settable through this endpoint. Sending them yields a 422.
"""

import uuid
from datetime import datetime, timezone

import pytest
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import Role, User, user_roles
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


class TestAuthMeAllowlist:
    async def test_put_me_allows_first_last_name(self, auth_client: AsyncClient):
        resp = await auth_client.put(
            "/api/auth/me",
            json={"first_name": "Renamed", "last_name": "Person"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["first_name"] == "Renamed"
        assert body["last_name"] == "Person"

    async def test_put_me_partial_update(self, auth_client: AsyncClient):
        resp = await auth_client.put(
            "/api/auth/me",
            json={"first_name": "OnlyFirst"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["first_name"] == "OnlyFirst"

    @pytest.mark.parametrize(
        "field,value",
        [
            ("is_active", False),
            ("email", "hacker@example.com"),
            ("tenant_id", "00000000-0000-0000-0000-000000000000"),
            ("id", "00000000-0000-0000-0000-000000000000"),
            ("role_code", "admin"),
            ("status", "active"),
            ("password_hash", "x"),
            ("avatar_file_id", "00000000-0000-0000-0000-000000000000"),
            # HRP-710: a read-only answer on the payload, never an input.
            ("can_view_job_profile", True),
            ("unknown_field", "anything"),
        ],
    )
    async def test_put_me_rejects_extra_field(
        self, auth_client: AsyncClient, field, value
    ):
        resp = await auth_client.put(
            "/api/auth/me",
            json={"first_name": "Ok", field: value},
        )
        assert resp.status_code == 422, (
            f"expected 422 for forbidden field {field!r}, got {resp.status_code}: "
            f"{resp.text}"
        )

    async def test_put_me_does_not_change_email_or_role(
        self, auth_client: AsyncClient, user
    ):
        original_email = user.email
        resp = await auth_client.put("/api/auth/me", json={"first_name": "Stays"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == original_email
        # role list is read from DB — sending a role_code can't insert one
        assert body["roles"] == ["admin"]


async def _user_with_role(db: AsyncSession, tenant, code: str) -> User:
    role = (await db.execute(select(Role).where(Role.code == code))).scalars().first()
    if role is None:
        role = Role(name=code.title(), code=code, is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    u = User(
        email=f"{code}-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name=code,
        last_name="X",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    # Re-read through the identity map, or ``get_me``'s selectinload keeps
    # the empty ``roles`` collection this object was loaded with.
    db.expunge(u)
    return (
        await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == u.id)
        )
    ).scalar_one()


async def _me(client: AsyncClient, u: User) -> dict:
    token = create_access_token(str(u.id), str(u.tenant_id))
    resp = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _set_show_grades(db: AsyncSession, tenant, value: bool) -> None:
    tenant.directory_show_grades = value
    await db.commit()


class TestAuthMeJobProfileAnswer:
    """HRP-710: /auth/me answers ``can_view_job_profile`` itself.

    The SPA used to rebuild it from the role list plus
    ``tenant_directory_show_grades`` — a hand-kept copy of
    ``access_scope.GRADE_ROLE_CODES``. These pin the two halves of the
    predicate as the payload now reports them.
    """

    async def test_employee_follows_the_tenant_switch(
        self, client: AsyncClient, db: AsyncSession, tenant
    ):
        u = await _user_with_role(db, tenant, "employee")
        await _set_show_grades(db, tenant, False)
        body = await _me(client, u)
        # Guards the fixture: a user with no role at all would answer the
        # same way and make the switch half of this vacuous.
        assert body["roles"] == ["employee"]
        assert body["can_view_job_profile"] is False
        await _set_show_grades(db, tenant, True)
        assert (await _me(client, u))["can_view_job_profile"] is True

    async def test_hr_reads_the_pair_with_the_switch_off(
        self, client: AsyncClient, db: AsyncSession, tenant
    ):
        u = await _user_with_role(db, tenant, "hr")
        await _set_show_grades(db, tenant, False)
        body = await _me(client, u)
        assert body["roles"] == ["hr"]
        assert body["can_view_job_profile"] is True
        # The switch itself stays on the payload — it is a public property
        # of the tenant and other surfaces read it.
        assert body["tenant_directory_show_grades"] is False
