"""EMP3 — Invitations cannot grant a role above the inviter's level."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from app.modules.auth import service as auth_service
from app.modules.auth.models import Role
from app.modules.auth.schemas import InvitationCreate
from app.modules.company.models import Division
from fastapi import HTTPException
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


def _payload(role_code: str, division_id: uuid.UUID | None = None) -> InvitationCreate:
    return InvitationCreate(
        email=f"i-{uuid.uuid4().hex[:8]}@test.com",
        name="Invitee",
        role_code=role_code,
        division_id=division_id,
    )


async def _make_division(db: AsyncSession, tenant_id: uuid.UUID) -> Division:
    """HRP-195: manager invitations require a division; helper to create one."""
    div = Division(
        tenant_id=tenant_id,
        name=f"Div-{uuid.uuid4().hex[:6]}",
    )
    db.add(div)
    await db.commit()
    await db.refresh(div)
    return div


class TestRoleHierarchy:
    async def test_admin_invites_manager_ok(
        self, db: AsyncSession, tenant, user, manager_role, employee_role
    ):
        div = await _make_division(db, tenant.id)
        result = await auth_service.create_invitation(
            db,
            tenant.id,
            user.id,
            _payload("manager", division_id=div.id),
            inviter_role_codes=["admin"],
        )
        assert result["role_code"] == "manager"

    async def test_admin_invites_employee_ok(
        self, db: AsyncSession, tenant, user, employee_role
    ):
        result = await auth_service.create_invitation(
            db,
            tenant.id,
            user.id,
            _payload("employee"),
            inviter_role_codes=["admin"],
        )
        assert result["role_code"] == "employee"

    async def test_admin_invites_platform_admin_forbidden(
        self,
        db: AsyncSession,
        tenant,
        user,
        platform_admin_role,
    ):
        with pytest.raises(HTTPException) as exc:
            await auth_service.create_invitation(
                db,
                tenant.id,
                user.id,
                _payload("platform_admin"),
                inviter_role_codes=["admin"],
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "role_above_inviter"

    async def test_manager_invites_employee_ok(
        self, db: AsyncSession, tenant, user, employee_role
    ):
        result = await auth_service.create_invitation(
            db,
            tenant.id,
            user.id,
            _payload("employee"),
            inviter_role_codes=["manager"],
        )
        assert result["role_code"] == "employee"

    async def test_manager_invites_manager_forbidden(
        self, db: AsyncSession, tenant, user, manager_role
    ):
        with pytest.raises(HTTPException) as exc:
            await auth_service.create_invitation(
                db,
                tenant.id,
                user.id,
                _payload("manager"),
                inviter_role_codes=["manager"],
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "role_above_inviter"

    async def test_manager_invites_admin_forbidden(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        with pytest.raises(HTTPException) as exc:
            await auth_service.create_invitation(
                db,
                tenant.id,
                user.id,
                _payload("admin"),
                inviter_role_codes=["manager"],
            )
        assert exc.value.status_code == 403

    async def test_employee_cannot_invite(
        self, db: AsyncSession, tenant, user, employee_role
    ):
        with pytest.raises(HTTPException) as exc:
            await auth_service.create_invitation(
                db,
                tenant.id,
                user.id,
                _payload("employee"),
                inviter_role_codes=["employee"],
            )
        assert exc.value.status_code == 403

    # NOTE: the "platform_admin invites anything" case moved to
    # tests/unit/ee/test_rbac_extension.py — the platform-admin invite tier
    # is provided by the enterprise RBAC extension (review [21]), so the
    # behaviour does not exist in community builds.
