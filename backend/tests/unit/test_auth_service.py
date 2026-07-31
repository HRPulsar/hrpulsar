import uuid
from datetime import datetime, timezone

import pytest
from app.config import settings
from app.core.security import (
    create_access_token,
    create_demo_access_token,
    create_email_verification_token,
    create_refresh_token,
    create_reset_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.modules.auth import service
from app.modules.auth.models import Role, User, user_roles
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    RegisterRequest,
    UserUpdate,
)
from app.modules.company.models import Tenant
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(autouse=True)
def _pin_classic_email_flow(monkeypatch):
    """HRP-390: ``register()`` auto-verifies on onprem installs without an
    email provider. This module exercises the classic pending-verification
    path, so pin a configured provider (with delivery stubbed to succeed)
    regardless of the developer's local ``.env``. Self-serve fallback
    coverage lives in ``test_auth_register_selfserve.py``."""
    monkeypatch.setattr("app.core.email.email_provider_configured", lambda: True)
    monkeypatch.setattr(
        "app.modules.auth.service.send_verification_email", lambda *a, **k: True
    )


# --- Security helpers ---


class TestPasswordHashing:
    def test_hash_and_verify(self):
        plain = "mypassword123"
        hashed = hash_password(plain)
        assert hashed != plain
        assert verify_password(plain, hashed)

    def test_wrong_password(self):
        hashed = hash_password("correct")
        assert not verify_password("wrong", hashed)


class TestJWT:
    def test_access_token_roundtrip(self):
        uid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        token = create_access_token(uid, tid)
        payload = decode_token(token)
        assert payload["sub"] == uid
        assert payload["tenant_id"] == tid
        assert payload["type"] == "access"

    def test_refresh_token_roundtrip(self):
        uid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        token = create_refresh_token(uid, tid)
        payload = decode_token(token)
        assert payload["type"] == "refresh"

    def test_reset_token_roundtrip(self):
        uid = str(uuid.uuid4())
        token = create_reset_token(uid)
        payload = decode_token(token)
        assert payload["type"] == "reset"
        assert payload["sub"] == uid

    def test_email_verification_token_roundtrip(self):
        uid = str(uuid.uuid4())
        token = create_email_verification_token(uid)
        payload = decode_token(token)
        assert payload["type"] == "email_verify"
        assert payload["sub"] == uid

    def test_demo_access_token_ttl_tracks_demo_session_setting(self):
        # The demo access token shares its TTL with the tenant's
        # ``demo_session_ttl_seconds`` so the JWT cannot expire before
        # the tenant — that contract is what keeps demo visitors from
        # getting bounced to /login mid-session.
        uid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        before = datetime.now(timezone.utc).timestamp()
        token = create_demo_access_token(uid, tid)
        after = datetime.now(timezone.utc).timestamp()

        payload = decode_token(token)
        assert payload["type"] == "access"
        assert payload["sub"] == uid
        assert payload["tenant_id"] == tid

        ttl = settings.demo_session_ttl_seconds
        assert before + ttl - 5 <= payload["exp"] <= after + ttl + 5
        # Long-lived by construction — must outlast a regular access
        # token even if someone bumps the regular setting.
        assert ttl > settings.access_token_expire_minutes * 60


# --- Auth service ---


class TestRegister:
    async def test_register_returns_pending_verification(
        self, db: AsyncSession, admin_role
    ):
        email = f"new-{uuid.uuid4().hex[:6]}@example.com"
        data = RegisterRequest(
            email=email,
            password="password123",
            first_name="New",
            last_name="User",
            company_name="New Corp",
        )
        resp = await service.register(db, data)
        assert resp["pending_verification"] is True
        assert resp["auto_verified"] is False
        assert resp["email"] == email
        assert "access_token" not in resp

    async def test_register_duplicate_email_fails(self, db: AsyncSession, admin_role):
        email = f"dup-{uuid.uuid4().hex[:6]}@example.com"
        data = RegisterRequest(
            email=email,
            password="password123",
            first_name="A",
            last_name="B",
            company_name="Corp",
        )
        await service.register(db, data)

        with pytest.raises(Exception) as exc:
            await service.register(db, data)
        assert (
            "409" in str(exc.value.status_code)
            or "already" in str(exc.value.detail).lower()
        )


