import os
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import create_engine as _create_sync_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Single source of truth for Postgres-side guards. All engines in the project
# (FastAPI app, Celery sync engines, Alembic) are built via the factories
# below so the same protections apply everywhere.
#
# idle_in_transaction_session_timeout: server-side reaper for orphaned
#   `idle in transaction` backends that hold locks (added after a 2026-04
#   lock pile-up). Only kills idle sessions — long active queries are
#   unaffected.
# tcp_keepalives_*: kernel detects dead peers within ~2 minutes instead of
#   waiting for the next user query (same 2026-04 connection-pool lockup).
_IDLE_IN_TX_TIMEOUT = "5min"
_TCP_KEEPALIVES = {
    "tcp_keepalives_idle": "60",
    "tcp_keepalives_interval": "10",
    "tcp_keepalives_count": "6",
}


def _server_settings(
    *,
    lock_timeout: str | None,
    statement_timeout: str | None,
    include_keepalives: bool,
) -> dict[str, str]:
    s: dict[str, str] = {"idle_in_transaction_session_timeout": _IDLE_IN_TX_TIMEOUT}
    if include_keepalives:
        s.update(_TCP_KEEPALIVES)
    if lock_timeout:
        s["lock_timeout"] = lock_timeout
    if statement_timeout:
        s["statement_timeout"] = statement_timeout
    return s


def make_async_engine(
    url: str,
    *,
    lock_timeout: str | None = None,
    statement_timeout: str | None = None,
    **engine_kwargs: Any,
) -> AsyncEngine:
    """Async (asyncpg) engine with project-wide Postgres guards baked in."""
    return create_async_engine(
        url,
        connect_args={
            "server_settings": _server_settings(
                lock_timeout=lock_timeout,
                statement_timeout=statement_timeout,
                include_keepalives=True,
            ),
        },
        **engine_kwargs,
    )


def make_sync_engine(
    url: str,
    *,
    lock_timeout: str | None = None,
    statement_timeout: str | None = None,
    **engine_kwargs: Any,
) -> Engine:
    """Sync (psycopg2) engine for Celery contexts. Accepts the same +asyncpg
    URL as the rest of the app and rewrites the driver. Applies the same
    Postgres guards via libpq `options`. Skips TCP keepalives — these engines
    are short-lived per task, keepalives matter for long-lived pools."""
    pg_url = url.replace("+asyncpg", "+psycopg2")
    opts = " ".join(
        f"-c {k}={v}"
        for k, v in _server_settings(
            lock_timeout=lock_timeout,
            statement_timeout=statement_timeout,
            include_keepalives=False,
        ).items()
    )
    return _create_sync_engine(
        pg_url,
        connect_args={"options": opts},
        **engine_kwargs,
    )


# pool_pre_ping issues a SELECT 1 before checking out a connection — drops
# half-dead asyncpg sockets (RST'd while idle) before they reach service code.
# POOL_SIZE/POOL_MAX_OVERFLOW/POOL_TIMEOUT envs are read so load tests can
# reproduce the pre-fix exhaustion case (5 + 10) without code changes.
engine = make_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=int(os.getenv("POOL_SIZE", "10")),
    max_overflow=int(os.getenv("POOL_MAX_OVERFLOW", "20")),
    pool_timeout=int(os.getenv("POOL_TIMEOUT", "10")),
    pool_recycle=1800,
    pool_pre_ping=True,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def import_all_models() -> None:
    """Import every model module under ``app/modules`` into Base.metadata.

    String ``ForeignKey("table.col")`` targets resolve lazily: if the module
    defining the target table was never imported in a given process, the
    first ORM flush raises ``NoReferencedTableError``. Callers that build
    the full mapper registry outside the FastAPI import graph (Celery
    worker init, Alembic env) must call this instead of maintaining their
    own import lists. Covers canonical ``models.py`` and feature-split
    ``*_models.py`` files.
    """
    import importlib
    from pathlib import Path

    modules_dir = Path(__file__).resolve().parent / "modules"
    for models_file in sorted(
        [*modules_dir.glob("*/models.py"), *modules_dir.glob("*/*_models.py")]
    ):
        importlib.import_module(
            f"app.modules.{models_file.parent.name}.{models_file.stem}"
        )


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with async_session() as session:
        yield session
