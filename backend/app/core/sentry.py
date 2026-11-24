"""Sentry error tracking integration."""

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# PII fields to strip from Sentry events
_PII_KEYS = {
    "email",
    "first_name",
    "last_name",
    "phone",
    "password",
    "new_password",
    "current_password",
}


def _strip_pii(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Remove PII from Sentry events before sending."""
    request_data = event.get("request", {})
    # Strip PII from request body
    if "data" in request_data and isinstance(request_data["data"], dict):
        for key in _PII_KEYS:
            if key in request_data["data"]:
                request_data["data"][key] = "[Filtered]"
    # Strip PII from user context
    user = event.get("user", {})
    for key in _PII_KEYS:
        if key in user:
            user[key] = "[Filtered]"
    return event


def init_sentry() -> None:
    """Initialize Sentry SDK if DSN is configured."""
    if not settings.sentry_dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            release=f"hrpulsar@{settings.version}",
            traces_sample_rate=settings.sentry_traces_sample_rate,
            before_send=_strip_pii,  # type: ignore[arg-type]
            # No frame variables: FastAPI's own frame holds the request body
            # as `body` and as raw bytes, so a password sent with a request
            # that ends in a 5xx would travel with the event, under a name
            # no scrubber can know (HRP-1161 review).
            include_local_variables=False,
            # A second layer, should variables ever come back: the SDK's
            # scrubber knows `password` but not `new_password`, so our names
            # go through it too, and a request model keeps its secrets out of
            # its repr (`Field(repr=False)`).
            event_scrubber=EventScrubber(
                denylist=[*DEFAULT_DENYLIST, *_PII_KEYS, "password_hash"]
            ),
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
            ],
            # Don't send PII by default
            send_default_pii=False,
        )
        logger.info("Sentry initialized (env=%s)", settings.sentry_environment)
    except Exception:  # noqa: BLE001 - optional telemetry init, logged
        logger.warning("Failed to initialize Sentry", exc_info=True)