class TestEmailVerification:
    async def test_verify_email_success(self, db: AsyncSession, admin_role):
        from app.core.security import create_email_verification_token

        # Register a user (unverified)
        email = f"verify-{uuid.uuid4().hex[:6]}@example.com"
        data = RegisterRequest(
            email=email,
            password="password123",
            first_name="V",
            last_name="U",
            company_name="VerifyCorp",
        )
        await service.register(db, data)

        # Find the user
        from sqlalchemy import select

        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        assert user.email_verified_at is None

        # Verify
        token = create_email_verification_token(str(user.id))
        resp = await service.verify_email(db, token)
        assert "access_token" in resp
        assert "refresh_token" in resp
        assert resp["user"]["email"] == email

        # Check user is now verified
        await db.refresh(user)
        assert user.email_verified_at is not None

    async def test_verify_email_invalid_token(self, db: AsyncSession):
        with pytest.raises(HTTPException) as exc:
            await service.verify_email(db, "invalid.token.value")
        assert exc.value.status_code == 400

    async def test_verify_email_wrong_type_token(self, db: AsyncSession, user):
        """An access token should not work as a verification token."""
        access = create_access_token(str(user.id), str(user.tenant_id))
        with pytest.raises(HTTPException) as exc:
            await service.verify_email(db, access)
        assert exc.value.status_code == 400

    async def test_verify_email_already_verified(self, db: AsyncSession, user):
        """Re-verifying an already verified user should succeed and return tokens."""
        from app.core.security import create_email_verification_token

        token = create_email_verification_token(str(user.id))
        resp = await service.verify_email(db, token)
        assert "access_token" in resp

    async def test_resend_verification_unverified_user(
        self, db: AsyncSession, admin_role
    ):
        email = f"resend-{uuid.uuid4().hex[:6]}@example.com"
        data = RegisterRequest(
            email=email,
            password="password123",
            first_name="R",
            last_name="U",
            company_name="ResendCorp",
        )
        await service.register(db, data)
        # Should not raise
        await service.resend_verification(db, email)

    async def test_resend_verification_nonexistent_email(self, db: AsyncSession):
        # Should not raise (prevent email enumeration)
        await service.resend_verification(db, "nobody@nowhere.com")


class TestLogin:
    async def test_login_success(self, db: AsyncSession, user, tenant):
        resp = await service.login(db, user.email, "testpass123")
        assert "access_token" in resp
        assert "refresh_token" in resp

    async def test_login_wrong_password(self, db: AsyncSession, user, tenant):
        with pytest.raises(Exception) as exc:
            await service.login(db, user.email, "wrongpassword")
        assert "401" in str(exc.value.status_code)

    async def test_login_nonexistent_email(self, db: AsyncSession):
        with pytest.raises(Exception) as exc:
            await service.login(db, "nobody@example.com", "password")
        assert "401" in str(exc.value.status_code)

    async def test_login_unverified_email(self, db: AsyncSession, tenant, admin_role):
        """Unverified users cannot log in (403)."""
        unverified = User(
            email=f"unverified-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("testpass123"),
            first_name="Unverified",
            last_name="User",
            tenant_id=tenant.id,
            email_verified_at=None,
        )
        db.add(unverified)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.login(db, unverified.email, "testpass123")
        assert exc.value.status_code == 403
        assert "not verified" in exc.value.detail.lower()


class TestRefreshTokens:
    async def test_refresh_returns_new_tokens(self, db: AsyncSession, user):
        resp = await service.refresh_tokens(db, user.id)
        assert "access_token" in resp
        assert "refresh_token" in resp

    async def test_refresh_nonexistent_user(self, db: AsyncSession):
        with pytest.raises(HTTPException):
            await service.refresh_tokens(db, uuid.uuid4())


class TestUpdateProfile:
    async def test_update_name(self, db: AsyncSession, user):
        data = UserUpdate(first_name="Updated", last_name="Name")
        result = await service.update_profile(db, user.id, data)
        assert result["first_name"] == "Updated"
        assert result["last_name"] == "Name"

    async def test_partial_update(self, db: AsyncSession, user):
        data = UserUpdate(first_name="OnlyFirst")
        result = await service.update_profile(db, user.id, data)
        assert result["first_name"] == "OnlyFirst"
        assert result["last_name"] == user.last_name


