"""HRP-251 (D3) — ``POST /api/demo/start`` end-to-end.

Covers the happy path (fresh demo tenant + JWT + redirect URL points
at Elena's interview), the master kill-switch (503), the concurrent-
session cap (503), the per-IP throttle (429), Turnstile failure (400),
and that the seed actually lands in the new tenant.
"""

from __future__ import annotations

import time
import uuid

import pytest
from app.config import settings
from app.core.security import decode_token
from app.modules.company.models import Tenant
from app.modules.demo import service as demo_service
from app.modules.recruitment.models import Candidate, Interview, Vacancy
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def enable_demo(monkeypatch, skill_levels):
    """Open the demo endpoint and short-circuit external guards.

    Depends on ``skill_levels`` so the demo seed (which requires origin
    SkillLevel rows) succeeds even when this file runs in isolation —
    same pattern as ``test_demo_rate_limit.py``.

    Turnstile secret stays empty so the verifier degrades to True;
    the per-IP throttle is disabled (0) by default; the concurrent
    cap is generous. Tests that exercise a specific guard override
    just that knob via their own monkeypatch.
    """
    # HRP-391: the demo router 404s outside SaaS.
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "demo_turnstile_secret", "")
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 0)
    # 500 (vs. prod default 50) so the file's many ``/demo/start`` calls
    # plus the new test_demo_resume.py suite don't exhaust the pool when
    # CI runs the whole backend job in a single DB.
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 500)
    monkeypatch.setattr(settings, "demo_initial_credits", 0)
    # HRP-276 / M5: trust the loopback peer so synthetic XFF headers
    # in this file's throttle-keyed tests still take effect.
    monkeypatch.setattr(settings, "demo_trusted_proxies", "127.0.0.0/8")


@pytest.mark.asyncio
async def test_start_returns_201_with_tokens_and_redirect(
    client: AsyncClient, admin_role, enable_demo, db: AsyncSession
):
    resp = await client.post("/api/demo/start", json={})

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert uuid.UUID(body["tenant_id"])
    assert body["redirect_url"] == "/dashboard"

    # HRP-276 / M7: no refresh token + no refresh cookie for demo.
    assert "refresh_token" not in body
    assert "demo_refresh_token" not in resp.cookies

    # The access token must live as long as the demo tenant (same
    # setting drives both) — without this the visitor gets bounced to
    # /login long before the tenant expires.
    payload = decode_token(body["access_token"])
    issued = time.time()
    ttl = settings.demo_session_ttl_seconds
    assert payload["exp"] >= issued + ttl - 30


@pytest.mark.asyncio
async def test_start_provisions_demo_tenant_with_seed(
    client: AsyncClient, admin_role, enable_demo, db: AsyncSession
):
    resp = await client.post("/api/demo/start", json={})
    assert resp.status_code == 201
    tenant_id = uuid.UUID(resp.json()["tenant_id"])

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one()
    assert tenant.is_demo is True
    assert tenant.expires_at is not None
    assert tenant.last_active_at is not None

    # Counts loosened from the original investor seed (3/8/2) — HRP-281
    # extends the demo with additional vacancies / candidates /
    # interviews. The test now pins the lower bound (the original
    # investor pack is still required) and the invariant that at least
    # one interview lands with a completed AI analysis (the demo's
    # first screen relies on it).
    vacancies = (
        await db.execute(select(Vacancy).where(Vacancy.tenant_id == tenant_id))
    ).scalars().all()
    assert len(vacancies) >= 3

    candidates = (
        await db.execute(select(Candidate).where(Candidate.tenant_id == tenant_id))
    ).scalars().all()
    assert len(candidates) >= 8

    interviews = (
        await db.execute(select(Interview).where(Interview.tenant_id == tenant_id))
    ).scalars().all()
    assert len(interviews) >= 2
    assert any(iv.analysis_status == "completed" for iv in interviews)


