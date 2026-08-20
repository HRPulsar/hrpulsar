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

    monkeypatch.setattr("app.core.email.send_signup_verify_email", _fake_send)
    return sent


@pytest.fixture
def no_rate_limit(monkeypatch):
    async def _noop(_remote_ip):
        return None

    monkeypatch.setattr("app.modules.signup.service._enforce_rate_limit", _noop)


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
        await db.execute(select(SignupRequest).where(SignupRequest.email == email))
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


async def test_repeat_submit_refreshes_demo_snapshot_but_never_clears_it(
    db,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
):
    """A re-submit from a newer sandbox must win (the old one may be
    purged before moderation); a later landing re-submit without a
    snapshot must not clear the stored one."""
    from app.modules.signup.schemas import SignupRequestCreate
    from app.modules.signup.service import create_signup_request

    email = f"resnap-{uuid.uuid4().hex[:8]}@example.com"
    data = SignupRequestCreate(email=email, first_name="Snap")
    sandbox_a, sandbox_b = uuid.uuid4(), uuid.uuid4()

    row = await create_signup_request(
        db, data, remote_ip=None,
        demo_tenant_id_snapshot=sandbox_a, keep_demo_data=True,
    )
    assert row.demo_tenant_id_snapshot == sandbox_a

    row = await create_signup_request(
        db, data, remote_ip=None,
        demo_tenant_id_snapshot=sandbox_b, keep_demo_data=True,
    )
    assert row.demo_tenant_id_snapshot == sandbox_b

    row = await create_signup_request(db, data, remote_ip=None)
    assert row.demo_tenant_id_snapshot == sandbox_b
    assert row.keep_demo_data is False  # latest-submit-wins for the flag


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
    resp = await client.post("/api/signup-request/verify", json={"token": token})
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
    resp = await client.post("/api/signup-request/verify", json={"token": token})
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
    resp = await client.post("/api/signup-request/verify", json={"token": token})
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
    resp = await client.post("/api/signup-request/verify", json={"token": token})
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
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many")

    monkeypatch.setattr("app.modules.signup.service._enforce_rate_limit", _block)
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
    resp = await client.post("/api/signup-request/verify", json={"token": token})
    assert resp.status_code == 404


# ── HRP-538: stuck-moderation reminder ──────────────────────────────────


class _FakeRedis:
    """Stub for the reminder throttle: records SETs, fixed verdict."""

    def __init__(self, set_result):
        self.set_result = set_result
        self.calls: list[tuple[str, bool | None, int | None]] = []

    async def set(self, key, value, nx=None, ex=None):
        self.calls.append((key, nx, ex))
        return self.set_result

    async def aclose(self):
        return None


@pytest.fixture(autouse=True)
def capture_events(monkeypatch):
    """Capture every event-bus publish instead of fanning out to EE.

    Autouse so no test in this module reaches the real bus — on a dev
    machine the EE Slack handlers are subscribed and ``.env`` may hold
    a real bot token.
    """
    events: list[tuple[str, dict]] = []

    async def _fake_publish(event, data):
        events.append((event, data))

    monkeypatch.setattr("app.core.events.publish", _fake_publish)
    return events


@pytest.fixture(autouse=True)
def reminder_redis(monkeypatch):
    """Stub the reminder throttle (SET NX succeeds) — autouse so no
    test touches the real Redis. Tests exercising throttle/outage
    behavior re-patch ``from_url`` inside their own body."""
    fake = _FakeRedis(set_result=True)
    monkeypatch.setattr(
        "app.core.redis.aioredis.from_url",
        lambda *_a, **_kw: fake,
    )
    return fake


def _reminder_events(events) -> list[dict]:
    return [d for e, d in events if e == "signup.moderation_reminder"]


def _verified_long_ago() -> datetime:
    """Past the reminder age gate — a genuinely stuck request."""
    return datetime.now(timezone.utc) - timedelta(hours=2)


