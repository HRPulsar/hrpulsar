"""HRP-262 / HRP-264 (M4 + M6): POST /auth/magic-login.

Covers the happy path, replay protection (Redis SETNX), token-type
guard, and an expired-token rejection. Redis is monkeypatched with an
in-memory stand-in so tests run without an actual Redis container.

HRP-1161: the account's first entry sets its password - the link works
once, and the account was made with a random one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.config import settings
from app.core.security import create_magic_login_token, create_reset_token
from app.modules.auth.models import User
from httpx import AsyncClient

PASSWORD = "a-password-of-my-own"


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
    resp = await client.post(
        "/api/auth/magic-login", json={"token": token, "new_password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["id"] == str(user.id)
    assert body["refresh_token"]
    # Minted after the password moved the token version, so it works.
    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200, me.text


async def test_the_first_entry_ends_a_reset_link_issued_before_it(
    client: AsyncClient, user, fake_redis
):
    """The password set on entry is a password change: a reset link from
    before it must not replace it."""
    reset = create_reset_token(str(user.id), user.token_version)
    token = create_magic_login_token(str(user.id), str(user.tenant_id))
    entered = await client.post(
        "/api/auth/magic-login", json={"token": token, "new_password": PASSWORD}
    )
    assert entered.status_code == 200, entered.text

    resp = await client.post(
        "/api/auth/reset-password",
        json={"token": reset, "new_password": "somebody-elses-1"},
    )
    assert resp.status_code == 400, resp.text


async def test_first_entry_asks_for_a_password_and_keeps_the_link(
    client: AsyncClient, user, fake_redis
):
    """Without a password the link is not burnt: the page shows its form and
    sends the same link again with the password - which then signs in by
    itself, without the link."""
    token = create_magic_login_token(str(user.id), str(user.tenant_id))
    asked = await client.post("/api/auth/magic-login", json={"token": token})
    assert asked.status_code == 409, asked.text
    assert asked.json()["code"] == "magic_login_password_required"
    assert fake_redis == set()

    entered = await client.post(
        "/api/auth/magic-login", json={"token": token, "new_password": PASSWORD}
    )
    assert entered.status_code == 200, entered.text

    again = await client.post(
        "/api/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert again.status_code == 200, again.text


async def test_a_short_password_is_refused_and_the_link_kept(
    client: AsyncClient, user, fake_redis
):
    token = create_magic_login_token(str(user.id), str(user.tenant_id))
    resp = await client.post(
        "/api/auth/magic-login", json={"token": token, "new_password": "short"}
    )
    assert resp.status_code == 422, resp.text
    assert fake_redis == set()


async def test_a_password_bcrypt_cannot_take_is_refused_and_the_link_kept(
    client: AsyncClient, user, fake_redis
):
    """bcrypt hashes 72 bytes at most: the refusal comes before the link is
    burnt, or the applicant would be left with neither link nor password."""
    token = create_magic_login_token(str(user.id), str(user.tenant_id))
    resp = await client.post(
        "/api/auth/magic-login", json={"token": token, "new_password": "p" * 73}
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "password_too_long"
    assert fake_redis == set()

    entered = await client.post(
        "/api/auth/magic-login", json={"token": token, "new_password": PASSWORD}
    )
    assert entered.status_code == 200, entered.text


async def test_an_account_that_signed_in_before_needs_no_password(
    client: AsyncClient, db, user, fake_redis
):
    """Only the first entry sets a password: the link never replaces one the
    account already uses."""
    from sqlalchemy import update

    await db.execute(
        update(User).where(User.id == user.id).values(first_login_at=datetime.now(UTC))
    )
    await db.commit()
    token = create_magic_login_token(str(user.id), str(user.tenant_id))
    resp = await client.post(
        "/api/auth/magic-login", json={"token": token, "new_password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text

    old = await client.post(
        "/api/auth/login", json={"email": user.email, "password": "testpass123"}
    )
    assert old.status_code == 200, old.text


async def test_an_account_that_signed_in_before_enters_by_the_link_alone(
    client: AsyncClient, db, user, fake_redis
):
    """What the page's first request is: the link, no password."""
    from sqlalchemy import update

    await db.execute(
        update(User).where(User.id == user.id).values(first_login_at=datetime.now(UTC))
    )
    await db.commit()
    token = create_magic_login_token(str(user.id), str(user.tenant_id))
    resp = await client.post("/api/auth/magic-login", json={"token": token})
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]


async def test_magic_login_replay_returns_401(
    client: AsyncClient, user, fake_redis
):
    token = create_magic_login_token(str(user.id), str(user.tenant_id))
    body = {"token": token, "new_password": PASSWORD}
    first = await client.post("/api/auth/magic-login", json=body)
    assert first.status_code == 200
    second = await client.post("/api/auth/magic-login", json=body)
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
    resp = await client.post(
        "/api/auth/magic-login", json={"token": token, "new_password": PASSWORD}
    )
    assert resp.status_code == 503, resp.text
    # Not let through, and no password set either.
    login = await client.post(
        "/api/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert login.status_code == 401, login.text


async def test_magic_login_rejects_wrong_token_type(
    client: AsyncClient, user, fake_redis
):
    bad_payload = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "type": "email_verify",  # wrong type
        "jti": "abc",
        "exp": datetime.now(UTC) + timedelta(hours=1),
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
        "exp": datetime.now(UTC) - timedelta(minutes=1),
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
