"""``POST /api/demo/end`` — the visitor ends their own sandbox (HRP-897).

Covers: the sandbox is handed to the purge and its tokens stop working,
``demo.session_ended`` is published, a pending "keep my demo data" signup
keeps the sandbox alive, and a non-demo bearer is rejected.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from app.config import settings
from app.modules.company.models import Tenant
from app.modules.signup.models import SignupRequest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_demo_switch_view import _paid_account_headers


@pytest.fixture
def enable_demo(monkeypatch, skill_levels):
    """Same configuration knobs as ``test_demo_start.py``."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "demo_turnstile_secret", "")
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 0)
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 500)
    monkeypatch.setattr(settings, "demo_initial_credits", 0)
    monkeypatch.setattr(settings, "demo_trusted_proxies", "127.0.0.0/8")


@pytest.fixture
def published(monkeypatch) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []

    async def _publish(event: str, data: dict) -> None:
        events.append((event, data))

    monkeypatch.setattr("app.core.events.publish", _publish)
    return events


@pytest.mark.asyncio
async def test_end_expires_sandbox_and_revokes_tokens(
    client: AsyncClient,
    admin_role,
    enable_demo,
    published,
    db: AsyncSession,
):
    start = await client.post("/api/demo/start", json={})
    assert start.status_code == 201
    headers = {"Authorization": f"Bearer {start.json()['access_token']}"}
    tenant_id = start.json()["tenant_id"]
    published.clear()

    resp = await client.post("/api/demo/end", headers=headers)
    assert resp.status_code == 204

    tenant = await db.get(Tenant, tenant_id)
    await db.refresh(tenant)
    assert tenant.expires_at <= datetime.now(timezone.utc)
    assert published == [("demo.session_ended", {"tenant_id": tenant_id})]

    # The sandbox lives until the next purge tick; its tokens must not.
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_end_spares_sandbox_with_pending_keep_data_signup(
    client: AsyncClient,
    admin_role,
    enable_demo,
    published,
    db: AsyncSession,
):
    start = await client.post("/api/demo/start", json={})
    assert start.status_code == 201
    tenant_id = start.json()["tenant_id"]
    db.add(
        SignupRequest(
            email="keeper@example.com",
            status="pending_moderation",
            source="demo",
            demo_tenant_id_snapshot=uuid.UUID(tenant_id),
            keep_demo_data=True,
        )
    )
    await db.commit()

    resp = await client.post(
        "/api/demo/end",
        headers={"Authorization": f"Bearer {start.json()['access_token']}"},
    )
    assert resp.status_code == 204

    tenant = await db.get(Tenant, tenant_id)
    await db.refresh(tenant)
    assert tenant.expires_at > datetime.now(timezone.utc)
    assert published[-1][0] == "demo.session_ended"

    # Revoked means revoked: the resume hint outlives the logout on the
    # marketing origin and must not buy a way back into the kept sandbox.
    old = {"Authorization": f"Bearer {start.json()['access_token']}"}
    assert (await client.get("/api/auth/me", headers=old)).status_code == 401
    again = await client.post("/api/demo/start", json={}, headers=old)
    assert again.status_code == 201
    assert again.json()["tenant_id"] != tenant_id


@pytest.mark.asyncio
async def test_end_rejects_non_demo_token(
    client: AsyncClient,
    enable_demo,
    db: AsyncSession,
):
    resp = await client.post("/api/demo/end", headers=await _paid_account_headers(db))
    assert resp.status_code == 403
    assert "demo_end_requires_demo_session" in resp.text
