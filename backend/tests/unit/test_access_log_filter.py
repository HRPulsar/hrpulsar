"""HRP-728: the access-log filter must hide only *successful* internal probes.

Five days of `GET /health` answering 503 left no trace in Loki because every
health line was filtered regardless of status. A non-2xx probe is exactly the
line an operator needs.
"""

import logging

from app.main import InternalEndpointFilter


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, message, None, None)


def test_successful_health_probe_is_suppressed():
    assert InternalEndpointFilter().filter(_record('172.25.0.9:1 - "GET /health HTTP/1.1" 200')) is False


def test_degraded_health_probe_is_logged():
    assert InternalEndpointFilter().filter(_record('172.25.0.9:1 - "GET /health HTTP/1.1" 503')) is True


def test_successful_metrics_scrape_is_suppressed():
    assert InternalEndpointFilter().filter(_record('172.25.0.9:1 - "GET /metrics HTTP/1.1" 200')) is False


def test_ordinary_request_passes():
    assert InternalEndpointFilter().filter(_record('172.25.0.9:1 - "GET /api/company HTTP/1.1" 200')) is True
