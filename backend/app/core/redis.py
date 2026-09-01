"""Shared async Redis client for the throttles (HRP-576).

Four call sites (signup rate limit, signup reminder throttle, demo rate
limit, recruitment invite throttles) had copied the same
``from_url`` / ``try`` / ``aclose``-in-``finally`` boilerplate. The
connection handling lives here now; the *failure policy* stays with the
callers, because it genuinely differs between them (signup and demo fail
closed, community resend fails open).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from app.config import settings


@asynccontextmanager
async def redis_client() -> AsyncIterator[aioredis.Redis]:
    """Yield a Redis client for ``settings.redis_url``, always closed after.

    ``from_url`` itself can raise (malformed URL), so open the context
    inside the caller's own ``try`` when the caller has a fallback.
    """
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


async def bump_counter(key: str, ttl_seconds: int) -> int:
    """Count one hit against ``key`` in a window anchored at the first hit.

    Returns the running count. Deliberately not a decision: the throttles
    that call this disagree on what a Redis outage means — signup and demo
    fail closed, feedback and the demo upload quota fail open — so the
    error propagates and each caller keeps the policy it already had
    (HRP-596). Same reason the cap itself stays with the caller.

    ``SET key 0 EX ttl NX`` + ``INCR`` rather than ``INCR`` +
    ``EXPIRE ... NX``: both anchor the window, but the ``EXPIRE`` flags
    need Redis 7.x, which the fleet's system Redis does not guarantee.
    Anchoring is the point (HRP-645) — an unconditional ``EXPIRE`` lets a
    throttled caller push its own reset an hour further with every
    refused retry, keeping itself over the cap forever.
    """
    async with redis_client() as client, client.pipeline(transaction=True) as pipe:
        pipe.set(key, 0, ex=ttl_seconds, nx=True)
        pipe.incr(key)
        _, count = await pipe.execute()
    return int(count)
