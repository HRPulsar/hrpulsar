"""Shared fixtures for pool load tests.

Each test spawns a fresh `uvicorn` subprocess with the pool config it wants
(POOL_SIZE / POOL_MAX_OVERFLOW / POOL_TIMEOUT). We don't piggy-back on the
unit-test ASGITransport because TestClient bypasses the engine pool that we
are trying to exercise.
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB_URL = "postgresql+asyncpg://hrpulsar:hrpulsar@localhost:5435/hrpulsar_test"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(base_url: str, timeout_s: float = 30.0) -> None:
    """Probe a load-test-only endpoint — `/health` depends on Celery beat,
    which isn't running in this subprocess, so it always returns 503 here.
    `/api/_test/pool-stats` only touches the engine, which is what we care
    about anyway.
    """
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/_test/pool-stats", timeout=1.0)
            if r.status_code == 200:
                return
        except Exception as e:  # pragma: no cover — startup race
            last_err = e
        time.sleep(0.3)
    raise RuntimeError(f"uvicorn didn't become ready in {timeout_s}s: {last_err!r}")


def spawn_uvicorn(
    *,
    pool_size: int,
    max_overflow: int,
    pool_timeout: int,
) -> tuple[subprocess.Popen, str]:
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "LOAD_TEST_MODE": "true",
            "DEPLOYMENT_MODE": "onprem",
            "SENTRY_DSN": "",
            "DATABASE_URL": TEST_DB_URL,
            "POOL_SIZE": str(pool_size),
            "POOL_MAX_OVERFLOW": str(max_overflow),
            "POOL_TIMEOUT": str(pool_timeout),
        }
    )
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
        try:
            out, _ = proc.communicate(timeout=2)
            sys.stderr.write(out.decode("utf-8", errors="replace"))
        except Exception:
            pass
        raise
    return proc, base


@pytest.fixture
def uvicorn_factory() -> Generator:
    spawned: list[subprocess.Popen] = []

    def _make(pool_size: int, max_overflow: int, pool_timeout: int = 10):
        proc, base = spawn_uvicorn(
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
        )
        spawned.append(proc)
        return proc, base

    yield _make

    for p in spawned:
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            with contextlib.suppress(Exception):
                p.kill()
