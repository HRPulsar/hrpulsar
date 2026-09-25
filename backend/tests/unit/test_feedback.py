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


async def test_contact_email_alone_is_a_request(
    auth_client: AsyncClient, captured_events
):
    """The demo banner's "Talk to us": an address alone asks for a call."""
    res = await auth_client.post(
        "/api/feedback",
        json={"source": "demo", "contact_email": "visitor@example.com"},
    )
    assert res.status_code == 204
    assert captured_events[0]["contact_email"] == "visitor@example.com"


async def test_phone_alone_is_a_request(auth_client: AsyncClient, captured_events):
    """Sites with the phone field: a number alone asks for a call too."""
    res = await auth_client.post(
        "/api/feedback",
        json={
            "source": "demo",
            "contact_name": " Anna ",
            "contact_phone": " +7 900 000-00-00 ",
        },
    )
    assert res.status_code == 204
    payload = captured_events[0]
    assert payload["contact_name"] == "Anna"
    assert payload["contact_phone"] == "+7 900 000-00-00"


async def test_name_alone_is_still_empty(auth_client: AsyncClient, captured_events):
    res = await auth_client.post(
        "/api/feedback", json={"contact_name": "Anna", "contact_phone": "  "}
    )
    assert res.status_code == 400
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

    def set(self, *args, **kwargs):
        self.ops.append(("set", args, kwargs))
        return self

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

    async def set(self, key, value, ex=None, nx=False):
        # NX: only creates the bucket, and only the first call arms its TTL —
        # the anchored window ``core.redis.bump_counter`` relies on.
        if nx and key in self.store:
            return None
        self.store[key] = value
        self.ttls[key] = ex
        return True

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


async def test_redis_outage_fails_closed(
    auth_client: AsyncClient, captured_events, monkeypatch
):
    """With the throttle store down the cap is unknowable, and an
    unthrottled path into the operators' chat is the worse outcome —
    signup and demo start already fail closed (review §3)."""
    from app.config import settings

    monkeypatch.setattr(settings, "feedback_rate_limit_per_user_per_hour", 2)
    monkeypatch.setattr(
        "app.core.redis.aioredis.from_url",
        lambda *_a, **_kw: (_ for _ in ()).throw(ConnectionError("redis down")),
    )

    res = await auth_client.post("/api/feedback", json={"rating": "up"})
    assert res.status_code == 429
    assert res.json()["code"] == "feedback_rate_limited"
    assert captured_events == []


async def test_disabled_cap_survives_a_redis_outage(
    auth_client: AsyncClient, captured_events, monkeypatch
):
    """0 disables the cap, so the store is never consulted at all."""
    from app.config import settings

    monkeypatch.setattr(settings, "feedback_rate_limit_per_user_per_hour", 0)
    monkeypatch.setattr(
        "app.core.redis.aioredis.from_url",
        lambda *_a, **_kw: (_ for _ in ()).throw(ConnectionError("redis down")),
    )

    res = await auth_client.post("/api/feedback", json={"rating": "up"})
    assert res.status_code == 204
    assert len(captured_events) == 1
