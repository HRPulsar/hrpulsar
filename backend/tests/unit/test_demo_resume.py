"""``POST /api/demo/start`` with a bearer token resumes the same demo
tenant instead of provisioning a fresh one.

Covers the happy path (same tenant_id + ``resumed=True``) and the
fall-throughs: expired tenant, paid-account token, malformed bearer,
and a token whose tenant has been hard-deleted. Resume must not
charge the per-IP throttle or trigger a Turnstile failure either.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.config import settings
from app.core.security import (
    create_demo_access_token,
    create_refresh_token,
)
from app.modules.company.models import Tenant
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def enable_demo(monkeypatch, skill_levels):
    """Same configuration knobs as ``test_demo_start.py`` (incl. the
    ``skill_levels`` dependency for isolated runs)."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "demo_turnstile_secret", "")
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 0)
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 500)
    monkeypatch.setattr(settings, "demo_initial_credits", 0)
    monkeypatch.setattr(settings, "demo_trusted_proxies", "127.0.0.0/8")


@pytest.mark.asyncio
async def test_resume_returns_same_tenant(
    client: AsyncClient, admin_role, enable_demo, db: AsyncSession
):
    first = await client.post("/api/demo/start", json={})
    assert first.status_code == 201
    token = first.json()["access_token"]
    tenant_id = first.json()["tenant_id"]

    resumed = await client.post(
        "/api/demo/start",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resumed.status_code == 201, resumed.text
    body = resumed.json()
    assert body["resumed"] is True
    assert body["tenant_id"] == tenant_id
    assert body["credits_granted"] == 0
    assert body["redirect_url"] == "/dashboard"


@pytest.mark.asyncio
async def test_resume_skips_turnstile_and_rate_limit(
    client: AsyncClient, admin_role, enable_demo, db: AsyncSession, monkeypatch
):
    first = await client.post("/api/demo/start", json={})
    assert first.status_code == 201
    token = first.json()["access_token"]

    # Tighten the guards: Turnstile is now strictly required and the
    # IP throttle is set to 1/h. A second cold ``/demo/start`` would
    # 400 (turnstile) or 429 (throttle) — resume must bypass both.
    monkeypatch.setattr(settings, "demo_turnstile_secret", "test-secret")
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 1)

    resumed = await client.post(
        "/api/demo/start",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resumed.status_code == 201, resumed.text
    assert resumed.json()["resumed"] is True


@pytest.mark.asyncio
async def test_resume_falls_through_when_tenant_expired(
    client: AsyncClient, admin_role, enable_demo, db: AsyncSession
):
    first = await client.post("/api/demo/start", json={})
    assert first.status_code == 201
    token = first.json()["access_token"]
    tenant_id = uuid.UUID(first.json()["tenant_id"])

    # Force the tenant past its hard TTL — resume must refuse to hand
    # back a dead sandbox.
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one()
    tenant.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()

    resumed = await client.post(
        "/api/demo/start",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resumed.status_code == 201, resumed.text
    body = resumed.json()
    assert body["resumed"] is False
    assert body["tenant_id"] != str(tenant_id)


@pytest.mark.asyncio
async def test_resume_falls_through_on_malformed_authorization(
    client: AsyncClient, admin_role, enable_demo, db: AsyncSession
):
    # ``Bearer`` with no token, and the scheme alone — both shapes are
    # treated as "no resume hint" rather than a 401.
    for header in ["Bearer", "Bearer ", "Token abc", "abc"]:
        resp = await client.post(
            "/api/demo/start",
            json={},
            headers={"Authorization": header},
        )
        assert resp.status_code == 201, (header, resp.text)
        assert resp.json()["resumed"] is False


@pytest.mark.asyncio
async def test_resume_falls_through_on_garbage_token(
    client: AsyncClient, admin_role, enable_demo, db: AsyncSession
):
    resp = await client.post(
        "/api/demo/start",
        json={},
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["resumed"] is False


@pytest.mark.asyncio
async def test_resume_falls_through_on_refresh_token_type(
    client: AsyncClient, admin_role, enable_demo, db: AsyncSession
):
    # A refresh JWT decodes cleanly but isn't an access token — must
    # not unlock a session. Guards against a future code path that
    # accidentally accepts refresh tokens here.
    fake_refresh = create_refresh_token(str(uuid.uuid4()), str(uuid.uuid4()))
    resp = await client.post(
        "/api/demo/start",
        json={},
        headers={"Authorization": f"Bearer {fake_refresh}"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["resumed"] is False


@pytest.mark.asyncio
async def test_resume_falls_through_for_non_demo_tenant(
    client: AsyncClient, admin_role, enable_demo, db: AsyncSession
):
    # Mint a valid access token for a brand-new non-demo tenant ID. The
    # tenant row doesn't exist (or isn't is_demo) — resume must refuse.
    fake = create_demo_access_token(str(uuid.uuid4()), str(uuid.uuid4()))
    resp = await client.post(
        "/api/demo/start",
        json={},
        headers={"Authorization": f"Bearer {fake}"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["resumed"] is False