class TestChangePassword:
    async def test_change_password_success(self, db: AsyncSession, user):
        data = ChangePasswordRequest(
            current_password="testpass123", new_password="newpass123"
        )
        await service.change_password(db, user.id, data)

        # Verify new password works
        updated = await db.get(User, user.id)
        assert verify_password("newpass123", updated.password_hash)

    async def test_change_password_wrong_current(self, db: AsyncSession, user):
        data = ChangePasswordRequest(
            current_password="wrong", new_password="newpass123"
        )
        with pytest.raises(Exception) as exc:
            await service.change_password(db, user.id, data)
        assert "400" in str(exc.value.status_code)


class TestRoles:
    async def test_list_roles(self, db: AsyncSession, tenant, admin_role):
        roles = await service.list_roles(db, tenant.id)
        assert len(roles) >= 1
        codes = [r.code for r in roles]
        assert "admin" in codes

    async def test_create_custom_role(self, db: AsyncSession, tenant):
        from app.modules.auth.schemas import RoleCreate

        data = RoleCreate(
            name="Viewer",
            code=f"viewer-{uuid.uuid4().hex[:6]}",
            description="Read-only",
        )
        role = await service.create_role(db, tenant.id, data)
        assert role.name == "Viewer"
        assert not role.is_system


# --- Login edge cases ---


class TestLoginInactiveUser:
    async def test_login_inactive_user(self, db: AsyncSession, tenant, admin_role):
        """Deactivated users cannot log in (403)."""
        inactive = User(
            email=f"inactive-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("testpass123"),
            first_name="Inactive",
            last_name="User",
            tenant_id=tenant.id,
            is_active=False,
        )
        db.add(inactive)
        await db.commit()

        with pytest.raises(Exception) as exc:
            await service.login(db, inactive.email, "testpass123")
        assert "403" in str(exc.value.status_code)


# --- get_me edge cases ---


class TestGetMe:
    async def test_get_me_success(self, db: AsyncSession, user):
        result = await service.get_me(db, user.id)
        assert result["email"] == user.email
        assert "roles" in result

    async def test_get_me_not_found(self, db: AsyncSession):
        with pytest.raises(Exception) as exc:
            await service.get_me(db, uuid.uuid4())
        assert "404" in str(exc.value.status_code)


# --- update_profile edge cases ---


class TestUpdateProfileEdgeCases:
    async def test_update_profile_not_found(self, db: AsyncSession):
        data = UserUpdate(first_name="Ghost")
        with pytest.raises(Exception) as exc:
            await service.update_profile(db, uuid.uuid4(), data)
        assert "404" in str(exc.value.status_code)


# --- change_password edge cases ---


class TestChangePasswordEdgeCases:
    async def test_change_password_not_found(self, db: AsyncSession):
        data = ChangePasswordRequest(current_password="old", new_password="newpass123")
        with pytest.raises(Exception) as exc:
            await service.change_password(db, uuid.uuid4(), data)
        assert "404" in str(exc.value.status_code)


# --- Password reset ---


class TestPasswordReset:
    async def test_request_reset_existing_email(self, db: AsyncSession, user):
        # i18n F4: returns (token, recipient locale) — the locale is
        # resolved here so the router doesn't re-look-up the user.
        issued = await service.request_password_reset(db, user.email)
        assert issued is not None
        token, locale = issued
        assert locale in settings.available_locales_list
        # Token should be a valid JWT
        payload = decode_token(token)
        assert payload["type"] == "reset"
        assert payload["sub"] == str(user.id)

    async def test_request_reset_nonexistent_email(self, db: AsyncSession):
        issued = await service.request_password_reset(db, "nobody@nowhere.com")
        assert issued is None

    async def test_reset_password_success(self, db: AsyncSession, user):
        issued = await service.request_password_reset(db, user.email)
        assert issued is not None
        token, _ = issued

        await service.reset_password(db, token, "brandnew123")

        # Verify new password works
        updated = await db.get(User, user.id)
        assert verify_password("brandnew123", updated.password_hash)

    async def test_reset_password_invalid_token(self, db: AsyncSession):
        with pytest.raises(Exception) as exc:
            await service.reset_password(db, "garbage.token.value", "newpass123")
        assert "400" in str(exc.value.status_code)

    async def test_reset_password_wrong_type_token(self, db: AsyncSession, user):
        """An access token should not work as a reset token."""
        access = create_access_token(str(user.id), str(user.tenant_id))
        with pytest.raises(Exception) as exc:
            await service.reset_password(db, access, "newpass123")
        assert "400" in str(exc.value.status_code)

    async def test_reset_password_nonexistent_user(self, db: AsyncSession):
        fake_token = create_reset_token(str(uuid.uuid4()))
        with pytest.raises(Exception) as exc:
            await service.reset_password(db, fake_token, "newpass123")
        assert "400" in str(exc.value.status_code)


