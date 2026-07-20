"""Load-test-only HTTP endpoints. Mounted only when LOAD_TEST_MODE=true.

These endpoints are intentionally not exposed in OpenAPI and must never ship
to staging/prod. They are used by `backend/tests/load/` to reproduce
QueuePool exhaustion and connection-leak scenarios.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import engine, get_db

router = APIRouter(
    prefix="/api/_test", tags=["_test-internal"], include_in_schema=False
)


@router.get("/sleep")
async def sleep_holding_connection(
    ms: int = 1000, db: AsyncSession = Depends(get_db)
) -> dict:
    seconds = ms / 1000.0
    await db.execute(text("SELECT pg_sleep(:s)"), {"s": seconds})
    return {"slept_ms": ms}


@router.get("/pool-stats")
async def pool_stats() -> dict:
    pool = engine.pool
    return {
        "size": pool.size(),  # type: ignore[attr-defined]
        "checked_in": pool.checkedin(),  # type: ignore[attr-defined]
        "checked_out": pool.checkedout(),  # type: ignore[attr-defined]
        "overflow": pool.overflow(),  # type: ignore[attr-defined]
    }
