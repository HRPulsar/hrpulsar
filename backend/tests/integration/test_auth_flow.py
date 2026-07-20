import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import register_and_verify


def _email():
    return f"test-{uuid.uuid4().hex[:8]}@example.com"


class TestAuthFlow:
    """Test the full auth flow: register -> verify -> login -> access protected -> refresh."""

    async def test_register_returns_pending_verification(self, client: AsyncClient):
        email = _email()
        resp = await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "password123",
                "first_name": "Flow",
                "last_name": "Test",
                "company_name": f"Corp-{uuid.uuid4().hex[:6]}",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["pending_verification"] is True
        assert data["email"] == email
        assert "access_token" not in data

    async def test_register_and_verify(self, client: AsyncClient, db: AsyncSession):
        email = _email()
        data = await register_and_verify(client, db, email)
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == email

    async def test_login(self, client: AsyncClient, db: AsyncSession):
        email = _email()
        await register_and_verify(client, db, email)
        resp = await client.post(
            "/api/auth/login", json={"email": email, "password": "password123"}
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_access_protected_endpoint(
        self, client: AsyncClient, db: AsyncSession
    ):
        email = _email()
        data = await register_and_verify(client, db, email)
        token = data["access_token"]
        resp = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == email

    async def test_access_without_token_fails(self, client: AsyncClient):
        resp = await client.get("/api/auth/me")
        assert resp.status_code in (401, 403)

    async def test_refresh_token_flow(self, client: AsyncClient, db: AsyncSession):
        email = _email()
        data = await register_and_verify(client, db, email)
        refresh_token = data["refresh_token"]
        resp = await client.post(
            "/api/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_login_wrong_password(self, client: AsyncClient, db: AsyncSession):
        email = _email()
        await register_and_verify(client, db, email)
        resp = await client.post(
            "/api/auth/login", json={"email": email, "password": "wrongpassword"}
        )
        assert resp.status_code == 401

    async def test_login_unverified_user_fails(self, client: AsyncClient):
        """Unverified user cannot login."""
        email = _email()
        await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "password123",
                "first_name": "U",
                "last_name": "V",
                "company_name": f"Corp-{uuid.uuid4().hex[:6]}",
            },
        )
        resp = await client.post(
            "/api/auth/login", json={"email": email, "password": "password123"}
        )
        assert resp.status_code == 403


class TestProfileEndpoints:
    async def test_update_profile(self, auth_client: AsyncClient):
        resp = await auth_client.put(
            "/api/auth/me", json={"first_name": "Updated", "last_name": "Profile"}
        )
        assert resp.status_code == 200
        assert resp.json()["first_name"] == "Updated"

    async def test_change_password(self, auth_client: AsyncClient):
        resp = await auth_client.post(
            "/api/auth/change-password",
            json={
                "current_password": "testpass123",
                "new_password": "newpassword123",
            },
        )
        assert resp.status_code == 204

    async def test_change_password_wrong_current(self, auth_client: AsyncClient):
        resp = await auth_client.post(
            "/api/auth/change-password",
            json={
                "current_password": "wrongpassword",
                "new_password": "newpassword123",
            },
        )
        assert resp.status_code == 400
