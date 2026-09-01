"""HRP-596: the shared throttle counter in ``app.core.redis``.

Four throttles (signup, demo, feedback, demo upload quota) had a copy of
this pipeline each. The properties they all relied on are pinned here, so
the next caller does not have to re-derive them from one of the copies.
"""

import uuid

import pytest
from app.core.redis import bump_counter, redis_client


async def _ttl(key: str) -> int:
    async with redis_client() as client:
        return await client.ttl(key)


async def _delete(key: str) -> None:
    async with redis_client() as client:
        await client.delete(key)


async def test_counts_up_and_never_extends_the_window() -> None:
    """The window is anchored at the first bump (HRP-645).

    An unconditional EXPIRE would re-arm on every call, refused ones
    included, so a throttled caller could push its own reset out with each
    retry and stay over the cap forever.
    """
    key = f"test:bump:{uuid.uuid4().hex}"
    await _delete(key)
    try:
        assert await bump_counter(key, 60) == 1
        assert await bump_counter(key, 60) == 2
        anchored = await _ttl(key)
        assert 0 < anchored <= 60

        # A longer TTL on a later bump must not move the expiry.
        assert await bump_counter(key, 6000) == 3
        assert 0 < await _ttl(key) <= anchored
    finally:
        await _delete(key)


async def test_redis_failure_reaches_the_caller(monkeypatch) -> None:
    """The helper counts; it does not decide. Signup and demo fail closed
    on an outage, feedback and the upload quota fail open — so the error
    has to propagate instead of being swallowed into some default count.
    """

    def _explode(*_args, **_kwargs):
        raise ConnectionError("redis dead")

    monkeypatch.setattr("app.core.redis.aioredis.from_url", _explode)
    with pytest.raises(ConnectionError):
        await bump_counter(f"test:bump:{uuid.uuid4().hex}", 60)
