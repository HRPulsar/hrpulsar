"""P0-5: per-IP rate limiting on the unauthenticated auth surface.

The bulk suite runs with the auth limiter disabled (see the autouse fixture in
tests/conftest.py); this module re-enables it and drives a real endpoint past
its window to prove the throttle fires and returns 429.
"""

from __future__ import annotations

import pytest_asyncio
from app.config import settings
from app.modules.auth.router import auth_limiter
from httpx import AsyncClient


@pytest_asyncio.fixture
async def _limited():
    """Re-enable the auth limiter for the duration of a test."""
    previous = auth_limiter.enabled
    auth_limiter.enabled = True
    auth_limiter.reset()
    yield
    auth_limiter.reset()
    auth_limiter.enabled = previous


def _limit_count(window: str) -> int:
    # "3/minute" -> 3
    return int(window.split("/", 1)[0])


class TestAuthRateLimit:
    async def test_forgot_password_throttled_per_ip(
        self, client: AsyncClient, _limited
    ):
        allowed = _limit_count(settings.auth_rate_limit_email)
        # First `allowed` calls pass (endpoint always 200 to avoid enumeration).
        for _ in range(allowed):
            resp = await client.post(
                "/api/auth/forgot-password", json={"email": "nobody@example.com"}
            )
            assert resp.status_code == 200
        # The next one over the window is rejected.
        blocked = await client.post(
            "/api/auth/forgot-password", json={"email": "nobody@example.com"}
        )
        assert blocked.status_code == 429

    async def test_disabled_by_default_fixture(self, client: AsyncClient):
        # Without the _limited fixture the autouse disable keeps the endpoint
        # open no matter how many times we hit it.
        for _ in range(_limit_count(settings.auth_rate_limit_email) + 3):
            resp = await client.post(
                "/api/auth/forgot-password", json={"email": "nobody@example.com"}
            )
            assert resp.status_code == 200
