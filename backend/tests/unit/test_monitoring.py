"""Tests for Phase J: Monitoring & Observability.

Covers: metrics, middleware (request ID), health checks, Sentry PII filtering, logging.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# J1: Prometheus metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_normalize_path_uuid(self):
        from app.core.metrics import _normalize_path

        path = "/api/employees/550e8400-e29b-41d4-a716-446655440000/events"
        assert _normalize_path(path) == "/api/employees/{id}/events"

    def test_normalize_path_integer(self):
        from app.core.metrics import _normalize_path

        assert _normalize_path("/api/divisions/42") == "/api/divisions/{id}"
        assert _normalize_path("/api/divisions/42/employees") == (
            "/api/divisions/{id}/employees"
        )

    def test_normalize_path_no_ids(self):
        from app.core.metrics import _normalize_path

        assert _normalize_path("/api/employees") == "/api/employees"
        assert _normalize_path("/health") == "/health"

    def test_metrics_endpoint_returns_prometheus_format(self):
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/metrics")
        assert resp.status_code == 200
        body = resp.text
        # Prometheus exposition format contains HELP/TYPE lines
        assert "hrpulsar_http_requests_total" in body or "# HELP" in body

    def test_metrics_records_request(self):
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        # Make a request to trigger metrics
        client.get("/health")
        resp = client.get("/metrics")
        body = resp.text
        assert "hrpulsar_http_request_duration_seconds" in body

    def test_prometheus_counter_exists(self):
        from app.core.metrics import REQUEST_COUNT, REQUEST_LATENCY

        assert REQUEST_COUNT._name == "hrpulsar_http_requests"
        assert REQUEST_LATENCY._name == "hrpulsar_http_request_duration_seconds"


# ---------------------------------------------------------------------------
# J2: Request ID middleware
# ---------------------------------------------------------------------------


class TestRequestIdMiddleware:
    def test_response_has_request_id_header(self):
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert "x-request-id" in resp.headers

    def test_propagates_incoming_request_id(self):
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health", headers={"X-Request-ID": "test-rid-123"})
        assert resp.headers["x-request-id"] == "test-rid-123"

    def test_generates_request_id_when_missing(self):
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        rid = resp.headers.get("x-request-id")
        assert rid is not None
        assert len(rid) == 16  # hex[:16]

    def test_context_vars_module_level(self):
        from app.core.middleware import request_id_var, tenant_id_var, user_id_var

        # Default values
        assert request_id_var.get("") == ""
        assert tenant_id_var.get(None) is None
        assert user_id_var.get(None) is None


# ---------------------------------------------------------------------------
# J2: Structured logging
# ---------------------------------------------------------------------------


class TestStructuredLogging:
    def test_formatter_adds_service_field(self):
        import logging

        from app.core.logging import HRPulsarJsonFormatter

        formatter = HRPulsarJsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        log_record = {}
        formatter.add_fields(log_record, record, {})
        assert log_record["service"] == "hrpulsar"

    def test_formatter_injects_request_id(self):
        import logging

        from app.core.logging import HRPulsarJsonFormatter
        from app.core.middleware import request_id_var

        token = request_id_var.set("test-rid-abc")
        try:
            formatter = HRPulsarJsonFormatter()
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="hello",
                args=(),
                exc_info=None,
            )
            log_record = {}
            formatter.add_fields(log_record, record, {})
            assert log_record["request_id"] == "test-rid-abc"
        finally:
            request_id_var.reset(token)

    def test_formatter_skips_empty_context(self):
        import logging

        from app.core.logging import HRPulsarJsonFormatter
        from app.core.middleware import request_id_var

        token = request_id_var.set("")
        try:
            formatter = HRPulsarJsonFormatter()
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="hello",
                args=(),
                exc_info=None,
            )
            log_record = {}
            formatter.add_fields(log_record, record, {})
            assert "request_id" not in log_record
            assert "tenant_id" not in log_record
            assert "user_id" not in log_record
        finally:
            request_id_var.reset(token)


# ---------------------------------------------------------------------------
# J3: Sentry PII filtering
# ---------------------------------------------------------------------------


class TestSentryPiiFilter:
    def test_strip_pii_from_request_data(self):
        from app.core.sentry import _strip_pii

        event = {
            "request": {
                "data": {
                    "email": "user@example.com",
                    "first_name": "John",
                    "last_name": "Doe",
                    "phone": "+1234567890",
                    "password": "secret123",
                    "company_name": "Acme",
                }
            }
        }
        result = _strip_pii(event, {})
        assert result is not None
        data = result["request"]["data"]
        assert data["email"] == "[Filtered]"
        assert data["first_name"] == "[Filtered]"
        assert data["last_name"] == "[Filtered]"
        assert data["phone"] == "[Filtered]"
        assert data["password"] == "[Filtered]"
        assert data["company_name"] == "Acme"  # not PII

    def test_strip_pii_from_user_context(self):
        from app.core.sentry import _strip_pii

        event = {
            "user": {
                "email": "user@example.com",
                "id": "123",
                "first_name": "John",
            }
        }
        result = _strip_pii(event, {})
        assert result is not None
        assert result["user"]["email"] == "[Filtered]"
        assert result["user"]["id"] == "123"  # not PII

    def test_strip_pii_no_request(self):
        from app.core.sentry import _strip_pii

        event = {"message": "test error"}
        result = _strip_pii(event, {})
        assert result == event

    def test_init_sentry_skips_when_no_dsn(self):
        from app.core.sentry import init_sentry

        with patch("app.core.sentry.settings") as mock_settings:
            mock_settings.sentry_dsn = ""
            # Should not raise, just return
            init_sentry()


# ---------------------------------------------------------------------------
# J4: Health checks
# ---------------------------------------------------------------------------


class TestHealthChecks:
    def test_health_endpoint_basic(self):
        """Health endpoint returns structured response."""
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert "status" in data
        assert "checks" in data
        assert "database" in data["checks"]
        assert "redis" in data["checks"]
        assert "s3" in data["checks"]
        assert "celery" in data["checks"]
        assert "version" in data

    def test_health_ready_endpoint(self):
        """Readiness probe returns structured response."""
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health/ready")
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert "ready" in data
        assert "checks" in data

    @pytest.mark.asyncio
    async def test_check_db_success(self):
        from app.core.health import _check_db

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.health.async_session", return_value=mock_session):
            result = await _check_db()
        assert result["status"] == "ok"
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_check_db_failure(self):
        from app.core.health import _check_db

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(
            side_effect=ConnectionError("Connection refused")
        )
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.health.async_session", return_value=mock_session):
            result = await _check_db()
        assert result["status"] == "error"
        assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_check_redis_success(self):
        from app.core.health import _check_redis

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            result = await _check_redis()
        assert result["status"] == "ok"
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_check_redis_failure(self):
        from app.core.health import _check_redis

        with patch(
            "redis.asyncio.from_url",
            side_effect=ConnectionError("Redis down"),
        ):
            result = await _check_redis()
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_check_s3_skipped(self):
        from app.core.health import _check_s3

        with patch("app.core.health.settings") as mock_settings:
            mock_settings.s3_endpoint = ""
            result = await _check_s3()
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_check_s3_success(self):
        from app.core.health import _check_s3

        mock_client = MagicMock()
        mock_client.head_bucket = MagicMock()

        with (
            patch("app.core.health.settings") as mock_settings,
            patch("app.core.s3.get_s3_client", return_value=mock_client),
        ):
            mock_settings.s3_endpoint = "http://minio:9000"
            mock_settings.s3_bucket = "test-bucket"
            result = await _check_s3()
        assert result["status"] == "ok"
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_check_celery_alive(self):
        from app.core.health import _check_celery

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"2026-04-26T10:00:00+00:00")
        mock_redis.aclose = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            result = await _check_celery()
        assert result["status"] == "ok"
        assert "last_seen" in result

    @pytest.mark.asyncio
    async def test_check_celery_no_heartbeat(self):
        from app.core.health import _check_celery

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.aclose = AsyncMock()

        # Patch the control-channel fallback too: a live dev worker on the
        # shared broker would answer ping() and legitimately flip the probe
        # back to ok, making the test environment-dependent.
        mock_celery = MagicMock()
        mock_celery.control.inspect.return_value.ping.return_value = None

        with (
            patch("redis.asyncio.from_url", return_value=mock_redis),
            patch("app.core.celery_app.celery", mock_celery),
        ):
            result = await _check_celery()
        assert result["status"] == "error"
        assert "no recent heartbeat" in result["error"]

    @pytest.mark.asyncio
    async def test_health_all_ok(self):
        from app.core.health import health

        with (
            patch(
                "app.core.health._check_db",
                return_value={"status": "ok", "latency_ms": 1.0},
            ),
            patch(
                "app.core.health._check_redis",
                return_value={"status": "ok", "latency_ms": 0.5},
            ),
            patch(
                "app.core.health._check_s3",
                return_value={"status": "skipped", "reason": "not configured"},
            ),
            patch(
                "app.core.health._check_celery",
                return_value={"status": "ok", "last_seen": "2026-04-26T10:00:00+00:00"},
            ),
        ):
            request = MagicMock()
            resp = await health(request)
        assert resp.status_code == 200
        import json

        body = json.loads(resp.body)
        assert body["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_degraded(self):
        from app.core.health import health

        with (
            patch(
                "app.core.health._check_db",
                return_value={"status": "error", "error": "down"},
            ),
            patch(
                "app.core.health._check_redis",
                return_value={"status": "ok", "latency_ms": 0.5},
            ),
            patch(
                "app.core.health._check_s3",
                return_value={"status": "skipped", "reason": "not configured"},
            ),
            patch(
                "app.core.health._check_celery",
                return_value={"status": "ok", "last_seen": "2026-04-26T10:00:00+00:00"},
            ),
        ):
            request = MagicMock()
            resp = await health(request)
        assert resp.status_code == 503
        import json

        body = json.loads(resp.body)
        assert body["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_health_ready_ok(self):
        from app.core.health import health_ready

        with (
            patch(
                "app.core.health._check_db",
                return_value={"status": "ok", "latency_ms": 1.0},
            ),
            patch(
                "app.core.health._check_redis",
                return_value={"status": "ok", "latency_ms": 0.5},
            ),
        ):
            request = MagicMock()
            resp = await health_ready(request)
        assert resp.status_code == 200
        import json

        body = json.loads(resp.body)
        assert body["ready"] is True

    @pytest.mark.asyncio
    async def test_health_ready_not_ready(self):
        from app.core.health import health_ready

        with (
            patch(
                "app.core.health._check_db",
                return_value={"status": "ok", "latency_ms": 1.0},
            ),
            patch(
                "app.core.health._check_redis",
                return_value={"status": "error", "error": "down"},
            ),
        ):
            request = MagicMock()
            resp = await health_ready(request)
        assert resp.status_code == 503
        import json

        body = json.loads(resp.body)
        assert body["ready"] is False
