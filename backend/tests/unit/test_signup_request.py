"""HRP-259 / HRP-264 (M1 + M6): signup-request endpoint + verify flow."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from app.core.security import create_signup_verify_token
from app.modules.signup.models import SignupRequest
from httpx import AsyncClient
from sqlalchemy import select


@pytest.fixture
def stub_signup_email(monkeypatch):
    """Skip the real email helper — tests focus on DB transitions."""
    sent: list[tuple[str, str]] = []

    def _fake_send(to: str, token: str, **_kwargs) -> bool:
        sent.append((to, token))
        return True

    monkeypatch.setattr(
        "app.core.email.send_signup_verify_email", _fake_send
    )
    return sent


@pytest.fixture
def no_rate_limit(monkeypatch):
    async def _noop(_remote_ip):
        return None

    monkeypatch.setattr(
        "app.modules.signup.service._enforce_rate_limit", _noop
    )


@pytest.fixture
def no_turnstile(monkeypatch):
    async def _ok(_token, *, remote_ip=None):
        return True

    monkeypatch.setattr("app.modules.signup.service._verify_turnstile", _ok)


async def test_create_signup_request_persists_row_and_sends_email(
    client: AsyncClient,
    db,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
):
    email = f"lead-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/signup-request",
        json={
            "email": email,
            "first_name": "Lead",
            "last_name": "Demo",
            "company_name": "Acme",
            "role": "founder",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == email
    assert body["status"] == "pending_email_verify"

    row = (
        await db.execute(
            select(SignupRequest).where(SignupRequest.email == email)
        )
    ).scalar_one()
    assert row.status == "pending_email_verify"
    assert row.source == "landing"
    assert row.company_name == "Acme"

    assert len(stub_signup_email) == 1
    sent_to, sent_token = stub_signup_email[0]
    assert sent_to == email
    assert isinstance(sent_token, str) and sent_token


async def test_create_signup_request_repeat_for_pending_resends(
    client: AsyncClient,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
):
    payload = {"email": "dup@example.com", "first_name": "Dup"}
    first = await client.post("/api/signup-request", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/signup-request", json=payload)
    assert second.status_code == 201
    # Same row id — repeat submit reuses the pending request.
    assert first.json()["id"] == second.json()["id"]
    assert len(stub_signup_email) == 2  # both calls (re-)sent the email


async def test_create_signup_request_409_when_already_finalized(
    client: AsyncClient,
    db,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
):
    row = SignupRequest(
        email="closed@example.com",
        first_name="Closed",
        status="approved",
    )
    db.add(row)
    await db.commit()

    resp = await client.post(
        "/api/signup-request",
        json={"email": "closed@example.com", "first_name": "Closed"},
    )
    assert resp.status_code == 409


async def test_verify_signup_request_flips_to_pending_moderation(
    client: AsyncClient,
    db,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
):
    row = SignupRequest(
        email="verify@example.com",
        first_name="V",
        status="pending_email_verify",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    token = create_signup_verify_token(str(row.id))
    resp = await client.post(
        "/api/signup-request/verify", json={"token": token}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending_moderation"
    assert body["already_verified"] is False

    await db.refresh(row)
    assert row.status == "pending_moderation"
    assert row.email_verified_at is not None


async def test_verify_signup_request_is_idempotent_on_repeat(
    client: AsyncClient,
    db,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
):
    row = SignupRequest(
        email="verify-2@example.com",
        first_name="V",
        status="pending_moderation",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()

    token = create_signup_verify_token(str(row.id))
    resp = await client.post(
        "/api/signup-request/verify", json={"token": token}
    )
    assert resp.status_code == 200
    assert resp.json()["already_verified"] is True


async def test_verify_signup_request_rejects_expired_token(
    client: AsyncClient,
    db,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
):
    from app.config import settings

    row = SignupRequest(
        email="expired@example.com",
        first_name="E",
        status="pending_email_verify",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    expired_payload = {
        "sub": str(row.id),
        "type": "signup_verify",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
    }
    token = jwt.encode(
        expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    resp = await client.post(
        "/api/signup-request/verify", json={"token": token}
    )
    assert resp.status_code == 401


async def test_verify_signup_request_rejects_finalized(
    client: AsyncClient,
    db,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
):
    row = SignupRequest(
        email="approved@example.com",
        first_name="A",
        status="approved",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    token = create_signup_verify_token(str(row.id))
    resp = await client.post(
        "/api/signup-request/verify", json={"token": token}
    )
    assert resp.status_code == 409


async def test_create_signup_request_returns_429_when_rate_limited(
    client: AsyncClient,
    monkeypatch,
    stub_signup_email,
    no_turnstile,
):
    """Inject a rate-limit raiser to verify the endpoint propagates 429."""
    from fastapi import HTTPException, status

    async def _block(_remote_ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "too many"
        )

    monkeypatch.setattr(
        "app.modules.signup.service._enforce_rate_limit", _block
    )
    resp = await client.post(
        "/api/signup-request",
        json={"email": "rate@example.com", "first_name": "R"},
    )
    assert resp.status_code == 429


async def test_verify_signup_request_404_for_missing_row(
    client: AsyncClient,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
):
    token = create_signup_verify_token(str(uuid.uuid4()))
    resp = await client.post(
        "/api/signup-request/verify", json={"token": token}
    )
    assert resp.status_code == 404
