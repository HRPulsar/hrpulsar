"""HRP-435: public token-scoped invitation preview backing the accept form."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from app.modules.auth import service
from app.modules.auth.models import Invitation
from app.modules.auth.schemas import InvitationCreate
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def invitation(db: AsyncSession, tenant, user, admin_role) -> Invitation:
    created = await service.create_invitation(
        db,
        tenant.id,
        user.id,
        InvitationCreate(
            email=f"invitee-{uuid.uuid4().hex[:6]}@test.com",
            name="Anna Maria Schmidt",
            role_code="admin",
        ),
    )
    result = await db.execute(
        select(Invitation).where(Invitation.id == created["id"])
    )
    return result.scalar_one()


class TestInvitationPreview:
    async def test_returns_name_and_email_for_a_pending_invitation(
        self, client: AsyncClient, invitation: Invitation
    ):
        resp = await client.get(f"/api/auth/invitations/{invitation.token}")
        assert resp.status_code == 200
        assert resp.json() == {
            "email": invitation.email,
            "name": "Anna Maria Schmidt",
        }

    async def test_response_exposes_nothing_beyond_name_and_email(
        self, client: AsyncClient, invitation: Invitation
    ):
        """Holding the token is the only authorisation, so keep it narrow."""
        resp = await client.get(f"/api/auth/invitations/{invitation.token}")
        assert set(resp.json()) == {"email", "name"}

    async def test_requires_no_authentication(
        self, client: AsyncClient, invitation: Invitation
    ):
        client.headers.pop("Authorization", None)
        resp = await client.get(f"/api/auth/invitations/{invitation.token}")
        assert resp.status_code == 200

    async def test_unknown_token_is_404(self, client: AsyncClient):
        resp = await client.get(f"/api/auth/invitations/{uuid.uuid4().hex}")
        assert resp.status_code == 404

    async def test_accepted_invitation_is_rejected(
        self, client: AsyncClient, db: AsyncSession, invitation: Invitation
    ):
        """The common real-world case: the link was already used."""
        invitation.status = "accepted"
        invitation.accepted_at = datetime.now(timezone.utc)
        await db.commit()
        resp = await client.get(f"/api/auth/invitations/{invitation.token}")
        assert resp.status_code == 400

    async def test_cancelled_invitation_is_rejected(
        self, client: AsyncClient, db: AsyncSession, invitation: Invitation
    ):
        invitation.status = "cancelled"
        await db.commit()
        resp = await client.get(f"/api/auth/invitations/{invitation.token}")
        assert resp.status_code == 400

    async def test_expired_invitation_is_rejected_without_mutating_it(
        self, client: AsyncClient, db: AsyncSession, invitation: Invitation
    ):
        """A GET must not write — unlike accept, which flips the row to expired."""
        invitation.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await db.commit()

        resp = await client.get(f"/api/auth/invitations/{invitation.token}")
        assert resp.status_code == 400

        await db.refresh(invitation)
        assert invitation.status == "pending"
