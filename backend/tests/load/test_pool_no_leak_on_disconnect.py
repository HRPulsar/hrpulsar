"""Test C — make sure cancelled clients don't strand connections in the pool.

Known Starlette gotcha: `BaseHTTPMiddleware` can swallow `CancelledError`
during `call_next` and keep the inner DB session checked out. We probe both
configs (RequestIdMiddleware ON / OFF) so any leak we observe can be blamed
on the middleware, not on FastAPI's request handling at large.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

pytestmark = [pytest.mark.load, pytest.mark.asyncio]

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB_URL = "postgresql+asyncpg://hrpulsar:hrpulsar@localhost:5435/hrpulsar_test"
POOL_TIMEOUT_S = 5
SLEEP_MS = 10_000
N_CLIENTS = 20
CANCEL_AFTER_S = 1.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(base_url: str, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/_test/pool-stats", timeout=1.0)
            if r.status_code == 200:
                return
        except Exception as e:
            last_err = e
        time.sleep(0.3)
    raise RuntimeError(f"uvicorn didn't become ready in {timeout_s}s: {last_err!r}")


@pytest.fixture
def uvicorn_with_middleware() -> Iterator[tuple[bool, str]]:
    """Param fixture: (request_id_middleware_enabled, base_url)."""
    yield from _spawn(disable_middleware=False)


@pytest.fixture
def uvicorn_without_middleware() -> Iterator[tuple[bool, str]]:
    yield from _spawn(disable_middleware=True)


def _spawn(*, disable_middleware: bool):
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "LOAD_TEST_MODE": "true",
            "DEPLOYMENT_MODE": "onprem",
            "SENTRY_DSN": "",
            "DATABASE_URL": TEST_DB_URL,
            "POOL_SIZE": "10",
            "POOL_MAX_OVERFLOW": "20",
            "POOL_TIMEOUT": str(POOL_TIMEOUT_S),
        }
    )
    if disable_middleware:
        env["LOAD_TEST_DISABLE_REQUEST_ID_MIDDLEWARE"] = "true"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "1",
            "--no-access-log",
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_ready(base)
    except Exception:
        proc.kill()
        raise
    try:
        yield (not disable_middleware), base
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()


async def _pool_snapshot(base: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(f"{base}/api/_test/pool-stats")
        r.raise_for_status()
        return r.json()


async def _bombard_then_cancel(base: str, n: int) -> dict:
    timeout = httpx.Timeout(SLEEP_MS / 1000 + 30)
    client = httpx.AsyncClient(timeout=timeout)
    tasks = [
        asyncio.create_task(
            client.get(f"{base}/api/_test/sleep", params={"ms": SLEEP_MS})
        )
        for _ in range(n)
    ]
    await asyncio.sleep(CANCEL_AFTER_S)
    cancelled = 0
    for t in tasks:
        if not t.done():
            t.cancel()
            cancelled += 1
    results = await asyncio.gather(*tasks, return_exceptions=True)
    await client.aclose()
    completed = sum(1 for r in results if not isinstance(r, BaseException))
    return {"cancelled": cancelled, "completed": completed}


async def _run_leak_check(base: str) -> dict:
    baseline = await _pool_snapshot(base)
    burst = await _bombard_then_cancel(base, N_CLIENTS)
    # Wait long enough for any in-flight pg_sleep to finish OR for the pool to
    # time-out a checkout attempt. pool_timeout + sleep duration covers both.
    await asyncio.sleep(POOL_TIMEOUT_S + SLEEP_MS / 1000 + 2)
    final = await _pool_snapshot(base)
    return {"baseline": baseline, "final": final, "burst": burst}


async def test_no_leak_with_request_id_middleware(uvicorn_with_middleware):
    enabled, base = uvicorn_with_middleware
    assert enabled is True
    report = await _run_leak_check(base)
    print(f"\n[middleware ON ] {report}")
    final = report["final"]
    # checked_out includes the snapshot connection itself (1) — anything above
    # that means a request-side connection is still pinned.
    assert final["checked_out"] <= 1, report


async def test_no_leak_without_request_id_middleware(uvicorn_without_middleware):
    enabled, base = uvicorn_without_middleware
    assert enabled is False
    report = await _run_leak_check(base)
    print(f"\n[middleware OFF] {report}")
    final = report["final"]
    assert final["checked_out"] <= 1, report
