"""HRP-262 / HRP-264 (M4 + M6): POST /auth/magic-login.

Covers the happy path, replay protection (Redis SETNX), token-type
guard, and an expired-token rejection. Redis is monkeypatched with an
in-memory stand-in so tests run without an actual Redis container.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from app.config import settings
from app.core.security import create_magic_login_token
from app.modules.auth.models import User
from httpx import AsyncClient


@pytest.fixture
def fake_redis(monkeypatch):
    """Replace ``redis.asyncio.from_url`` with a tiny in-memory client.

    Mirrors the SETNX-EX semantics the service relies on without
    requiring a live Redis. The set of used JTIs survives across calls
    in the same test so replay attempts are detected.
    """
    used: set[str] = set()

    class _FakeClient:
        async def set(self, key: str, _value: str, *, nx: bool, ex: int):
            if nx and key in used:
                return None
            used.add(key)
            return True

        async def aclose(self):
            return None

    def _factory(_url, decode_responses=True):  # noqa: ARG001
        return _FakeClient()

    monkeypatch.setattr("redis.asyncio.from_url", _factory)
    return used


async def test_magic_login_happy_path_issues_tokens(
    client: AsyncClient, user, fake_redis
):
    token = create_magic_login_token(str(user.id), str(user.tenant_id))
    resp = await client.post("/api/auth/magic-login", json={"token": token})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["id"] == str(user.id)
    assert body["access_token"]
    assert body["refresh_token"]


async def test_magic_login_replay_returns_401(
    client: AsyncClient, user, fake_redis
):
    token = create_magic_login_token(str(user.id), str(user.tenant_id))
    first = await client.post("/api/auth/magic-login", json={"token": token})
    assert first.status_code == 200
    second = await client.post("/api/auth/magic-login", json={"token": token})
    assert second.status_code == 401


async def test_magic_login_fails_closed_when_redis_down(
    client: AsyncClient, user, monkeypatch
):
    """P3-46: a Redis outage must block sign-in (fail closed), not wave the
    one-time link through where it could be replayed."""

    class _BrokenClient:
        async def set(self, *a, **kw):
            raise ConnectionError("redis down")

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "redis.asyncio.from_url", lambda *a, **kw: _BrokenClient()
    )
    token = create_magic_login_token(str(user.id), str(user.tenant_id))
    resp = await client.post("/api/auth/magic-login", json={"token": token})
    assert resp.status_code == 503, resp.text


async def test_magic_login_rejects_wrong_token_type(
    client: AsyncClient, user, fake_redis
):
    bad_payload = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "type": "email_verify",  # wrong type
        "jti": "abc",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    token = jwt.encode(
        bad_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    resp = await client.post("/api/auth/magic-login", json={"token": token})
    assert resp.status_code == 401


async def test_magic_login_rejects_expired_token(
    client: AsyncClient, user, fake_redis
):
    expired_payload = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "type": "magic_login",
        "jti": "expired",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
    }
    token = jwt.encode(
        expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    resp = await client.post("/api/auth/magic-login", json={"token": token})
    assert resp.status_code == 401


async def test_magic_login_rejects_inactive_user(
    client: AsyncClient, db, user, fake_redis
):
    # Flip the user to inactive so the service refuses to issue tokens
    # even with a valid JWT. Mirrors the existing /auth/login behaviour.
    row = await db.get(User, user.id)
    row.is_active = False
    await db.commit()

    token = create_magic_login_token(str(user.id), str(user.tenant_id))
    resp = await client.post("/api/auth/magic-login", json={"token": token})
    assert resp.status_code == 401