# --- Role CRUD: update + delete + protection ---


class TestRoleUpdateDelete:
    async def test_create_duplicate_role_code(self, db: AsyncSession, tenant):
        from app.modules.auth.schemas import RoleCreate

        code = f"dup-{uuid.uuid4().hex[:6]}"
        await service.create_role(db, tenant.id, RoleCreate(name="First", code=code))

        with pytest.raises(Exception) as exc:
            await service.create_role(
                db, tenant.id, RoleCreate(name="Second", code=code)
            )
        assert "409" in str(exc.value.status_code)

    async def test_update_role_success(self, db: AsyncSession, tenant):
        from app.modules.auth.schemas import RoleCreate, RoleUpdate

        code = f"upd-{uuid.uuid4().hex[:6]}"
        role = await service.create_role(
            db, tenant.id, RoleCreate(name="Updatable", code=code)
        )
        updated = await service.update_role(
            db, tenant.id, role.id, RoleUpdate(name="Updated Role")
        )
        assert updated.name == "Updated Role"

    async def test_update_role_not_found(self, db: AsyncSession, tenant):
        from app.modules.auth.schemas import RoleUpdate

        with pytest.raises(Exception) as exc:
            await service.update_role(db, tenant.id, uuid.uuid4(), RoleUpdate(name="X"))
        assert "404" in str(exc.value.status_code)

    async def test_update_system_role_forbidden(
        self, db: AsyncSession, tenant, admin_role
    ):
        from app.modules.auth.schemas import RoleUpdate

        with pytest.raises(Exception) as exc:
            await service.update_role(
                db, tenant.id, admin_role.id, RoleUpdate(name="Hacked Admin")
            )
        assert "403" in str(exc.value.status_code)

    async def test_update_role_wrong_tenant(self, db: AsyncSession, tenant):
        from app.modules.auth.schemas import RoleCreate, RoleUpdate
        from app.modules.company.models import Tenant

        other = Tenant(name="OtherRole", slug=f"othr-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        code = f"other-{uuid.uuid4().hex[:6]}"
        role = await service.create_role(
            db, other.id, RoleCreate(name="Other", code=code)
        )

        with pytest.raises(Exception) as exc:
            await service.update_role(db, tenant.id, role.id, RoleUpdate(name="Stolen"))
        assert "404" in str(exc.value.status_code)

    async def test_delete_role_success(self, db: AsyncSession, tenant):
        from app.modules.auth.schemas import RoleCreate

        code = f"del-{uuid.uuid4().hex[:6]}"
        role = await service.create_role(
            db, tenant.id, RoleCreate(name="Deletable", code=code)
        )
        await service.delete_role(db, tenant.id, role.id)

        # Verify deleted
        deleted = await db.get(Role, role.id)
        assert deleted is None

    async def test_delete_role_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(Exception) as exc:
            await service.delete_role(db, tenant.id, uuid.uuid4())
        assert "404" in str(exc.value.status_code)

    async def test_delete_system_role_forbidden(
        self, db: AsyncSession, tenant, admin_role
    ):
        with pytest.raises(Exception) as exc:
            await service.delete_role(db, tenant.id, admin_role.id)
        assert "403" in str(exc.value.status_code)

    async def test_delete_role_wrong_tenant(self, db: AsyncSession, tenant):
        from app.modules.auth.schemas import RoleCreate
        from app.modules.company.models import Tenant

        other = Tenant(name="OtherDelR", slug=f"othdr-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        code = f"otherdel-{uuid.uuid4().hex[:6]}"
        role = await service.create_role(
            db, other.id, RoleCreate(name="OtherDel", code=code)
        )

        with pytest.raises(Exception) as exc:
            await service.delete_role(db, tenant.id, role.id)
        assert "404" in str(exc.value.status_code)


# --- Multi-tenant login ---


async def _make_user_in_tenant(
    db: AsyncSession,
    email: str,
    password: str,
    tenant: Tenant,
    admin_role: Role,
    *,
    verified: bool = True,
    active: bool = True,
) -> User:
    """Helper: create a verified user in the given tenant."""
    u = User(
        email=email,
        password_hash=hash_password(password),
        first_name="Multi",
        last_name="Tenant",
        tenant_id=tenant.id,
        is_active=active,
        email_verified_at=datetime.now(timezone.utc) if verified else None,
    )
    db.add(u)
    await db.flush()
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=admin_role.id))
    await db.commit()
    await db.refresh(u)
    return u


