"""Tests for INV2/INV3: PATCH /api/invitations/{id} and PATCH /api/invitations/{id}/email."""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from app.core.security import create_access_token, hash_password
from app.modules.auth import service
from app.modules.auth.models import Invitation, Role, User, user_roles
from app.modules.auth.schemas import (
    InvitationCreate,
    InvitationEmailUpdate,
    InvitationUpdate,
)
from app.modules.company.models import Division, Tenant
from app.modules.position.models import Position
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def manager_role(db: AsyncSession):
    from sqlalchemy import select

    result = await db.execute(
        select(Role).where(Role.code == "manager", Role.is_system == True)  # noqa: E712
    )
    # ``.first()`` not ``scalar_one_or_none()``: the shared test DB accumulates
    # duplicate system roles from other tests, which intermittently tripped
    # MultipleResultsFound here (order-dependent flake, review P0-2).
    role = result.scalars().first()
    if not role:
        role = Role(name="Manager", code="manager", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


@pytest_asyncio.fixture
async def division(db: AsyncSession, tenant):
    d = Division(name="Engineering", tenant_id=tenant.id)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d


async def _create_pending(db, tenant, user, *, email=None, name="Target") -> dict:
    return await service.create_invitation(
        db,
        tenant.id,
        user.id,
        InvitationCreate(
            email=email or f"target-{uuid.uuid4().hex[:6]}@test.com",
            name=name,
            role_code="admin",
        ),
    )


async def _load_inv(db: AsyncSession, invitation_id: uuid.UUID) -> Invitation:
    inv = await db.get(Invitation, invitation_id)
    assert inv is not None
    return inv


class TestUpdateInvitation:
    async def test_admin_updates_position_and_division(
        self,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        manager_role,
        position,
        division,
    ):
        inv = await _create_pending(db, tenant, user)
        result = await service.update_invitation(
            db,
            tenant.id,
            inv["id"],
            InvitationUpdate(position_id=position.id, division_id=division.id),
            role_codes=["admin"],
        )
        assert result["position_id"] == position.id
        assert result["division_id"] == division.id

    async def test_admin_changes_role(
        self, db: AsyncSession, user, tenant, admin_role, manager_role
    ):
        inv = await _create_pending(db, tenant, user)
        result = await service.update_invitation(
            db,
            tenant.id,
            inv["id"],
            InvitationUpdate(role_code="manager"),
            role_codes=["admin"],
        )
        assert result["role_code"] == "manager"

    # NOTE: the "platform_admin changes role" case moved to
    # tests/unit/ee/test_rbac_extension.py — platform-admin
    # admin-equivalence is provided by the enterprise RBAC extension
    # (review [21]) and does not exist in community builds.

    async def test_manager_updates_position_and_division(
        self, db: AsyncSession, user, tenant, admin_role, position, division
    ):
        """Service-layer field RBAC only — kept as defence in depth.

        Since HRP-436 the router refuses a manager before this runs (see
        ``test_invitation_access.py``), so this asserts the inner tier, not a
        reachable capability.
        """
        inv = await _create_pending(db, tenant, user)
        result = await service.update_invitation(
            db,
            tenant.id,
            inv["id"],
            InvitationUpdate(position_id=position.id, division_id=division.id),
            role_codes=["manager"],
        )
        assert result["position_id"] == position.id
        assert result["division_id"] == division.id

    async def test_manager_cannot_change_role(
        self, db: AsyncSession, user, tenant, admin_role, manager_role
    ):
        inv = await _create_pending(db, tenant, user)
        with pytest.raises(HTTPException) as exc:
            await service.update_invitation(
                db,
                tenant.id,
                inv["id"],
                InvitationUpdate(role_code="manager"),
                role_codes=["manager"],
            )
        assert exc.value.status_code == 403

    async def test_manager_cannot_change_role_in_combined_payload(
        self, db: AsyncSession, user, tenant, admin_role, manager_role, position
    ):
        """Field-level RBAC: even with role+position in one payload, manager → 403."""
        inv = await _create_pending(db, tenant, user)
        with pytest.raises(HTTPException) as exc:
            await service.update_invitation(
                db,
                tenant.id,
                inv["id"],
                InvitationUpdate(role_code="manager", position_id=position.id),
                role_codes=["manager"],
            )
        assert exc.value.status_code == 403
        # Position must NOT be persisted when the request is rejected.
        db_inv = await db.get(Invitation, inv["id"])
        assert db_inv is not None
        assert db_inv.position_id is None

    async def test_invalid_role_rejected(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        inv = await _create_pending(db, tenant, user)
        with pytest.raises(HTTPException) as exc:
            await service.update_invitation(
                db,
                tenant.id,
                inv["id"],
                InvitationUpdate(role_code="nonexistent"),
                role_codes=["admin"],
            )
        assert exc.value.status_code == 400

    async def test_clear_division(
        self, db: AsyncSession, user, tenant, admin_role, division
    ):
        inv = await service.create_invitation(
            db,
            tenant.id,
            user.id,
            InvitationCreate(
                email=f"clr-{uuid.uuid4().hex[:6]}@test.com",
                name="Clearable",
                role_code="admin",
                division_id=division.id,
            ),
        )
        result = await service.update_invitation(
            db,
            tenant.id,
            inv["id"],
            InvitationUpdate(division_id=None),
            role_codes=["admin"],
        )
        assert result["division_id"] is None

    async def test_accepted_invitation_rejected(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        inv = await _create_pending(db, tenant, user)
        db_inv = await db.get(Invitation, inv["id"])
        assert db_inv is not None
        db_inv.status = "accepted"
        db_inv.accepted_at = datetime.now(timezone.utc)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.update_invitation(
                db,
                tenant.id,
                inv["id"],
                InvitationUpdate(role_code="admin"),
                role_codes=["admin"],
            )
        assert exc.value.status_code == 409

    async def test_cancelled_invitation_rejected(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        inv = await _create_pending(db, tenant, user)
        await service.cancel_invitation(db, tenant.id, inv["id"])

        with pytest.raises(HTTPException) as exc:
            await service.update_invitation(
                db,
                tenant.id,
                inv["id"],
                InvitationUpdate(role_code="admin"),
                role_codes=["admin"],
            )
        assert exc.value.status_code == 409

    async def test_expired_invitation_rejected(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        inv = await _create_pending(db, tenant, user)
        db_inv = await _load_inv(db, inv["id"])
        db_inv.status = "expired"
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.update_invitation(
                db,
                tenant.id,
                inv["id"],
                InvitationUpdate(role_code="admin"),
                role_codes=["admin"],
            )
        assert exc.value.status_code == 409

    async def test_other_tenant_404(self, db: AsyncSession, user, tenant, admin_role):
        inv = await _create_pending(db, tenant, user)
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.update_invitation(
                db,
                other.id,
                inv["id"],
                InvitationUpdate(role_code="admin"),
                role_codes=["admin"],
            )
        assert exc.value.status_code == 404


class TestUpdateInvitationEmail:
    async def test_email_change_rotates_token_and_expiry(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        inv = await _create_pending(db, tenant, user, email="old@test.com")
        old_token = (await _load_inv(db, inv["id"])).token
        old_expiry = inv["expires_at"]

        with patch("app.modules.auth.service.send_invitation_email") as mock_send:
            result = await service.update_invitation_email(
                db,
                tenant.id,
                inv["id"],
                InvitationEmailUpdate(email="new@test.com"),
            )

        assert result["email"] == "new@test.com"
        new_token = (await _load_inv(db, inv["id"])).token
        assert new_token != old_token
        assert result["expires_at"] >= old_expiry
        mock_send.assert_called_once()
        sent_email = mock_send.call_args[0][0]
        assert sent_email == "new@test.com"

    async def test_duplicate_email_same_tenant_rejected(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        await _create_pending(db, tenant, user, email="taken@test.com")
        target = await _create_pending(db, tenant, user, email="other@test.com")

        with pytest.raises(HTTPException) as exc:
            await service.update_invitation_email(
                db,
                tenant.id,
                target["id"],
                InvitationEmailUpdate(email="taken@test.com"),
            )
        assert exc.value.status_code == 409

    async def test_existing_user_same_tenant_rejected(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        target = await _create_pending(db, tenant, user, email="target@test.com")

        with pytest.raises(HTTPException) as exc:
            await service.update_invitation_email(
                db,
                tenant.id,
                target["id"],
                InvitationEmailUpdate(email=user.email),
            )
        assert exc.value.status_code == 409

    async def test_cross_tenant_collision_allowed(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        """Same email in different tenant is allowed (multi-tenant by design)."""
        # Create another tenant with a pending invitation for shared@test.com
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        from app.core.security import hash_password
        from app.modules.auth.models import User as UserModel

        other_user = UserModel(
            email=f"o-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("x" * 12),
            first_name="O",
            last_name="U",
            tenant_id=other.id,
        )
        db.add(other_user)
        await db.commit()
        from app.modules.auth.models import user_roles as _user_roles_tbl

        await db.execute(
            _user_roles_tbl.insert().values(
                user_id=other_user.id, role_id=admin_role.id
            )
        )
        await db.commit()

        await service.create_invitation(
            db,
            other.id,
            other_user.id,
            InvitationCreate(email="shared@test.com", name="Shared", role_code="admin"),
        )

        # Now patch our tenant's invitation to the same email — must succeed
        target = await _create_pending(db, tenant, user, email="ours@test.com")
        with patch("app.modules.auth.service.send_invitation_email"):
            result = await service.update_invitation_email(
                db,
                tenant.id,
                target["id"],
                InvitationEmailUpdate(email="shared@test.com"),
            )
        assert result["email"] == "shared@test.com"

    async def test_accepted_email_change_rejected(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        inv = await _create_pending(db, tenant, user)
        db_inv = await _load_inv(db, inv["id"])
        db_inv.status = "accepted"
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.update_invitation_email(
                db,
                tenant.id,
                inv["id"],
                InvitationEmailUpdate(email="elsewhere@test.com"),
            )
        assert exc.value.status_code == 409

    async def test_same_email_no_collision_check(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        """PATCHing an invitation with its own current email rotates the token without 409ing on itself."""
        inv = await _create_pending(db, tenant, user, email="same@test.com")
        old_token = (await _load_inv(db, inv["id"])).token

        with patch("app.modules.auth.service.send_invitation_email"):
            result = await service.update_invitation_email(
                db,
                tenant.id,
                inv["id"],
                InvitationEmailUpdate(email="same@test.com"),
            )
        assert result["email"] == "same@test.com"
        new_token = (await _load_inv(db, inv["id"])).token
        assert new_token != old_token


# --- INV3 ---


@pytest_asyncio.fixture
async def employee_role(db: AsyncSession):
    from sqlalchemy import select

    result = await db.execute(
        select(Role).where(Role.code == "employee", Role.is_system.is_(True))
    )
    role = result.scalar_one_or_none()
    if not role:
        role = Role(name="Employee", code="employee", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


async def _make_user_with_role(
    db: AsyncSession, tenant, role: Role, *, label: str
) -> User:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

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


def _client_for(client: AsyncClient, user: User, tenant) -> AsyncClient:
    token = create_access_token(str(user.id), str(tenant.id))
    client.headers["Authorization"] = f"Bearer {token}"
    return client


class TestUpdateInvitationRouter:
    """Endpoint-level RBAC: PATCH /api/invitations/{id} and /email."""

    async def test_manager_cannot_change_role_via_router(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        manager_role,
    ):
        inv = await _create_pending(db, tenant, user)
        manager = await _make_user_with_role(db, tenant, manager_role, label="mgr")
        c = _client_for(client, manager, tenant)
        resp = await c.patch(
            f"/api/invitations/{inv['id']}",
            json={"role_code": "admin"},
        )
        assert resp.status_code == 403

    async def test_manager_cannot_change_email_via_router(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        manager_role,
    ):
        inv = await _create_pending(db, tenant, user)
        manager = await _make_user_with_role(db, tenant, manager_role, label="mgr")
        c = _client_for(client, manager, tenant)
        resp = await c.patch(
            f"/api/invitations/{inv['id']}/email",
            json={"email": "elsewhere@test.com"},
        )
        assert resp.status_code == 403

    async def test_employee_cannot_update_invitation_via_router(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        employee_role,
    ):
        inv = await _create_pending(db, tenant, user)
        emp = await _make_user_with_role(db, tenant, employee_role, label="emp")
        c = _client_for(client, emp, tenant)
        resp = await c.patch(
            f"/api/invitations/{inv['id']}",
            json={"role_code": "admin"},
        )
        assert resp.status_code == 403

    async def test_admin_changes_role_via_router(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        manager_role,
        access_token,
    ):
        inv = await _create_pending(db, tenant, user)
        client.headers["Authorization"] = f"Bearer {access_token}"
        resp = await client.patch(
            f"/api/invitations/{inv['id']}",
            json={"role_code": "manager"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role_code"] == "manager"


class TestInvitationTenantScope:
    """INV3.5 — division/position must belong to the caller's tenant."""

    async def test_update_rejects_foreign_division(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        inv = await _create_pending(db, tenant, user)
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)
        foreign_div = Division(name="Foreign", tenant_id=other.id)
        db.add(foreign_div)
        await db.commit()
        await db.refresh(foreign_div)

        with pytest.raises(HTTPException) as exc:
            await service.update_invitation(
                db,
                tenant.id,
                inv["id"],
                InvitationUpdate(division_id=foreign_div.id),
                role_codes=["admin"],
            )
        assert exc.value.status_code == 400
        assert "Division" in exc.value.detail

    async def test_update_rejects_foreign_position(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        inv = await _create_pending(db, tenant, user)
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)
        foreign_pos = Position(
            tenant_id=other.id, title="Foreign Engineer", source="manual"
        )
        db.add(foreign_pos)
        await db.commit()
        await db.refresh(foreign_pos)

        with pytest.raises(HTTPException) as exc:
            await service.update_invitation(
                db,
                tenant.id,
                inv["id"],
                InvitationUpdate(position_id=foreign_pos.id),
                role_codes=["admin"],
            )
        assert exc.value.status_code == 400
        assert "Position" in exc.value.detail

    async def test_create_rejects_foreign_division(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)
        foreign_div = Division(name="Foreign", tenant_id=other.id)
        db.add(foreign_div)
        await db.commit()
        await db.refresh(foreign_div)

        with pytest.raises(HTTPException) as exc:
            await service.create_invitation(
                db,
                tenant.id,
                user.id,
                InvitationCreate(
                    email=f"newcomer-{uuid.uuid4().hex[:6]}@test.com",
                    name="Newcomer",
                    role_code="admin",
                    division_id=foreign_div.id,
                ),
            )
        assert exc.value.status_code == 400

    async def test_create_rejects_foreign_position(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)
        foreign_pos = Position(
            tenant_id=other.id, title="Foreign Engineer", source="manual"
        )
        db.add(foreign_pos)
        await db.commit()
        await db.refresh(foreign_pos)

        with pytest.raises(HTTPException) as exc:
            await service.create_invitation(
                db,
                tenant.id,
                user.id,
                InvitationCreate(
                    email=f"newcomer-{uuid.uuid4().hex[:6]}@test.com",
                    name="Newcomer",
                    role_code="admin",
                    position_id=foreign_pos.id,
                ),
            )
        assert exc.value.status_code == 400


class TestInvitationAuditLog:
    """INV3.7 — email rotation should emit a structured audit log entry."""

    async def test_email_change_emits_audit_log(
        self, db: AsyncSession, user, tenant, admin_role, caplog
    ):
        import logging

        caplog.set_level(logging.INFO, logger="app.modules.auth.service")
        inv = await _create_pending(db, tenant, user, email="old@test.com")
        with patch("app.modules.auth.service.send_invitation_email"):
            await service.update_invitation_email(
                db,
                tenant.id,
                inv["id"],
                InvitationEmailUpdate(email="new@test.com"),
                changed_by_id=user.id,
            )
        rec = next(
            (r for r in caplog.records if r.message == "invitation.email_changed"),
            None,
        )
        assert rec is not None
        assert rec.old_email == "old@test.com"
        assert rec.new_email == "new@test.com"
        assert rec.changed_by == str(user.id)

    async def test_no_audit_log_when_email_unchanged(
        self, db: AsyncSession, user, tenant, admin_role, caplog
    ):
        import logging

        caplog.set_level(logging.INFO, logger="app.modules.auth.service")
        inv = await _create_pending(db, tenant, user, email="same@test.com")
        with patch("app.modules.auth.service.send_invitation_email"):
            await service.update_invitation_email(
                db,
                tenant.id,
                inv["id"],
                InvitationEmailUpdate(email="same@test.com"),
                changed_by_id=user.id,
            )
        assert not any(r.message == "invitation.email_changed" for r in caplog.records)


class TestInvitationRateLimit:
    """INV3.6 — slowapi limits on /email and /resend."""

    async def test_email_rate_limit_returns_429(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        access_token,
    ):
        inv = await _create_pending(db, tenant, user, email="rl@test.com")
        client.headers["Authorization"] = f"Bearer {access_token}"

        # Reset the limiter so other tests' calls don't pollute the window.
        from app.modules.auth.router import invitations_limiter

        invitations_limiter.reset()

        with patch("app.modules.auth.service.send_invitation_email"):
            for i in range(5):
                resp = await client.patch(
                    f"/api/invitations/{inv['id']}/email",
                    json={"email": f"rl{i}@test.com"},
                )
                assert resp.status_code == 200, resp.text
            blocked = await client.patch(
                f"/api/invitations/{inv['id']}/email",
                json={"email": "rl-overflow@test.com"},
            )
        assert blocked.status_code == 429

    async def test_resend_rate_limit_returns_429(
        self,
        client: AsyncClient,
        db: AsyncSession,
        user,
        tenant,
        admin_role,
        access_token,
    ):
        inv = await _create_pending(db, tenant, user, email="rs@test.com")
        client.headers["Authorization"] = f"Bearer {access_token}"

        from app.modules.auth.router import invitations_limiter

        invitations_limiter.reset()

        with patch("app.modules.auth.service.send_invitation_reminder_email"):
            for _ in range(3):
                resp = await client.post(
                    f"/api/invitations/{inv['id']}/resend",
                )
                assert resp.status_code == 200, resp.text
            blocked = await client.post(
                f"/api/invitations/{inv['id']}/resend",
            )
        assert blocked.status_code == 429