@pytest.mark.asyncio
async def test_start_pins_ai_content_language_to_platform_default_locale(
    client: AsyncClient, admin_role, enable_demo, monkeypatch, db: AsyncSession
):
    """White-label deployments run with a non-English DEFAULT_LOCALE;
    the demo tenant must be born with an explicit TenantAISettings row
    matching it — otherwise the first AI call would lazily create the
    row with the global English default and demo visitors on a German
    platform would get English AI content."""
    from app.modules.ai_settings.models import TenantAISettings

    monkeypatch.setattr(settings, "available_locales", "de,en")
    monkeypatch.setattr(settings, "default_locale", "de")

    resp = await client.post("/api/demo/start", json={})
    assert resp.status_code == 201, resp.text
    tenant_id = uuid.UUID(resp.json()["tenant_id"])

    row = (
        await db.execute(
            select(TenantAISettings).where(
                TenantAISettings.tenant_id == tenant_id
            )
        )
    ).scalar_one()
    assert row.content_language == "de"


def test_demo_content_language_falls_back_for_unsupported_locale(monkeypatch):
    """Interface locales and AI content languages are orthogonal axes:
    a platform locale the AI layer doesn't support (no entry in the
    ContentLanguage Literal) must fall back to English rather than
    store a value the settings API would refuse to round-trip."""
    monkeypatch.setattr(settings, "default_locale", "fr")
    assert demo_service._demo_content_language() == "en"

    monkeypatch.setattr(settings, "default_locale", "de")
    assert demo_service._demo_content_language() == "de"


