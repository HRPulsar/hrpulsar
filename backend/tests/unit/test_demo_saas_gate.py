"""HRP-391 — the public-demo sandbox is enterprise-only.

Community / self-hosted deployments run with ``deployment_mode=onprem``
(the test env default, pinned in ``tests/conftest.py``); every
``/api/demo/*`` endpoint must return 404 there — indistinguishable from
a route that does not exist. In SaaS the router behaves as before
(``demo_enabled`` kill-switch, Turnstile, throttles).
"""

from __future__ import annotations

import pytest
from app.config import settings
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_demo_start_404_in_onprem(client: AsyncClient):
    assert settings.deployment_mode == "onprem"
    resp = await client.post("/api/demo/start", json={})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_demo_save_access_404_in_onprem(client: AsyncClient):
    resp = await client.post("/api/demo/save-access", json={"email": "a@b.c"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_demo_wrong_method_404_not_405_in_onprem(client: AsyncClient):
    """A wrong-method probe must not fingerprint the surface: the
    pre-routing middleware answers 404 where the registered route would
    otherwise leak a 405."""
    resp = await client.get("/api/demo/start")
    assert resp.status_code == 404
    resp = await client.delete("/api/demo/save-access")
    assert resp.status_code == 404


def test_demo_purge_not_scheduled_in_onprem():
    """The beat schedule is assembled at import time from the env
    (``DEPLOYMENT_MODE=onprem`` in tests) — demo purge entries must be
    absent, while neighbouring core entries stay."""
    from app.core.celery_app import celery

    assert "purge-expired-demo-tenants" not in celery.conf.beat_schedule
    assert "purge-orphan-demo-blobs" not in celery.conf.beat_schedule
    assert "reap-stuck-compgen-sessions" in celery.conf.beat_schedule


@pytest.mark.asyncio
async def test_demo_start_not_gated_in_saas(client: AsyncClient, monkeypatch):
    """In SaaS the gate lets the request through to the normal service
    logic — with ``demo_enabled=False`` (default) that's the 503
    kill-switch, NOT the 404 deployment gate."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "demo_enabled", False)
    resp = await client.post("/api/demo/start", json={})
    assert resp.status_code == 503