async def test_repeat_verify_click_publishes_moderation_reminder(
    client: AsyncClient,
    db,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
    capture_events,
    reminder_redis,
):
    row = SignupRequest(
        email="stuck@example.com",
        first_name="S",
        status="pending_moderation",
        email_verified_at=_verified_long_ago(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    token = create_signup_verify_token(str(row.id))
    resp = await client.post("/api/signup-request/verify", json={"token": token})
    assert resp.status_code == 200
    assert resp.json()["already_verified"] is True

    reminders = _reminder_events(capture_events)
    assert len(reminders) == 1
    assert reminders[0]["signup_request_id"] == str(row.id)
    assert reminders[0]["email"] == "stuck@example.com"
    # Throttle key is scoped to the request id with a 1h TTL.
    key, nx, ex = reminder_redis.calls[0]
    assert key == f"signup:remind:{row.id}"
    assert nx is True
    assert ex == 3600


async def test_repeat_form_submit_publishes_moderation_reminder(
    client: AsyncClient,
    db,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
    capture_events,
    reminder_redis,
):
    row = SignupRequest(
        email="stuck-form@example.com",
        first_name="S",
        status="pending_moderation",
        email_verified_at=_verified_long_ago(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    resp = await client.post(
        "/api/signup-request",
        json={"email": "stuck-form@example.com", "first_name": "S"},
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == str(row.id)

    reminders = _reminder_events(capture_events)
    assert len(reminders) == 1
    assert reminders[0]["signup_request_id"] == str(row.id)
    # The verify email is still (re-)sent — behavior unchanged.
    assert len(stub_signup_email) == 1


async def test_no_reminder_for_pending_email_verify_repeat(
    client: AsyncClient,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
    capture_events,
    reminder_redis,
):
    payload = {"email": "not-verified-yet@example.com", "first_name": "N"}
    first = await client.post("/api/signup-request", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/signup-request", json=payload)
    assert second.status_code == 201

    # Row never reached the queue — nothing to remind about.
    assert _reminder_events(capture_events) == []


async def test_reminder_throttled_by_redis(
    client: AsyncClient,
    db,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
    capture_events,
    monkeypatch,
):
    fake = _FakeRedis(set_result=None)  # SET NX lost — already reminded
    monkeypatch.setattr(
        "app.core.redis.aioredis.from_url",
        lambda *_a, **_kw: fake,
    )
    row = SignupRequest(
        email="throttled@example.com",
        first_name="T",
        status="pending_moderation",
        email_verified_at=_verified_long_ago(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    token = create_signup_verify_token(str(row.id))
    resp = await client.post("/api/signup-request/verify", json={"token": token})
    assert resp.status_code == 200
    assert _reminder_events(capture_events) == []


async def test_reminder_redis_failure_does_not_break_flow(
    client: AsyncClient,
    db,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
    capture_events,
    monkeypatch,
):
    def _boom(*_a, **_kw):
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.core.redis.aioredis.from_url", _boom)
    row = SignupRequest(
        email="redis-down@example.com",
        first_name="R",
        status="pending_moderation",
        email_verified_at=_verified_long_ago(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    token = create_signup_verify_token(str(row.id))
    resp = await client.post("/api/signup-request/verify", json={"token": token})
    # Visitor flow unaffected; reminder silently skipped.
    assert resp.status_code == 200
    assert resp.json()["already_verified"] is True
    assert _reminder_events(capture_events) == []


async def test_no_reminder_within_age_gate(
    client: AsyncClient,
    db,
    stub_signup_email,
    no_rate_limit,
    no_turnstile,
    capture_events,
):
    """A re-click right after verification is a mail-scanner prefetch /
    double click, not a stuck request — no reminder inside the gate."""
    row = SignupRequest(
        email="fresh@example.com",
        first_name="F",
        status="pending_moderation",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    token = create_signup_verify_token(str(row.id))
    resp = await client.post("/api/signup-request/verify", json={"token": token})
    assert resp.status_code == 200
    assert resp.json()["already_verified"] is True
    assert _reminder_events(capture_events) == []
