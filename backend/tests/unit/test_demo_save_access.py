"""``POST /api/demo/save-access`` without a name (HRP-1161).

The demo card asks for an email only, so the name is optional on the
save-access path; the landing form keeps requiring it.
"""

from __future__ import annotations

import uuid

import pytest
from app.config import settings
from app.modules.signup.models import SignupRequest
from httpx import AsyncClient
from sqlalchemy import select
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


@pytest.fixture
def quiet_signup(monkeypatch):
    """No captcha, rate limit or verify email — the tests are about the name."""

    async def _ok(_token, *, remote_ip=None):
        return True

    async def _noop(_remote_ip):
        return None

    monkeypatch.setattr("app.modules.signup.service._verify_turnstile", _ok)
    monkeypatch.setattr("app.modules.signup.service._enforce_rate_limit", _noop)
    monkeypatch.setattr(
        "app.core.email.send_signup_verify_email", lambda *_a, **_k: True
    )


@pytest.mark.asyncio
async def test_save_access_needs_no_name(
    client: AsyncClient,
    admin_role,
    enable_demo,
    quiet_signup,
    db: AsyncSession,
):
    start = await client.post("/api/demo/start", json={})
    assert start.status_code == 201
    email = f"nameless-{uuid.uuid4().hex[:8]}@example.com"

    resp = await client.post(
        "/api/demo/save-access",
        json={"email": email, "keep_demo_data": True},
        headers={"Authorization": f"Bearer {start.json()['access_token']}"},
    )

    assert resp.status_code == 201, resp.text
    row = (
        await db.execute(select(SignupRequest).where(SignupRequest.email == email))
    ).scalar_one()
    assert row.first_name is None
    assert row.keep_demo_data is True
    assert str(row.demo_tenant_id_snapshot) == start.json()["tenant_id"]


@pytest.mark.asyncio
async def test_landing_form_still_requires_the_name(client: AsyncClient, quiet_signup):
    resp = await client.post(
        "/api/signup-request", json={"email": "noname@example.com"}
    )
    assert resp.status_code == 422
    assert "first_name" in resp.text
