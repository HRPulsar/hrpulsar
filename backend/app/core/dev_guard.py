"""Shared gate for the E2E/dev-only endpoints (auth, recruitment seeds).

``E2E_MODE`` alone is not enough: a deployed environment carrying a stray
``E2E_MODE=true`` would expose auto-register, token reveal and the seed
routes. The tier check is belt-and-braces on top of it, and lives here so
every dev surface uses the same rule instead of its own copy.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.config import settings

_DEPLOYED_TIERS = {"production", "staging"}


def dev_endpoints_enabled() -> bool:
    """Whether the dev/E2E surface may exist at all in this process."""
    env = (settings.sentry_environment or "").lower()
    return settings.e2e_mode and env not in _DEPLOYED_TIERS


def require_dev_endpoint() -> None:
    """404 unless the dev/E2E surface is enabled."""
    if not dev_endpoints_enabled():
        # Deliberately a bare HTTPException, not AppError: the response must
        # stay indistinguishable from a nonexistent route — an error code
        # would fingerprint the hidden dev surface.
        raise HTTPException(status_code=404, detail="Not found")
