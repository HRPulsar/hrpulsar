"""Unit tests for the lightweight `/health/celery` endpoint.

The full `/health` route reads Redis, DB, and S3. The dedicated Celery probe
exists so the AI generation drawer can surface a "Worker offline" warning
without paying for the heavier full-stack check on every drawer open.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core import health
from starlette.requests import Request


def _build_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health/celery",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope=scope)


@pytest.mark.asyncio
async def test_health_celery_ok(monkeypatch):
    async def fake_check():
        return {
            "status": "ok",
            "mode": "heartbeat",
            "last_seen": "2026-05-04T00:00:00",
        }

    monkeypatch.setattr(health, "_check_celery", fake_check)
    response = await health.health_celery(_build_request())
    assert response.status_code == 200
    body = response.body
    assert b'"available":true' in body
    assert b'"mode":"heartbeat"' in body
    assert b'"last_seen":"2026-05-04T00:00:00"' in body


@pytest.mark.asyncio
async def test_health_celery_ok_via_control(monkeypatch):
    """HRP-46: when the heartbeat key is stale but the worker answers ping,
    the endpoint still reports available with mode=control."""

    async def fake_check():
        return {"status": "ok", "mode": "control"}

    monkeypatch.setattr(health, "_check_celery", fake_check)
    response = await health.health_celery(_build_request())
    assert response.status_code == 200
    body = response.body
    assert b'"available":true' in body
    assert b'"mode":"control"' in body
    assert b"last_seen" not in body


@pytest.mark.asyncio
async def test_health_celery_offline(monkeypatch):
    async def fake_check():
        return {"status": "error", "error": "no recent heartbeat"}

    monkeypatch.setattr(health, "_check_celery", fake_check)
    response = await health.health_celery(_build_request())
    assert response.status_code == 503
    assert b'"available":false' in response.body
    assert b'"error":"no recent heartbeat"' in response.body


class _StubRedis:
    """Minimal async-redis stand-in for `_check_celery` tests."""

    def __init__(self, value: bytes | None):
        self._value = value
        self.get = AsyncMock(return_value=value)
        self.aclose = AsyncMock()


def _patch_redis(monkeypatch, value: bytes | None) -> None:
    stub = _StubRedis(value)
    import redis.asyncio as aioredis  # ensure real module is loaded first

    monkeypatch.setattr(aioredis, "from_url", lambda *_args, **_kw: stub)


def _patch_celery_ping(monkeypatch, result):
    """Stub `app.core.celery_app.celery.control.inspect(...).ping()`."""
    fake_inspect = MagicMock()
    if isinstance(result, Exception):
        fake_inspect.ping = MagicMock(side_effect=result)
    else:
        fake_inspect.ping = MagicMock(return_value=result)
    fake_control = MagicMock()
    fake_control.inspect = MagicMock(return_value=fake_inspect)

    # Patch the live `celery` attribute on app.core.celery_app if it's already
    # imported; otherwise inject a stub module so the import inside
    # `_check_celery` resolves to our fake.
    if "app.core.celery_app" in sys.modules:
        monkeypatch.setattr(
            sys.modules["app.core.celery_app"].celery, "control", fake_control
        )
    else:
        fake_module = MagicMock()
        fake_module.celery = MagicMock(control=fake_control)
        monkeypatch.setitem(sys.modules, "app.core.celery_app", fake_module)


@pytest.mark.asyncio
async def test_check_celery_uses_heartbeat_when_present(monkeypatch):
    _patch_redis(monkeypatch, b"2026-05-16T12:00:00")
    result = await health._check_celery()
    assert result == {
        "status": "ok",
        "mode": "heartbeat",
        "last_seen": "2026-05-16T12:00:00",
    }


@pytest.mark.asyncio
async def test_check_celery_falls_back_to_control_ping(monkeypatch):
    """HRP-46: heartbeat task can sit queued behind a long AI job — the
    control-channel ping must still confirm the worker is alive."""
    _patch_redis(monkeypatch, None)
    _patch_celery_ping(monkeypatch, [{"celery@host": {"ok": "pong"}}])
    result = await health._check_celery()
    assert result == {"status": "ok", "mode": "control"}


@pytest.mark.asyncio
async def test_check_celery_reports_offline_when_ping_empty(monkeypatch):
    _patch_redis(monkeypatch, None)
    _patch_celery_ping(monkeypatch, None)
    result = await health._check_celery()
    assert result == {"status": "error", "error": "no recent heartbeat"}


@pytest.mark.asyncio
async def test_check_celery_reports_offline_when_ping_raises(monkeypatch):
    _patch_redis(monkeypatch, None)
    _patch_celery_ping(monkeypatch, RuntimeError("broker down"))
    result = await health._check_celery()
    assert result["status"] == "error"
    assert "ping failed" in result["error"]
    assert "broker down" in result["error"]
