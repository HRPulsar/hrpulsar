"""In-product feedback endpoint (HRP-586, HRP-587).

Core never talks to Slack — it publishes ``feedback.submitted`` and the
enterprise handler picks it up. These tests pin exactly that contract,
including the community case where nobody is subscribed.
"""

import pytest
from app.core import events
from httpx import AsyncClient


@pytest.fixture
def captured_events(monkeypatch):
    """Capture ``feedback.submitted`` payloads for the test's duration.

    The whole subscriber list is replaced, not appended to: in the
    monorepo the enterprise Slack handler subscribes at import time, and
    these tests must neither depend on it nor fire it. monkeypatch
    restores the original list afterwards.
    """
    seen: list[dict] = []

    async def _handler(data: dict) -> None:
        seen.append(data)

    monkeypatch.setitem(events._handlers, "feedback.submitted", [_handler])
    return seen


async def test_submit_publishes_event(
    auth_client: AsyncClient, tenant, captured_events
):
    res = await auth_client.post(
        "/api/feedback",
        json={"rating": "up", "message": "  Love the reports  "},
    )
    assert res.status_code == 204
    assert len(captured_events) == 1
    payload = captured_events[0]
    assert payload["rating"] == "up"
    assert payload["message"] == "Love the reports"
    assert payload["source"] == "platform"
    assert payload["tenant_name"] == tenant.name
    assert payload["tenant_is_demo"] is False
    assert "@" in payload["user_email"]


async def test_demo_popup_fields_are_carried(auth_client: AsyncClient, captured_events):
    res = await auth_client.post(
        "/api/feedback",
        json={
            "source": "demo",
            "rating": "down",
            "message": "Could not find the export button",
            "clarity": "no",
            "contact_email": "visitor@example.com",
        },
    )
    assert res.status_code == 204
    payload = captured_events[0]
    assert payload["source"] == "demo"
    assert payload["clarity"] == "no"
    assert payload["contact_email"] == "visitor@example.com"


async def test_empty_submission_rejected(auth_client: AsyncClient, captured_events):
    res = await auth_client.post("/api/feedback", json={"message": "   "})
    assert res.status_code == 400
    assert res.json()["code"] == "feedback_empty"
    assert captured_events == []


async def test_requires_authentication(client: AsyncClient, captured_events):
    res = await client.post("/api/feedback", json={"rating": "up"})
    assert res.status_code == 401
    assert captured_events == []


async def test_community_build_accepts_without_subscriber(
    auth_client: AsyncClient, monkeypatch
):
    """No Slack handler subscribed (community build) — still a clean 204."""
    monkeypatch.setitem(events._handlers, "feedback.submitted", [])
    res = await auth_client.post("/api/feedback", json={"rating": "up"})
    assert res.status_code == 204


class _FakePipe:
    def __init__(self, r):
        self.r, self.ops = r, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    def incr(self, key):
        self.ops.append(("incr", (key,), {}))
        return self

    def expire(self, *args, **kwargs):
        self.ops.append(("expire", args, kwargs))
        return self

    async def execute(self):
        out = [await getattr(self.r, op)(*a, **kw) for op, a, kw in self.ops]
        self.ops.clear()
        return out


class _FakeRedis:
    def __init__(self):
        self.store: dict = {}
        self.ttls: dict = {}

    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key, seconds, nx=False):
        if nx and self.ttls.get(key):
            return False
        self.ttls[key] = seconds
        return True

    def pipeline(self, transaction=True):
        return _FakePipe(self)

    async def aclose(self):
        return None


async def test_rate_limited_after_the_hourly_cap(
    auth_client: AsyncClient, captured_events, monkeypatch
):
    """The endpoint fans out to the operators' chat — demo tokens must
    not buy unlimited pings (review fix)."""
    from app.config import settings

    monkeypatch.setattr(settings, "feedback_rate_limit_per_user_per_hour", 2)
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.redis.aioredis.from_url", lambda *_a, **_kw: fake)

    for _ in range(2):
        res = await auth_client.post("/api/feedback", json={"rating": "up"})
        assert res.status_code == 204
    res = await auth_client.post("/api/feedback", json={"rating": "up"})
    assert res.status_code == 429
    assert len(captured_events) == 2


async def test_redis_outage_fails_open(
    auth_client: AsyncClient, captured_events, monkeypatch
):
    """Feedback is a convenience channel — a flaky throttle store must
    not refuse the submission itself."""
    from app.config import settings

    monkeypatch.setattr(settings, "feedback_rate_limit_per_user_per_hour", 2)
    monkeypatch.setattr(
        "app.core.redis.aioredis.from_url",
        lambda *_a, **_kw: (_ for _ in ()).throw(ConnectionError("redis down")),
    )

    res = await auth_client.post("/api/feedback", json={"rating": "up"})
    assert res.status_code == 204
    assert len(captured_events) == 1
