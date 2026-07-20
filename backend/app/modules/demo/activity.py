"""Per-request demo-tenant ``last_active_at`` touch (HRP-249 — D1).

Called from the auth dependency on every authenticated request so the
sliding inactivity TTL stays current. Three cheaping moves keep this
off the hot path of regular tenants:

1. A single ``UPDATE … WHERE id = :tid AND is_demo`` runs only when the
   request is bound to a tenant; the predicate short-circuits to zero
   rows for non-demo tenants without us needing to first read the row.
2. A Redis-backed debounce per ``tenant_id`` (``demo:active:{id}``,
   TTL = ``DEMO_ACTIVITY_TOUCH_DEBOUNCE_SECONDS``) skips the SQL alto-
   gether between writes.
3. The write happens inside a SAVEPOINT (``begin_nested``) so a
   transient failure rolls back only the touch, not the surrounding
   request-scoped transaction. The savepoint is released on success
   and is materialised by whatever ``commit()`` the route handler /
   ``get_db`` cleanup eventually issues.

Both Redis and DB errors are swallowed — this is a freshness hint, not
a correctness signal. The cleanup task is the source of truth.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.company.models import Tenant

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def _redis_client() -> aioredis.Redis | None:
    """Lazy redis client. Returns ``None`` if Redis is unreachable so
    callers can safely degrade to always-write mode in tests / dev."""
    global _redis
    if _redis is None:
        try:
            _redis = aioredis.from_url(
                settings.redis_url, decode_responses=True
            )
        except Exception:  # noqa: BLE001
            logger.debug("demo activity: redis init failed", exc_info=True)
            return None
    return _redis


def _session_factory():
    """Resolve the async sessionmaker used for activity touches.

    Indirected through a function so tests can monkeypatch it onto
    their own test engine — the production ``async_session`` in
    ``app.database`` is bound to ``settings.database_url`` which may
    differ from the test database.
    """
    from app.database import async_session

    return async_session


async def touch_demo_tenant_activity(
    db: AsyncSession, tenant_id: uuid.UUID | None
) -> None:
    """Bump ``tenants.last_active_at`` for demo tenants (debounced).

    Safe to call on every authenticated request. The ``db`` parameter
    is kept in the signature for backwards compatibility but is no
    longer used for the write — the UPDATE runs in a fresh, short-
    lived session of its own so:

    * read-only requests (GET) still persist the touch — the request
      session in ``get_db`` never commits, so a borrowed-session SAVEPOINT
      would roll back with the outer transaction and the update would be
      silently dropped (HRP-276 / H1).
    * a failure here never aborts the transaction the route handler is
      about to use — the dedicated session has nothing else in flight.
    """
    if tenant_id is None:
        return

    debounce_key = f"demo:active:{tenant_id}"
    client = _redis_client()
    if client is not None:
        try:
            already = await client.set(
                debounce_key,
                "1",
                ex=settings.demo_activity_touch_debounce_seconds,
                nx=True,
            )
            if not already:
                return
        except Exception:  # noqa: BLE001
            logger.debug("demo activity: redis debounce failed", exc_info=True)

    try:
        factory = _session_factory()
        async with factory() as own_session, own_session.begin():
            await own_session.execute(
                update(Tenant)
                .where(Tenant.id == tenant_id, Tenant.is_demo.is_(True))
                .values(last_active_at=datetime.now(timezone.utc))
            )
    except Exception:  # noqa: BLE001
        logger.debug("demo activity: db touch failed", exc_info=True)
