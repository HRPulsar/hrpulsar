"""``POST /api/demo/switch-view`` — the demo persona switcher (HRP-612).

Covers: admin → employee → admin round-trip inside one demo tenant,
rejection of non-demo bearers, and the 404 gate outside saas mode.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.config import settings
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User
from app.modules.company.models import Tenant
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


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


async def _paid_account_headers(db: AsyncSession) -> dict[str, str]:
    """Bearer for a regular (non-demo) tenant's user."""
    suffix = uuid.uuid4().hex[:6]
    tenant = Tenant(name=f"Paid {suffix}", slug=f"paid-{suffix}")
    db.add(tenant)
    await db.flush()
    user = User(
        email=f"paid-{suffix}@example.com",
        password_hash=hash_password("pw12345678"),
        first_name="Paid",
        last_name="User",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.commit()
    return {
        "Authorization": f"Bearer {create_access_token(str(user.id), str(tenant.id))}"
    }


@pytest.mark.asyncio
async def test_switch_to_employee_and_back(
    client: AsyncClient, admin_role, enable_demo, db: AsyncSession
):
    start = await client.post("/api/demo/start", json={})
    assert start.status_code == 201
    admin_token = start.json()["access_token"]
    tenant_id = start.json()["tenant_id"]

    switched = await client.post(
        "/api/demo/switch-view",
        json={"persona": "employee"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert switched.status_code == 200, switched.text
    body = switched.json()
    assert body["persona"] == "employee"
    assert body["tenant_id"] == tenant_id
    employee_token = body["access_token"]
    assert employee_token != admin_token

    # The employee token resolves to Carlos Mendez in the same tenant.
    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {employee_token}"}
    )
    assert me.status_code == 200
    assert me.json()["first_name"] == "Carlos"

    # Round-trip back to the admin persona.
    back = await client.post(
        "/api/demo/switch-view",
        json={"persona": "admin"},
        headers={"Authorization": f"Bearer {employee_token}"},
    )
    assert back.status_code == 200, back.text
    assert back.json()["persona"] == "admin"
    assert back.json()["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_non_demo_token_rejected(
    client: AsyncClient, enable_demo, db: AsyncSession
):
    headers = await _paid_account_headers(db)
    resp = await client.post(
        "/api/demo/switch-view",
        json={"persona": "employee"},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "demo_switch_requires_demo_session" in resp.text


@pytest.mark.asyncio
async def test_expired_demo_tenant_rejected(
    client: AsyncClient, admin_role, enable_demo, db: AsyncSession
):
    start = await client.post("/api/demo/start", json={})
    assert start.status_code == 201
    token = start.json()["access_token"]
    tenant = await db.get(Tenant, start.json()["tenant_id"])
    tenant.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()

    resp = await client.post(
        "/api/demo/switch-view",
        json={"persona": "employee"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_switch_view_hidden_outside_saas(
    client: AsyncClient, monkeypatch, db: AsyncSession
):
    monkeypatch.setattr(settings, "deployment_mode", "onprem")
    headers = await _paid_account_headers(db)
    resp = await client.post(
        "/api/demo/switch-view",
        json={"persona": "employee"},
        headers=headers,
    )
    assert resp.status_code == 404
