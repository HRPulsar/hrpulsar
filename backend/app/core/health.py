"""Enhanced health check endpoints with DB, Redis, and S3 connectivity checks."""

import logging
import time

from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.database import async_session

logger = logging.getLogger(__name__)


async def _check_db() -> dict:
    """Check database connectivity."""
    start = time.perf_counter()
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        }
    except Exception as exc:  # noqa: BLE001 - health probe reports the failure
        return {"status": "error", "error": str(exc)}


async def _check_redis() -> dict:
    """Check Redis connectivity."""
    start = time.perf_counter()
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url)
        await r.ping()  # type: ignore[misc]
        await r.aclose()  # type: ignore[attr-defined]
        return {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        }
    except Exception as exc:  # noqa: BLE001 - health probe reports the failure
        return {"status": "error", "error": str(exc)}


async def _check_celery() -> dict:
    """Check that the Celery worker stack is alive.

    Primary signal: the `status:celery:heartbeat` Redis key, refreshed every
    30s by the beat task `write_celery_heartbeat` (TTL 90s).

    Fallback (HRP-46): when the heartbeat key is stale we ask the worker over
    Celery's control channel. With `worker_prefetch_multiplier=1` + a long AI
    generation in flight, the heartbeat task can sit queued behind the AI job
    and the key naturally expires — but the worker itself is alive. The
    control channel runs on a dedicated consumer thread and answers mid-task,
    so a positive `ping` flips us back to ok with `mode=control` and prevents
    the drawer from surfacing a false "worker offline" banner.
    """
    import asyncio

    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url)
        try:
            value = await r.get("status:celery:heartbeat")
        finally:
            await r.aclose()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - health probe reports the failure
        return {"status": "error", "error": str(exc)}

    if value is not None:
        return {
            "status": "ok",
            "mode": "heartbeat",
            "last_seen": value.decode() if isinstance(value, bytes) else str(value),
        }

    try:
        from app.core.celery_app import celery as celery_app

        def _ping() -> object:
            return celery_app.control.inspect(timeout=1.0).ping()

        pong = await asyncio.to_thread(_ping)
        if pong:
            return {"status": "ok", "mode": "control"}
    except Exception as exc:  # noqa: BLE001 - health probe reports the failure
        return {"status": "error", "error": f"no heartbeat; ping failed: {exc}"}

    return {"status": "error", "error": "no recent heartbeat"}


async def _check_s3() -> dict:
    """Check S3/MinIO connectivity (skip if not configured)."""
    if not settings.s3_endpoint:
        return {"status": "skipped", "reason": "not configured"}

    start = time.perf_counter()
    try:
        from app.core.s3 import get_s3_client

        client = get_s3_client()
        if client is None:
            return {"status": "skipped", "reason": "not configured"}
        client.head_bucket(Bucket=settings.s3_bucket)
        return {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        }
    except Exception as exc:  # noqa: BLE001 - health probe reports the failure
        return {"status": "error", "error": str(exc)}


async def health(request: Request) -> JSONResponse:
    """Full health check — DB, Redis, S3, Celery connectivity."""
    db = await _check_db()
    redis_check = await _check_redis()
    s3 = await _check_s3()
    celery = await _check_celery()

    checks = {"database": db, "redis": redis_check, "s3": s3, "celery": celery}
    all_ok = all(c["status"] in ("ok", "skipped") for c in checks.values())
    status_code = 200 if all_ok else 503

    return JSONResponse(
        content={
            "status": "ok" if all_ok else "degraded",
            "version": settings.version,
            "checks": checks,
        },
        status_code=status_code,
    )


async def health_ready(request: Request) -> JSONResponse:
    """Kubernetes readiness probe — checks if app can serve traffic."""
    db = await _check_db()
    redis_check = await _check_redis()

    ready = db["status"] == "ok" and redis_check["status"] == "ok"
    return JSONResponse(
        content={
            "ready": ready,
            "checks": {"database": db, "redis": redis_check},
        },
        status_code=200 if ready else 503,
    )


async def health_celery(request: Request) -> JSONResponse:
    """Lightweight Celery worker check used by UI to surface "worker offline".

    Returns 200 with `{available, last_seen?}` when the heartbeat key is fresh,
    503 with `{available: false, error}` otherwise.
    """
    result = await _check_celery()
    available = result["status"] == "ok"
    body: dict[str, object] = {"available": available}
    if available and "mode" in result:
        body["mode"] = result["mode"]
    if available and "last_seen" in result:
        body["last_seen"] = result["last_seen"]
    if not available and "error" in result:
        body["error"] = result["error"]
    return JSONResponse(content=body, status_code=200 if available else 503)
