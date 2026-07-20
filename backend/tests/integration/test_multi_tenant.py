import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import register_and_verify


def _email():
    return f"mt-{uuid.uuid4().hex[:8]}@example.com"


async def _register_verified(client: AsyncClient, db: AsyncSession) -> str:
    """Register a user, verify email, and return the access token."""
    email = _email()
    data = await register_and_verify(client, db, email)
    return data["access_token"]


class TestMultiTenantIsolation:
    """Verify that tenants cannot access each other's data."""

    async def test_tenant_a_cannot_see_tenant_b_employees(
        self, client: AsyncClient, db: AsyncSession
    ):
        token_a = await _register_verified(client, db)
        token_b = await _register_verified(client, db)

        resp_a = await client.get(
            "/api/employees", headers={"Authorization": f"Bearer {token_a}"}
        )
        resp_b = await client.get(
            "/api/employees", headers={"Authorization": f"Bearer {token_b}"}
        )

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert resp_a.json()["total"] == 0
        assert resp_b.json()["total"] == 0

    async def test_tenant_a_cannot_see_tenant_b_divisions(
        self, client: AsyncClient, db: AsyncSession
    ):
        token_a = await _register_verified(client, db)
        token_b = await _register_verified(client, db)

        await client.post(
            "/api/divisions",
            json={"name": "Secret B"},
            headers={"Authorization": f"Bearer {token_b}"},
        )

        resp_a = await client.get(
            "/api/divisions", headers={"Authorization": f"Bearer {token_a}"}
        )
        assert resp_a.status_code == 200
        names = [d["name"] for d in resp_a.json()]
        assert "Secret B" not in names

    async def test_tenant_a_cannot_see_tenant_b_assessments(
        self, client: AsyncClient, db: AsyncSession
    ):
        token_a = await _register_verified(client, db)
        token_b = await _register_verified(client, db)

        resp_a = await client.get(
            "/api/assessments", headers={"Authorization": f"Bearer {token_a}"}
        )
        resp_b = await client.get(
            "/api/assessments", headers={"Authorization": f"Bearer {token_b}"}
        )

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert resp_a.json()["total"] == 0
        assert resp_b.json()["total"] == 0
