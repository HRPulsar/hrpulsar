"""Regression guards for the asyncpg engine settings introduced after a
2026-04 connection-pool lockup (stuck `idle in transaction` backends).
"""

import inspect

from app.database import engine


def test_engine_pre_ping_enabled():
    assert engine.pool._pre_ping is True


def test_engine_tcp_keepalives_propagated():
    cparams = inspect.getclosurevars(engine.pool._creator).nonlocals["cparams"]
    server_settings = cparams.get("server_settings", {})
    assert server_settings.get("tcp_keepalives_idle") == "60"
    assert server_settings.get("tcp_keepalives_interval") == "10"
    assert server_settings.get("tcp_keepalives_count") == "6"


def test_engine_pool_capacity():
    pool = engine.pool
    assert pool.size() == 10
    assert pool._max_overflow == 20
    assert pool._timeout == 10
    assert pool._recycle == 1800
