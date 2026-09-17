"""M15: every slowapi limiter counts in Redis, not in process memory.

With in-memory counters a "10/min" login limit is really 10 per uvicorn
worker times replicas, and every deploy hands an attacker a fresh budget.
"""

from __future__ import annotations

from app.core.rate_limit import make_limiter
from limits.storage import MemoryStorage
from limits.storage.redis import RedisStorage


def test_make_limiter_counts_in_redis() -> None:
    limiter = make_limiter(lambda request: "k")
    assert isinstance(limiter._storage, RedisStorage)


def test_make_limiter_keeps_an_in_memory_fallback() -> None:
    """A Redis blip must throttle harder, never fail auth closed."""
    limiter = make_limiter(lambda request: "k")
    assert limiter._storage_dead is False
    assert isinstance(limiter._fallback_storage, MemoryStorage)


def test_every_app_limiter_goes_through_the_factory() -> None:
    from app.modules.auth.router import auth_limiter, invitations_limiter
    from app.modules.public_api.router import limiter as public_api_limiter
    from app.modules.recruitment.routers.common import recruitment_public_limiter

    for limiter in (
        auth_limiter,
        invitations_limiter,
        public_api_limiter,
        recruitment_public_limiter,
    ):
        assert isinstance(limiter._storage, RedisStorage)
