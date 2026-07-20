import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.modules.company import service
from app.modules.company.schemas import DivisionCreate
from sqlalchemy.ext.asyncio import AsyncSession


class TestOnboardingStatus:
    async def test_needs_onboarding_fresh_tenant(self, db: AsyncSession, tenant):
        """Fresh tenant with 0 employees needs onboarding."""
        status = await service.get_onboarding_status(db, tenant.id)
        assert status.needs_onboarding is True
        assert status.onboarding_completed is False
        assert status.employee_count == 0
        assert status.division_count == 0
        assert status.has_invitations is False

    async def test_no_onboarding_with_employees(
        self, db: AsyncSession, tenant, employee
    ):
        """Tenant with employees does not need onboarding."""
        status = await service.get_onboarding_status(db, tenant.id)
        assert status.needs_onboarding is False
        assert status.employee_count == 1

    async def test_no_onboarding_after_complete(self, db: AsyncSession, tenant):
        """After marking complete, needs_onboarding is False even with 0 employees."""
        await service.complete_onboarding(db, tenant.id)
        status = await service.get_onboarding_status(db, tenant.id)
        assert status.needs_onboarding is False
        assert status.onboarding_completed is True
        assert status.employee_count == 0

    async def test_division_count_in_status(self, db: AsyncSession, tenant):
        """Division count is reported in onboarding status."""
        await service.create_division(db, tenant.id, DivisionCreate(name="Eng"))
        await service.create_division(db, tenant.id, DivisionCreate(name="HR"))
        status = await service.get_onboarding_status(db, tenant.id)
        assert status.division_count == 2

    async def test_invitation_detected(self, db: AsyncSession, tenant, user):
        """Pending invitations are detected in status."""
        from app.modules.auth.models import Invitation

        inv = Invitation(
            email="new@test.com",
            name="New Recipient",
            token=uuid.uuid4().hex,
            role_code="employee",
            invited_by=user.id,
            tenant_id=tenant.id,
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.add(inv)
        await db.commit()

        status = await service.get_onboarding_status(db, tenant.id)
        assert status.has_invitations is True


class TestCompleteOnboarding:
    async def test_complete_onboarding(self, db: AsyncSession, tenant):
        """complete_onboarding sets the flag to True."""
        result = await service.complete_onboarding(db, tenant.id)
        assert result.onboarding_completed is True

    async def test_complete_onboarding_idempotent(self, db: AsyncSession, tenant):
        """Calling complete_onboarding twice is safe."""
        await service.complete_onboarding(db, tenant.id)
        result = await service.complete_onboarding(db, tenant.id)
        assert result.onboarding_completed is True

    async def test_complete_onboarding_not_found(self, db: AsyncSession):
        """Completing onboarding for nonexistent tenant raises 404."""
        with pytest.raises(Exception) as exc:
            await service.complete_onboarding(db, uuid.uuid4())
        assert "404" in str(exc.value.status_code)


class TestOnboardingEndpoints:
    async def test_get_status_endpoint(self, auth_client):
        resp = await auth_client.get("/api/onboarding/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "needs_onboarding" in data
        assert "employee_count" in data

    async def test_complete_endpoint(self, auth_client):
        resp = await auth_client.post("/api/onboarding/complete")
        assert resp.status_code == 200
        data = resp.json()
        assert data["onboarding_completed"] is True

    async def test_complete_endpoint_non_admin(self, db, client, tenant):
        """Non-admin users cannot complete onboarding."""
        from app.core.security import create_access_token, hash_password
        from app.modules.auth.models import Role, User, user_roles
        from sqlalchemy import select

        # Create employee role
        result = await db.execute(
            select(Role).where(
                Role.code == "employee", Role.is_system == True  # noqa: E712
            )
        )
        role = result.scalar_one_or_none()
        if not role:
            role = Role(name="Employee", code="employee", is_system=True)
            db.add(role)
            await db.commit()
            await db.refresh(role)

        u = User(
            email=f"emp-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("pass123"),
            first_name="Emp",
            last_name="User",
            tenant_id=tenant.id,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
        await db.commit()

        token = create_access_token(str(u.id), str(tenant.id))
        client.headers["Authorization"] = f"Bearer {token}"
        resp = await client.post("/api/onboarding/complete")
        assert resp.status_code == 403
