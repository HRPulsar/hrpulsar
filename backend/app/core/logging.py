"""JSON logging configuration for all processes (API, Celery worker, beat)."""

import logging
import logging.config
import sys

from pythonjsonlogger.json import JsonFormatter


class HRPulsarJsonFormatter(JsonFormatter):
    """JSON formatter that includes standard fields in every log entry."""

    def __init__(self, **kwargs):
        super().__init__(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
            **kwargs,
        )

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record.setdefault("service", "hrpulsar")

        # Inject request context (set by RequestIdMiddleware)
        from app.core.middleware import request_id_var, tenant_id_var, user_id_var

        rid = request_id_var.get("")
        if rid:
            log_record["request_id"] = rid
        tenant = tenant_id_var.get(None)
        if tenant is not None:
            log_record["tenant_id"] = tenant
        user = user_id_var.get(None)
        if user is not None:
            log_record["user_id"] = user

        if record.exc_info and not log_record.get("exc_info"):
            log_record["exc_info"] = self.formatException(record.exc_info)


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON output to stderr."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(HRPulsarJsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Force uvicorn loggers to use root JSON handler instead of their own
    # plain-text handlers (prevents multi-line tracebacks from splitting
    # into separate log entries in Loki/Grafana).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True

    # Suppress noisy libraries
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
