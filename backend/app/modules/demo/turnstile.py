"""Cloudflare Turnstile verifier for the public demo bootstrap.

Used by ``POST /api/demo/start`` to bot-guard session creation. The
verifier is no-op when ``DEMO_TURNSTILE_SECRET`` is empty, so dev /
self-hosted / E2E runs can skip the challenge entirely.

Reference: https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

_bypass_warned = False


def _warn_turnstile_bypass_once() -> None:
    """One-shot warning so a misconfigured prod (empty secret + demo
    enabled) gets at least one record in the logs."""
    global _bypass_warned
    if _bypass_warned:
        return
    _bypass_warned = True
    logger.warning(
        "demo turnstile: DEMO_ENABLED=true but DEMO_TURNSTILE_SECRET is "
        "empty — bot guard is BYPASSED. Set the secret before opening "
        "the demo to the public."
    )


async def verify_turnstile_token(token: str | None, *, remote_ip: str | None) -> bool:
    """Return True iff the Turnstile challenge passes.

    When ``DEMO_TURNSTILE_SECRET`` is unset we short-circuit to True so
    the endpoint stays usable in development. Network failures are
    treated as a *failed* challenge — bot-guard semantics require us to
    fail closed under unknown state.
    """
    secret = settings.demo_turnstile_secret
    if not secret:
        if settings.demo_enabled:
            # Calling out the bypass on every check would drown the
            # logs; warn once per process instead.
            _warn_turnstile_bypass_once()
        return True

    if not token:
        return False

    payload: dict[str, str] = {"secret": secret, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(_VERIFY_URL, data=payload)
        if resp.status_code != 200:
            logger.warning(
                "demo turnstile: siteverify returned HTTP %s", resp.status_code
            )
            return False
        body = resp.json()
        return bool(body.get("success"))
    except Exception:  # noqa: BLE001
        logger.exception("demo turnstile: verification failed")
        return False
