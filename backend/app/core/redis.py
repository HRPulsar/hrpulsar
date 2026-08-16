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
async def redis_client(**kwargs: object) -> AsyncIterator[aioredis.Redis]:
    """Yield a Redis client for ``settings.redis_url``, always closed after.

    ``from_url`` itself can raise (malformed URL), so open the context
    inside the caller's own ``try`` when the caller has a fallback.
    """
    client = aioredis.from_url(settings.redis_url, decode_responses=True, **kwargs)
    try:
        yield client
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()
