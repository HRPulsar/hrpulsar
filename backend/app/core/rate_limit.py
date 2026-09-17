"""One constructor for every slowapi limiter in the app.

Limiters default to process-memory counters, which is wrong twice over on a
deployed instance: with ``UVICORN_WORKERS=2`` (times replicas) a "10/min"
login limit is really 10 per worker, and every deploy hands an attacker a
fresh budget. Counting in Redis makes the limit mean what it says, and
``in_memory_fallback_enabled`` keeps the auth surface serving if Redis
blinks instead of failing every request closed.

Every ``Limiter(...)`` goes through here so a new throttle cannot silently
go back to per-process counting (review M15).
"""

from collections.abc import Callable

from slowapi import Limiter
from starlette.requests import Request

from app.config import settings


def make_limiter(key_func: Callable[[Request], str]) -> Limiter:
    """A ``Limiter`` counting in Redis, bucketed by endpoint.

    ``key_style="endpoint"`` is load-bearing: slowapi's default ("url")
    buckets by the full request path, so any route carrying an id or token
    in its path would get a fresh bucket per value and never throttle.
    """
    return Limiter(
        key_func=key_func,
        key_style="endpoint",
        storage_uri=settings.redis_url,
        in_memory_fallback_enabled=True,
    )
