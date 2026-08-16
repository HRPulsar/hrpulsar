"""HRP-255 (D7) — organic throttle behavior on ``POST /api/demo/start``.

The existing ``test_demo_start.py`` covers the throttle by pre-loading
the Redis counter above the limit. D7 widens the coverage to the
organic loop — INCR runs naturally per request, neighbouring IPs keep
their own buckets, and an expired TTL resets the count.

Every test cleans up the Redis keys it touches so a half-finished run
can't bleed into the next file.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from app.config import settings
from httpx import AsyncClient


@pytest.fixture
def enable_demo(monkeypatch, skill_levels):
    """Open the endpoint and bypass the bot guard so the only thing the
    test exercises is the per-IP throttle.

    Depends on ``skill_levels`` so the demo seed (which requires origin
    SkillLevel rows) succeeds even when this file runs in isolation — the
    shared test DB otherwise only has them if an earlier file seeded them.

    ``demo_max_concurrent_sessions`` is set far above this file's needs
    on purpose — the test DB persists between files, so demo tenants
    seeded by ``test_demo_start.py`` / ``test_demo_lifecycle_e2e.py``
    stay alive (``expires_at`` defaults to hours in the future) and
    count toward ``_enforce_concurrent_limit``. A tight cap here would
    have these tests start returning 503 once the file count grows.
    """
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "demo_turnstile_secret", "")
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 500)
    monkeypatch.setattr(settings, "demo_initial_credits", 0)
    # HRP-276 / M5: the ASGI test transport sets ``request.client.host``
    # to 127.0.0.1, so XFF would be ignored by default. Trust the loop-
    # back range so the synthetic ``X-Forwarded-For`` IPs below still
    # drive the per-IP throttle.
    monkeypatch.setattr(settings, "demo_trusted_proxies", "127.0.0.0/8")


@pytest_asyncio.fixture
async def redis_cleanup() -> AsyncIterator[list[str]]:
    """Tracks the rate-limit keys each test touches and wipes them on
    teardown so subsequent tests start at a clean counter."""
    touched: list[str] = []
    yield touched
    if not touched:
        return
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    # Both the DELETE and the close are best-effort — a Redis blip
    # between the test body and teardown must not surface as a
    # fixture-finalizer ERROR that masks the actual test outcome.
    try:
        with contextlib.suppress(Exception):
            await r.delete(*touched)
    finally:
        with contextlib.suppress(Exception):
            await r.aclose()


async def _start_with_ip(client: AsyncClient, ip: str) -> int:
    """Call ``POST /api/demo/start`` carrying a synthetic ``X-Forwarded-
    For`` so the throttle keys on a stable, test-controllable IP."""
    resp = await client.post(
        "/api/demo/start",
        json={},
        headers={"X-Forwarded-For": ip},
    )
    return resp.status_code


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_throttle_blocks_after_organic_burst(
    client: AsyncClient,
    admin_role,
    enable_demo,
    monkeypatch,
    redis_cleanup: list[str],
):
    """Drive the throttle through Redis the same way a real client
    would: each request bumps the counter, and the (limit+1)th request
    gets 429. Picking a small limit (2) keeps the test fast — the same
    code path runs for the production 5/hour value."""
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 2)

    ip = "203.0.113.10"
    redis_cleanup.append(f"demo:rl:{ip}")

    # First two requests stay under the limit and provision tenants.
    s1 = await _start_with_ip(client, ip)
    s2 = await _start_with_ip(client, ip)
    s3 = await _start_with_ip(client, ip)

    assert s1 == 201, f"first request unexpectedly {s1}"
    assert s2 == 201, f"second request unexpectedly {s2}"
    assert s3 == 429, f"third request must trip the throttle; got {s3}"


@pytest.mark.asyncio
async def test_throttle_buckets_are_per_ip(
    client: AsyncClient,
    admin_role,
    enable_demo,
    monkeypatch,
    redis_cleanup: list[str],
):
    """Different XFF source IPs key into different Redis buckets — a
    burst from one neighbour must not lock out an unrelated client."""
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 1)

    ip_a = "203.0.113.20"
    ip_b = "203.0.113.21"
    redis_cleanup.extend([f"demo:rl:{ip_a}", f"demo:rl:{ip_b}"])

    # Tenant A burns its quota.
    assert await _start_with_ip(client, ip_a) == 201
    assert await _start_with_ip(client, ip_a) == 429

    # Tenant B should not have inherited A's counter.
    assert await _start_with_ip(client, ip_b) == 201


@pytest.mark.asyncio
async def test_throttle_resets_when_ttl_elapses(
    client: AsyncClient,
    admin_role,
    enable_demo,
    monkeypatch,
    redis_cleanup: list[str],
):
    """Counter is stored with a TTL — once that TTL passes the bucket
    resets and the same IP can start again. The 3600 s production TTL
    is impractical for a test, so we drop the key directly to simulate
    expiry; what we're proving is that the throttle has no second
    persistent ledger beyond the Redis key."""
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 1)

    ip = "203.0.113.30"
    key = f"demo:rl:{ip}"
    redis_cleanup.append(key)

    assert await _start_with_ip(client, ip) == 201
    assert await _start_with_ip(client, ip) == 429

    # Force-expire the bucket; production reaches this state when the
    # TTL elapses naturally.
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.delete(key)
    finally:
        await r.aclose()

    assert await _start_with_ip(client, ip) == 201


@pytest.mark.asyncio
async def test_throttle_disabled_when_limit_is_zero(
    client: AsyncClient,
    admin_role,
    enable_demo,
    monkeypatch,
    redis_cleanup: list[str],
):
    """``DEMO_RATE_LIMIT_PER_IP_PER_HOUR=0`` short-circuits the guard
    entirely — the helper returns before touching Redis at all. Sending
    a burst from the same IP keeps producing 201s."""
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 0)

    ip = "203.0.113.40"
    redis_cleanup.append(f"demo:rl:{ip}")

    # Sequential, not ``asyncio.gather``: the test session is bound to a
    # single ``AsyncSession``, and a concurrent ``db.add`` from two
    # parallel coroutines lands inside the same flush and raises
    # "Session is already flushing". Serial calls preserve the test's
    # intent — proves the throttle stays inert at limit=0 — without
    # tripping the test fixture.
    s1 = await _start_with_ip(client, ip)
    s2 = await _start_with_ip(client, ip)
    s3 = await _start_with_ip(client, ip)
    assert (s1, s2, s3) == (201, 201, 201)


@pytest.mark.asyncio
async def test_full_pool_does_not_burn_rate_limit_counter(
    client: AsyncClient,
    admin_role,
    enable_demo,
    monkeypatch,
    redis_cleanup: list[str],
):
    """HRP-276 / M2: when ``/api/demo/start`` is refused because the
    concurrent pool is full, the IP's hourly INCR allowance must be
    untouched. Pre-fix the INCR ran first, so a NAT-behind cluster
    bouncing off a full pool at peak times burned its 5/hour budget
    and locked itself out for the rest of the window.
    """
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 0)
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 3)

    ip = "203.0.113.55"
    key = f"demo:rl:{ip}"
    redis_cleanup.append(key)

    # Three retries against a closed pool — each gets 503, none burns
    # an INCR token.
    for _ in range(3):
        resp = await client.post(
            "/api/demo/start",
            json={},
            headers={"X-Forwarded-For": ip},
        )
        assert resp.status_code == 503

    # Open the pool back up — the IP still has its full 3/hour budget,
    # so a fresh request proceeds and INCR becomes the active brake.
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 500)
    resp = await client.post(
        "/api/demo/start",
        json={},
        headers={"X-Forwarded-For": ip},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_throttle_fails_closed_when_redis_unavailable(
    client: AsyncClient,
    admin_role,
    enable_demo,
    monkeypatch,
):
    """HRP-276 / H3: a Redis flake must NOT silently lift the throttle.

    Pre-fix the helper logged a warning and let the request through —
    which meant a single Redis hiccup turned the public demo into an
    unlimited tenant factory until the cache recovered. Post-fix the
    helper refuses with 503 so the only application brake against
    automated abuse stays effective.
    """
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 5)

    def _explode(*_args, **_kwargs):
        raise ConnectionError("redis dead")

    # ``from_url`` is invoked at call time inside the shared
    # ``app.core.redis.redis_client`` helper, so patching the symbol
    # there is enough — no need to reach into the caller.
    import app.core.redis as redis_helper

    monkeypatch.setattr(redis_helper.aioredis, "from_url", _explode)

    resp = await client.post(
        "/api/demo/start",
        json={},
        headers={"X-Forwarded-For": "203.0.113.99"},
    )
    assert resp.status_code == 503, resp.text