class TestMultiTenantLogin:
    """Login when the same email exists in multiple tenants."""

    async def test_single_tenant_returns_tokens(self, db: AsyncSession, user, tenant):
        """Single-tenant user gets JWT directly (backward compatible)."""
        resp = await service.login(db, user.email, "testpass123")
        assert "access_token" in resp
        assert "refresh_token" in resp
        assert "requires_tenant_selection" not in resp

    async def test_multi_tenant_returns_tenant_list(
        self, db: AsyncSession, tenant, admin_role
    ):
        """User in 2 tenants gets a tenant selection prompt."""
        email = f"multi-{uuid.uuid4().hex[:6]}@test.com"
        pw = "testpass123"

        tenant2 = Tenant(name="Second Corp", slug=f"second-{uuid.uuid4().hex[:6]}")
        db.add(tenant2)
        await db.commit()
        await db.refresh(tenant2)

        await _make_user_in_tenant(db, email, pw, tenant, admin_role)
        await _make_user_in_tenant(db, email, pw, tenant2, admin_role)

        resp = await service.login(db, email, pw)
        assert resp["requires_tenant_selection"] is True
        assert len(resp["tenants"]) == 2
        tenant_ids = {t["id"] for t in resp["tenants"]}
        assert tenant.id in tenant_ids
        assert tenant2.id in tenant_ids

    async def test_multi_tenant_one_inactive_returns_tokens(
        self, db: AsyncSession, tenant, admin_role
    ):
        """If one account is deactivated, only the active one counts → direct JWT."""
        email = f"partial-{uuid.uuid4().hex[:6]}@test.com"
        pw = "testpass123"

        tenant2 = Tenant(name="Inactive Corp", slug=f"inact-{uuid.uuid4().hex[:6]}")
        db.add(tenant2)
        await db.commit()
        await db.refresh(tenant2)

        await _make_user_in_tenant(db, email, pw, tenant, admin_role)
        await _make_user_in_tenant(db, email, pw, tenant2, admin_role, active=False)

        resp = await service.login(db, email, pw)
        assert "access_token" in resp
        assert "requires_tenant_selection" not in resp

    async def test_multi_tenant_all_unverified_gives_403(
        self, db: AsyncSession, tenant, admin_role
    ):
        """All matching users unverified → 403."""
        email = f"unver-{uuid.uuid4().hex[:6]}@test.com"
        pw = "testpass123"
        await _make_user_in_tenant(db, email, pw, tenant, admin_role, verified=False)

        with pytest.raises(HTTPException) as exc:
            await service.login(db, email, pw)
        assert exc.value.status_code == 403

    async def test_multi_tenant_wrong_password(
        self, db: AsyncSession, tenant, admin_role
    ):
        email = f"wrongpw-{uuid.uuid4().hex[:6]}@test.com"
        await _make_user_in_tenant(db, email, "correct123", tenant, admin_role)

        with pytest.raises(HTTPException) as exc:
            await service.login(db, email, "wrongpassword")
        assert exc.value.status_code == 401


class TestSelectTenant:
    async def test_select_tenant_success(self, db: AsyncSession, tenant, admin_role):
        email = f"select-{uuid.uuid4().hex[:6]}@test.com"
        pw = "testpass123"

        tenant2 = Tenant(name="Select Corp", slug=f"sel-{uuid.uuid4().hex[:6]}")
        db.add(tenant2)
        await db.commit()
        await db.refresh(tenant2)

        await _make_user_in_tenant(db, email, pw, tenant, admin_role)
        await _make_user_in_tenant(db, email, pw, tenant2, admin_role)

        resp = await service.select_tenant(db, email, pw, tenant2.id)
        assert "access_token" in resp
        payload = decode_token(resp["access_token"])
        assert payload["tenant_id"] == str(tenant2.id)

    async def test_select_tenant_wrong_password(
        self, db: AsyncSession, tenant, admin_role
    ):
        email = f"selwrong-{uuid.uuid4().hex[:6]}@test.com"
        await _make_user_in_tenant(db, email, "correct123", tenant, admin_role)

        with pytest.raises(HTTPException) as exc:
            await service.select_tenant(db, email, "wrong", tenant.id)
        assert exc.value.status_code == 401

    async def test_select_tenant_no_account(self, db: AsyncSession, tenant, admin_role):
        email = f"nosel-{uuid.uuid4().hex[:6]}@test.com"
        await _make_user_in_tenant(db, email, "testpass123", tenant, admin_role)

        with pytest.raises(HTTPException) as exc:
            await service.select_tenant(db, email, "testpass123", uuid.uuid4())
        assert exc.value.status_code == 401


