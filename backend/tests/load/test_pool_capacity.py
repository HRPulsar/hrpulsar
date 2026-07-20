"""Test A — confirm the hot-fix raised the per-worker concurrency ceiling.

We spawn a real uvicorn process (TestClient/ASGITransport bypasses the engine
pool). Each request hits the guarded `/api/_test/sleep` endpoint which holds
its DB connection inside `pg_sleep`, so concurrency directly maps to checked
out pool slots.

Outcomes for each (pool_size, max_overflow) pair:
- N == capacity         → all 200, no errors.
- N == capacity + 1     → exactly 1 request fails with QueuePool timeout.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

pytestmark = [pytest.mark.load, pytest.mark.asyncio]

POOL_TIMEOUT_S = 2
SLEEP_MS = 4_000  # > pool_timeout so the overflow request can't simply wait it out


async def _fire(client: httpx.AsyncClient, base: str) -> tuple[int, str, float]:
    t0 = time.monotonic()
    try:
        r = await client.get(f"{base}/api/_test/sleep", params={"ms": SLEEP_MS})
        return r.status_code, r.text, time.monotonic() - t0
    except Exception as e:
        return 0, repr(e), time.monotonic() - t0


async def _run_burst(base: str, n: int) -> list[tuple[int, str, float]]:
    timeout = httpx.Timeout(POOL_TIMEOUT_S + SLEEP_MS / 1000 + 15)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await asyncio.gather(*(_fire(client, base) for _ in range(n)))


def _summary(results: list[tuple[int, str, float]]) -> dict:
    ok = [r for r in results if r[0] == 200]
    bad = [r for r in results if r[0] != 200]
    pool_errors = [r for r in bad if "QueuePool" in r[1]]
    return {
        "total": len(results),
        "ok": len(ok),
        "errors": len(bad),
        "pool_errors": len(pool_errors),
        "ok_avg_latency_s": (sum(r[2] for r in ok) / len(ok)) if ok else 0.0,
        "first_error_at_s": min((r[2] for r in bad), default=None),
        "error_samples": [r[1][:200] for r in bad[:3]],
    }


@pytest.mark.parametrize(
    "pool_size,max_overflow,n_at_cap,n_overflow",
    [
        pytest.param(5, 10, 15, 16, id="old-pool-5+10"),
        pytest.param(10, 20, 30, 31, id="new-pool-10+20"),
    ],
)
async def test_pool_capacity(
    uvicorn_factory, pool_size: int, max_overflow: int, n_at_cap: int, n_overflow: int
):
    capacity = pool_size + max_overflow
    assert n_at_cap == capacity
    assert n_overflow == capacity + 1

    _, base = uvicorn_factory(pool_size, max_overflow, POOL_TIMEOUT_S)

    # --- 1) at-capacity burst: everyone should make it
    res_cap = await _run_burst(base, n_at_cap)
    cap_summary = _summary(res_cap)
    print(f"\n[at-capacity {pool_size}+{max_overflow} N={n_at_cap}] {cap_summary}")
    assert cap_summary["ok"] == n_at_cap, cap_summary
    assert cap_summary["errors"] == 0, cap_summary

    # --- 2) capacity + 1: exactly one QueuePool timeout expected.
    # FastAPI ships a plain "Internal Server Error" body for any 500, so we
    # can't pattern-match the exception class on the wire — instead we anchor
    # on timing: a QueuePool TimeoutError fires after exactly pool_timeout
    # seconds, which is distinct from any other failure mode here.
    res_over = await _run_burst(base, n_overflow)
    over_summary = _summary(res_over)
    print(f"[overflow    {pool_size}+{max_overflow} N={n_overflow}] {over_summary}")
    assert over_summary["ok"] == capacity, over_summary
    assert over_summary["errors"] == 1, over_summary
    fail_t = over_summary["first_error_at_s"]
    assert (
        fail_t is not None and POOL_TIMEOUT_S - 0.5 <= fail_t <= POOL_TIMEOUT_S + 1.5
    ), over_summary
