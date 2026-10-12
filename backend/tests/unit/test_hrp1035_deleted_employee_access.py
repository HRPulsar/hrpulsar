"""HRP-1035: a deleted employee's account must not reach the tenant.

Deleting an Employee card used to leave the linked User active with no
Employee row for the status guards to judge, so the deleted employee kept
signing in. Deleting the card now deactivates the account and bumps its
token version, which closes every token path — password login, refresh,
magic login, the verification-link replay — and kills the tokens issued
before the delete.

The way back in is a new invitation (review follow-up): an active account
still blocks one with 409, a deactivated account does not — accepting it
reactivates the account under the password set in the form, with the old
tokens staying dead. Handing a deactivated account an employee card
directly is refused instead, since login would stay closed forever.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.core.security import (
    create_access_token,
    create_email_verification_token,
    create_magic_login_token,
)
from app.modules.auth import service as auth_service
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Invitation, Role, User, user_roles
from app.modules.auth.schemas import InvitationCreate
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import bare_request
from tests.unit.test_pdp_manager_visibility import (
    _get_or_create_role,
    _make_employee,
    _make_user_with_role,
)


async def _deleted_employee_user(
    db: AsyncSession, auth_client: AsyncClient, tenant
) -> User:
    """A user whose Employee card an admin has just deleted over HTTP."""
    role = await _get_or_create_role(db, "employee", "Employee")
    victim = await _make_user_with_role(db, tenant.id, role, prefix="gone")
    emp = await _make_employee(db, tenant.id, victim.id)
    resp = await auth_client.delete(f"/api/employees/{emp.id}")
    assert resp.status_code == 200, resp.text
    await db.refresh(victim)
    return victim


class TestDeletedEmployeeLockedOut:
    async def test_delete_deactivates_the_account(
        self, db: AsyncSession, auth_client: AsyncClient, tenant
    ) -> None:
        victim = await _deleted_employee_user(db, auth_client, tenant)
        assert victim.is_active is False
        assert victim.token_version >= 1

    async def test_password_login_refused(
        self, db: AsyncSession, auth_client: AsyncClient, tenant
    ) -> None:
        victim = await _deleted_employee_user(db, auth_client, tenant)
        with pytest.raises(HTTPException) as excinfo:
            await auth_service.login(db, victim.email, "testpass123")
        assert excinfo.value.status_code == 403
        assert excinfo.value.code == "account_deactivated"

    async def test_pre_issued_access_token_refused(
        self, db: AsyncSession, auth_client: AsyncClient, tenant
    ) -> None:
        role = await _get_or_create_role(db, "employee", "Employee")
        victim = await _make_user_with_role(db, tenant.id, role, prefix="gone")
        emp = await _make_employee(db, tenant.id, victim.id)
        token = create_access_token(str(victim.id), str(tenant.id))
        # Sanity: the token works while the employee exists.
        loaded = await get_current_user(bare_request(), token=token, db=db)
        assert loaded.id == victim.id

        resp = await auth_client.delete(f"/api/employees/{emp.id}")
        assert resp.status_code == 200, resp.text
        db.expire_all()
        with pytest.raises(HTTPException) as excinfo:
            await get_current_user(bare_request(), token=token, db=db)
        assert excinfo.value.status_code == 401

    async def test_refresh_refused_for_old_and_current_version(
        self, db: AsyncSession, auth_client: AsyncClient, tenant
    ) -> None:
        victim = await _deleted_employee_user(db, auth_client, tenant)
        # A refresh token minted before the delete carries the old version…
        with pytest.raises(HTTPException) as excinfo:
            await auth_service.refresh_tokens(db, victim.id, token_version=0)
        assert excinfo.value.status_code == 401
        # …and even the current version dies on the deactivated account.
        with pytest.raises(HTTPException) as excinfo:
            await auth_service.refresh_tokens(
                db, victim.id, token_version=victim.token_version
            )
        assert excinfo.value.status_code == 401

    async def test_magic_login_refused(
        self, db: AsyncSession, auth_client: AsyncClient, tenant
    ) -> None:
        victim = await _deleted_employee_user(db, auth_client, tenant)
        token = create_magic_login_token(str(victim.id), str(tenant.id))
        with pytest.raises(HTTPException) as excinfo:
            await auth_service.magic_login(db, token)
        assert excinfo.value.status_code == 401
        assert excinfo.value.code == "account_not_available"

    async def test_verification_link_replay_refused(
        self, db: AsyncSession, auth_client: AsyncClient, tenant
    ) -> None:
        # The "already verified" branch of verify_email handed tokens back
        # with no account check at all.
        victim = await _deleted_employee_user(db, auth_client, tenant)
        token = create_email_verification_token(str(victim.id))
        with pytest.raises(HTTPException) as excinfo:
            await auth_service.verify_email(db, token)
        assert excinfo.value.status_code == 403
        assert excinfo.value.code == "account_deactivated"

    async def test_invitation_to_an_active_account_still_409(
        self,
        db: AsyncSession,
        client: AsyncClient,
        tenant,
        user,
    ) -> None:
        role = await _get_or_create_role(db, "employee", "Employee")
        live = await _make_user_with_role(db, tenant.id, role, prefix="live")
        # Creating one is refused outright…
        with pytest.raises(HTTPException) as excinfo:
            await auth_service.create_invitation(
                db,
                tenant.id,
                user.id,
                InvitationCreate(email=live.email, name="Live User"),
                inviter_role_codes=["admin"],
            )
        assert excinfo.value.status_code == 409
        assert excinfo.value.code == "user_email_already_exists"
        # …and a pending one slipped in directly mints no session either.
        inv = Invitation(
            tenant_id=tenant.id,
            email=live.email,
            name="Live User",
            token=uuid.uuid4().hex,
            role_code="employee",
            invited_by=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.add(inv)
        await db.commit()
        resp = await client.post(
            "/api/auth/accept-invite",
            json={
                "token": inv.token,
                "password": "newpass12345",
                "first_name": "Live",
                "last_name": "User",
            },
        )
        assert resp.status_code == 409, resp.text
        assert "access_token" not in resp.json()


class TestReHireViaInvitation:
    """Review follow-up on HRP-1035: deactivation must not be a one-way
    street. A new invitation to the deleted employee's address is the
    re-hire path — accepting it reactivates the account."""

    async def test_reinvite_reactivates_the_deleted_employee(
        self,
        db: AsyncSession,
        client: AsyncClient,
        auth_client: AsyncClient,
        tenant,
        user,
    ) -> None:
        victim = await _deleted_employee_user(db, auth_client, tenant)
        # A token shaped like the previous employment's (version 0).
        old_token = create_access_token(str(victim.id), str(tenant.id))

        await auth_service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(email=victim.email, name="Gone User"),
            inviter_role_codes=["admin"],
        )
        inv_token = await db.scalar(
            select(Invitation.token).where(
                Invitation.email == victim.email,
                Invitation.tenant_id == tenant.id,
            )
        )
        resp = await client.post(
            "/api/auth/accept-invite",
            json={
                "token": inv_token,
                "password": "rehired12345",
                "first_name": "Back",
                "last_name": "Again",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]

        db.expire_all()
        await db.refresh(victim)
        assert victim.is_active is True
        assert victim.first_name == "Back"

        # The fresh password signs in; the old employment's token stays dead.
        tokens = await auth_service.login(db, victim.email, "rehired12345")
        assert tokens["access_token"]
        with pytest.raises(HTTPException) as excinfo:
            await get_current_user(bare_request(), token=old_token, db=db)
        assert excinfo.value.status_code == 401

    async def test_rehire_does_not_restore_the_old_admin_role(
        self,
        db: AsyncSession,
        client: AsyncClient,
        auth_client: AsyncClient,
        tenant,
        user,
    ) -> None:
        # The deleted employee held admin in their previous employment; the
        # re-hire grants exactly what the invitation says — employee — and
        # must not resurrect the old authority.
        admin_role = await _get_or_create_role(db, "admin", "Admin")
        await _get_or_create_role(db, "employee", "Employee")
        victim = await _make_user_with_role(db, tenant.id, admin_role, prefix="exadm")
        emp = await _make_employee(db, tenant.id, victim.id)
        resp = await auth_client.delete(f"/api/employees/{emp.id}")
        assert resp.status_code == 200, resp.text

        await auth_service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(email=victim.email, name="Ex Admin"),
            inviter_role_codes=["admin"],
        )
        inv_token = await db.scalar(
            select(Invitation.token).where(
                Invitation.email == victim.email,
                Invitation.tenant_id == tenant.id,
            )
        )
        resp = await client.post(
            "/api/auth/accept-invite",
            json={
                "token": inv_token,
                "password": "rehired12345",
                "first_name": "Ex",
                "last_name": "Admin",
            },
        )
        assert resp.status_code == 200, resp.text
        access = resp.json()["access_token"]
        victim_id = victim.id

        db.expire_all()
        codes = set(
            (
                await db.execute(
                    select(Role.code)
                    .join(user_roles, user_roles.c.role_id == Role.id)
                    .where(user_roles.c.user_id == victim_id)
                )
            )
            .scalars()
            .all()
        )
        assert codes == {"employee"}

        # The old authority is gone: an admin-only route answers 403.
        resp = await client.delete(
            f"/api/employees/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 403, resp.text

    async def test_create_employee_refuses_a_deactivated_account(
        self, db: AsyncSession, auth_client: AsyncClient, tenant
    ) -> None:
        victim = await _deleted_employee_user(db, auth_client, tenant)
        resp = await auth_client.post(
            "/api/employees",
            json={"user_id": str(victim.id), "hire_date": "2026-01-01"},
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] == "user_account_deactivated"


class TestVerifyLinkBlockedStatuses:
    async def test_terminated_employee_verification_link_refused(
        self, db: AsyncSession, tenant
    ) -> None:
        # The same verify_email hole, for the statuses that block login:
        # the guard mirrors magic_login's assert_employee_active.
        role = await _get_or_create_role(db, "employee", "Employee")
        leaver = await _make_user_with_role(db, tenant.id, role, prefix="term")
        emp = await _make_employee(db, tenant.id, leaver.id)
        emp.status = "terminated"
        await db.commit()
        token = create_email_verification_token(str(leaver.id))
        with pytest.raises(HTTPException) as excinfo:
            await auth_service.verify_email(db, token)
        assert excinfo.value.status_code == 401
        assert excinfo.value.detail["error_code"] == "employee_status_blocked"