@pytest.mark.asyncio
async def test_start_returns_503_when_disabled(
    client: AsyncClient, admin_role, enable_demo, monkeypatch
):
    monkeypatch.setattr(settings, "demo_enabled", False)
    resp = await client.post("/api/demo/start", json={})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_start_returns_503_when_concurrent_limit_reached(
    client: AsyncClient, admin_role, enable_demo, monkeypatch
):
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 0)
    resp = await client.post("/api/demo/start", json={})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_failed_seed_leaves_only_short_lived_tenant(
    admin_role, enable_demo, monkeypatch, db: AsyncSession
):
    """HRP-276 / M4 follow-up: when the outer-tx work (seed / credits
    grant) raises, the already-committed Tenant row from the mini-tx
    must NOT hold a pool slot for the full 4-hour session window. The
    tenant is born with a 5-minute ``expires_at`` and only gets
    extended on the successful path, so a seed failure leaves an
    orphan that the next purge tick (5 min default) can sweep
    automatically.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import delete, select

    # Pre-clean any demo rows so we can assert a definite count below.
    await db.execute(delete(Tenant).where(Tenant.is_demo.is_(True)))
    await db.commit()

    async def _explode(*_args, **_kwargs):
        raise RuntimeError("simulated seed failure")

    monkeypatch.setattr(
        "app.modules.demo.service.clone_seed_into_demo_tenant", _explode
    )

    now = datetime.now(timezone.utc)
    with pytest.raises(RuntimeError, match="simulated seed failure"):
        await demo_service.create_demo_session(
            db, turnstile_token=None, remote_ip=None
        )
    # The mini-tx already committed before the seed failure, so the
    # tenant row exists; the request session may be poisoned, so rollback
    # whatever the failure left in flight before reading back.
    await db.rollback()

    # Tenant row exists but its expires_at is the 5-minute "short" TTL,
    # not the full 4-hour session window.
    rows = (
        await db.execute(
            select(Tenant.id, Tenant.expires_at).where(
                Tenant.is_demo.is_(True)
            )
        )
    ).all()
    assert len(rows) == 1, f"expected exactly one orphan, got {rows}"
    _id, expires_at = rows[0]
    assert expires_at < now + timedelta(minutes=10), (
        f"orphan tenant got full session TTL ({expires_at}); the M4 "
        "follow-up requires the bootstrap to extend expires_at only on "
        "the successful path so a failed seed expires in ~5 min."
    )


@pytest.mark.asyncio
async def test_xff_ignored_when_no_trusted_proxies_configured(
    client: AsyncClient, admin_role, enable_demo, monkeypatch
):
    """HRP-276 / M5: with ``demo_trusted_proxies`` empty the throttle
    keys on the socket peer, not on ``X-Forwarded-For``. Two requests
    from different synthetic XFF IPs share the same per-IP bucket and
    the second one trips the throttle. Pre-fix XFF was honoured
    unconditionally so a script could mint a fresh bucket per request
    by rotating the header.
    """
    monkeypatch.setattr(settings, "demo_trusted_proxies", "")
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 1)

    import redis.asyncio as aioredis

    # Drain any bleed-through from earlier tests.
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.delete("demo:rl:127.0.0.1")
    finally:
        await r.aclose()

    r1 = await client.post(
        "/api/demo/start",
        json={},
        headers={"X-Forwarded-For": "203.0.113.91"},
    )
    r2 = await client.post(
        "/api/demo/start",
        json={},
        headers={"X-Forwarded-For": "203.0.113.92"},
    )
    assert r1.status_code == 201
    assert r2.status_code == 429

    # Cleanup so the loopback bucket doesn't leak across files.
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.delete("demo:rl:127.0.0.1")
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_two_concurrent_demo_start_calls_respect_cap(
    admin_role, enable_demo, monkeypatch
):
    """HRP-276 / M4: with cap=2 two parallel ``create_demo_session``
    calls must both succeed; with cap=1 the loser must get 503. The
    cap-check + tenant insert mini-tx serialises on
    ``pg_advisory_xact_lock`` for the ~ms count window only, so the
    heavy seed runs outside the lock — but the atomic check still
    prevents both winners from breaching the cap.
    """
    import asyncio
    from datetime import datetime, timedelta, timezone

    from fastapi import HTTPException
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from tests.conftest import TEST_DB_URL

    # Each parallel call needs its own session — asyncpg cannot interleave
    # statements on a single connection, so reusing the conftest ``db``
    # fixture would serialise the two coroutines and defeat the test.
    engine = create_async_engine(TEST_DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as cleanup:
        await cleanup.execute(delete(Tenant).where(Tenant.is_demo.is_(True)))
        await cleanup.commit()

    async def _run() -> int | str:
        async with factory() as session:
            try:
                await demo_service.create_demo_session(
                    session, turnstile_token=None, remote_ip=None
                )
            except HTTPException as exc:
                return exc.status_code
            return 201

    # cap=2 → both succeed
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 2)
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 0)
    results = await asyncio.gather(_run(), _run())
    assert sorted(results) == [201, 201]

    # cap=1 → one succeeds, one gets 503
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 1)
    async with factory() as cleanup:
        await cleanup.execute(delete(Tenant).where(Tenant.is_demo.is_(True)))
        await cleanup.commit()
    # Pre-fill the cap so any successful run still gets blocked. Easier
    # signal than racing two empty-pool runs.
    now = datetime.now(timezone.utc)
    pre = Tenant(
        id=uuid.uuid4(),
        name=f"pre-{uuid.uuid4().hex[:6]}",
        slug=f"pre-{uuid.uuid4().hex[:8]}",
        is_demo=True,
        is_active=True,
        expires_at=now + timedelta(hours=2),
        last_active_at=now,
    )
    async with factory() as primer:
        primer.add(pre)
        await primer.commit()
    results = await asyncio.gather(_run(), _run())
    assert all(r == 503 for r in results), results

    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_cap_excludes_inactive_demo_tenants(
    admin_role, enable_demo, monkeypatch, db: AsyncSession
):
    """HRP-276 / M1: a soft-deleted demo tenant (``is_active=False``)
    must not count toward the live-pool cap. Pre-fix the count was
    pinned only on ``expires_at > now`` and an inactive-but-future
    tenant would lock out a fresh session even though it carries no
    live load. Exercised against the private helper to keep the test
    independent of cross-file fixture pollution in the shared DB.
    """
    from datetime import datetime, timedelta, timezone

    from fastapi import HTTPException

    # Wipe any demo tenants the suite has accumulated so the count
    # starts at a known baseline (0 live, 1 ghost).
    from sqlalchemy import delete

    await db.execute(delete(Tenant).where(Tenant.is_demo.is_(True)))
    await db.commit()

    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 1)
    now = datetime.now(timezone.utc)

    # Inactive demo tenant with a future expires_at — pre-fix this row
    # alone fills the pool at cap=1 even though it's been soft-deleted.
    ghost = Tenant(
        id=uuid.uuid4(),
        name=f"ghost-{uuid.uuid4().hex[:6]}",
        slug=f"ghost-{uuid.uuid4().hex[:8]}",
        is_demo=True,
        is_active=False,
        expires_at=now + timedelta(hours=2),
        last_active_at=now,
    )
    db.add(ghost)
    await db.commit()

    # Post-fix the inactive ghost is excluded — guard passes.
    await demo_service._enforce_concurrent_limit(db, now=now)

    # And one active live tenant DOES still count: with cap=1 a second
    # call must raise 503.
    live = Tenant(
        id=uuid.uuid4(),
        name=f"live-{uuid.uuid4().hex[:6]}",
        slug=f"live-{uuid.uuid4().hex[:8]}",
        is_demo=True,
        is_active=True,
        expires_at=now + timedelta(hours=2),
        last_active_at=now,
    )
    db.add(live)
    await db.commit()

    with pytest.raises(HTTPException) as excinfo:
        await demo_service._enforce_concurrent_limit(db, now=now)
    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_start_returns_400_when_turnstile_required_and_missing(
    client: AsyncClient, admin_role, enable_demo, monkeypatch
):
    """Configuring a Turnstile secret flips the verifier from no-op to
    enforcement; a request without a token must fail."""
    monkeypatch.setattr(settings, "demo_turnstile_secret", "test-secret")
    resp = await client.post("/api/demo/start", json={})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_start_returns_429_when_rate_limit_exceeded(
    client: AsyncClient, admin_role, enable_demo, monkeypatch
):
    """Throttle is per-IP via Redis INCR; pre-loading the counter
    above the limit makes the next call 429 without burning real
    tenants on the test DB."""
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 1)

    # Drive the counter manually so the test stays deterministic.
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.set("demo:rl:127.0.0.1", "5", ex=3600)
    finally:
        await r.aclose()

    resp = await client.post(
        "/api/demo/start",
        json={},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    assert resp.status_code == 429

    # Cleanup so the value doesn't bleed into other tests.
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.delete("demo:rl:127.0.0.1")
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_start_falls_back_to_request_client_on_empty_xff(
    client: AsyncClient, admin_role, enable_demo, monkeypatch
):
    """A leading-comma XFF (empty first hop) used to silently disable
    the throttle by returning None — the helper must fall through to
    ``request.client.host`` instead."""
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 1)

    import redis.asyncio as aioredis

    # The TestClient bound to ASGITransport sets request.client.host
    # to ``127.0.0.1``; pre-load THAT key over the limit and the next
    # call must 429 even though the XFF first hop is empty.
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.set("demo:rl:127.0.0.1", "10", ex=3600)
    finally:
        await r.aclose()

    resp = await client.post(
        "/api/demo/start",
        json={},
        headers={"X-Forwarded-For": ", 10.0.0.1"},
    )
    assert resp.status_code == 429

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.delete("demo:rl:127.0.0.1")
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_start_survives_skipped_seed(
    client: AsyncClient, admin_role, enable_demo, monkeypatch
):
    """A short-circuiting seed must not break session creation."""

    async def _fake_seed(*args, **kwargs):
        return {
            "vacancies": 0,
            "candidates": 0,
            "interviews": 0,
            "skipped": True,
        }

    monkeypatch.setattr(
        demo_service, "clone_seed_into_demo_tenant", _fake_seed
    )

    resp = await client.post("/api/demo/start", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert body["redirect_url"] == "/dashboard"
