"""Prometheus metrics for HRPulsar.

Uses multiprocess mode when running with multiple uvicorn workers.
Requires PROMETHEUS_MULTIPROC_DIR env var to be set (done in entrypoint.sh).
"""

import os
import time

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# --- Metrics ---

REQUEST_COUNT = Counter(
    "hrpulsar_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

REQUEST_LATENCY = Histogram(
    "hrpulsar_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

REQUESTS_IN_PROGRESS = Gauge(
    "hrpulsar_http_requests_in_progress",
    "Number of HTTP requests currently being processed",
    ["method"],
    multiprocess_mode="livesum",
)

RESPONSE_SIZE = Histogram(
    "hrpulsar_http_response_size_bytes",
    "HTTP response size in bytes",
    ["method", "path"],
    buckets=(100, 500, 1_000, 5_000, 10_000, 50_000, 100_000, 500_000),
)


def _normalize_path(path: str) -> str:
    """Collapse UUID/int segments to reduce cardinality."""
    import re

    # Replace UUIDs
    path = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "{id}",
        path,
    )
    # Replace integer IDs in path segments
    path = re.sub(r"/\d+(?=/|$)", "/{id}", path)
    return path


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Middleware that records Prometheus metrics for each request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        path = _normalize_path(request.url.path)

        REQUESTS_IN_PROGRESS.labels(method=method).inc()
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            REQUEST_COUNT.labels(method=method, path=path, status=500).inc()
            raise
        finally:
            duration = time.perf_counter() - start
            REQUESTS_IN_PROGRESS.labels(method=method).dec()
            REQUEST_LATENCY.labels(method=method, path=path).observe(duration)

        REQUEST_COUNT.labels(
            method=method, path=path, status=response.status_code
        ).inc()

        content_length = response.headers.get("content-length")
        if content_length:
            RESPONSE_SIZE.labels(method=method, path=path).observe(int(content_length))

        return response


async def metrics_endpoint(request: Request) -> Response:
    """Endpoint that exposes Prometheus metrics.

    In multiprocess mode, collects metrics from all workers via shared files.
    """
    if "PROMETHEUS_MULTIPROC_DIR" in os.environ:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        data = generate_latest(registry)
    else:
        data = generate_latest()
    return Response(
        content=data,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