class TestSwitchTenant:
    async def test_switch_tenant_success(self, db: AsyncSession, tenant, admin_role):
        email = f"switch-{uuid.uuid4().hex[:6]}@test.com"
        pw = "testpass123"

        tenant2 = Tenant(name="Switch Corp", slug=f"sw-{uuid.uuid4().hex[:6]}")
        db.add(tenant2)
        await db.commit()
        await db.refresh(tenant2)

        user1 = await _make_user_in_tenant(db, email, pw, tenant, admin_role)
        await _make_user_in_tenant(db, email, pw, tenant2, admin_role)

        resp = await service.switch_tenant(db, user1.id, email, tenant2.id)
        assert "access_token" in resp
        payload = decode_token(resp["access_token"])
        assert payload["tenant_id"] == str(tenant2.id)

    async def test_switch_tenant_no_account_in_target(
        self, db: AsyncSession, tenant, admin_role
    ):
        email = f"noswitch-{uuid.uuid4().hex[:6]}@test.com"
        user1 = await _make_user_in_tenant(db, email, "testpass123", tenant, admin_role)

        with pytest.raises(HTTPException) as exc:
            await service.switch_tenant(db, user1.id, email, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_switch_tenant_inactive_target(
        self, db: AsyncSession, tenant, admin_role
    ):
        email = f"swinact-{uuid.uuid4().hex[:6]}@test.com"
        pw = "testpass123"

        tenant2 = Tenant(name="Inactive Switch", slug=f"swi-{uuid.uuid4().hex[:6]}")
        db.add(tenant2)
        await db.commit()
        await db.refresh(tenant2)

        user1 = await _make_user_in_tenant(db, email, pw, tenant, admin_role)
        await _make_user_in_tenant(db, email, pw, tenant2, admin_role, active=False)

        with pytest.raises(HTTPException) as exc:
            await service.switch_tenant(db, user1.id, email, tenant2.id)
        assert exc.value.status_code == 403


class TestListUserTenants:
    async def test_list_tenants_single(self, db: AsyncSession, tenant, admin_role):
        email = f"list1-{uuid.uuid4().hex[:6]}@test.com"
        await _make_user_in_tenant(db, email, "testpass123", tenant, admin_role)

        tenants = await service.list_user_tenants(db, email)
        assert len(tenants) == 1
        assert tenants[0]["id"] == tenant.id

    async def test_list_tenants_multiple(self, db: AsyncSession, tenant, admin_role):
        email = f"listmulti-{uuid.uuid4().hex[:6]}@test.com"
        pw = "testpass123"

        tenant2 = Tenant(name="List Corp", slug=f"lst-{uuid.uuid4().hex[:6]}")
        db.add(tenant2)
        await db.commit()
        await db.refresh(tenant2)

        await _make_user_in_tenant(db, email, pw, tenant, admin_role)
        await _make_user_in_tenant(db, email, pw, tenant2, admin_role)

        tenants = await service.list_user_tenants(db, email)
        assert len(tenants) == 2

    async def test_list_tenants_excludes_unverified(
        self, db: AsyncSession, tenant, admin_role
    ):
        email = f"listunver-{uuid.uuid4().hex[:6]}@test.com"
        pw = "testpass123"

        tenant2 = Tenant(name="Unver Corp", slug=f"unv-{uuid.uuid4().hex[:6]}")
        db.add(tenant2)
        await db.commit()
        await db.refresh(tenant2)

        await _make_user_in_tenant(db, email, pw, tenant, admin_role)
        await _make_user_in_tenant(db, email, pw, tenant2, admin_role, verified=False)

        tenants = await service.list_user_tenants(db, email)
        assert len(tenants) == 1
        assert tenants[0]["id"] == tenant.id

    async def test_list_tenants_nonexistent_email(self, db: AsyncSession):
        tenants = await service.list_user_tenants(db, "ghost@nowhere.com")
        assert tenants == []
