"""Integration test helpers for auth flows with email verification."""

import uuid

import pytest
from app.core.security import create_email_verification_token
from app.modules.auth.models import User
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(autouse=True)
def _pin_classic_email_flow(monkeypatch):
    """HRP-390: ``register()`` auto-verifies on onprem installs without an
    email provider. Integration flows exercise the classic
    register → verify → login path, so pin a configured provider (with
    delivery stubbed to succeed) regardless of the local ``.env``."""
    monkeypatch.setattr("app.core.email.email_provider_configured", lambda: True)
    monkeypatch.setattr(
        "app.modules.auth.service.send_verification_email", lambda *a, **k: True
    )


async def register_and_verify(
    client: AsyncClient, db: AsyncSession, email: str | None = None
) -> dict:
    """Register a user, verify their email, and return the token response.

    Returns dict with access_token, refresh_token, and user.
    """
    email = email or f"test-{uuid.uuid4().hex[:8]}@example.com"
    company_name = f"Corp-{uuid.uuid4().hex[:6]}"

    # 1. Register (returns pending_verification)
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "first_name": "Test",
            "last_name": "User",
            "company_name": company_name,
        },
    )
    assert resp.status_code == 201
    reg_data = resp.json()
    assert reg_data["pending_verification"] is True

    # 2. Find user in DB to get their ID for the verification token
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one()

    # 3. Create verification token and verify email via API
    token = create_email_verification_token(str(user.id))
    verify_resp = await client.post("/api/auth/verify-email", json={"token": token})
    assert verify_resp.status_code == 200

    return verify_resp.json()
