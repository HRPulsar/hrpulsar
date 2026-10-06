"""Cloudflare Turnstile server-side check, for any bot-guarded public form.

The public process check (HRP-923) calls it; the signup and demo flows
still carry copies of their own (``signup.service``, ``demo.turnstile``)
that can move onto this one. Each caller keeps its own secret setting.

Reference: https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(
    secret: str,
    token: str | None,
    *,
    remote_ip: str | None,
    action: str | None = None,
    hostname: str | None = None,
) -> bool:
    """True when the challenge passes - or when ``secret`` is empty: the
    guard is off (dev, on-prem, E2E), and the caller's settings decide
    whether that may happen in production. Fails closed: no token, a
    refusal, an HTTP error and a network failure are all a failed
    challenge.

    ``action`` and ``hostname``, when given, must be what siteverify says
    the token was solved for: the widget's ``action`` and the page's host.
    Otherwise a token solved on another form, or on another site carrying
    the same public site key, would pass here."""
    if not secret:
        return True
    if not token:
        return False
    payload = {"secret": secret, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(VERIFY_URL, data=payload)
        if resp.status_code != 200:
            logger.warning("turnstile: siteverify returned HTTP %s", resp.status_code)
            return False
        verdict = resp.json()
        if not verdict.get("success"):
            return False
        for field, expected in (("action", action), ("hostname", hostname)):
            if expected is not None and verdict.get(field) != expected:
                logger.warning(
                    "turnstile: token solved for %s %r, expected %r",
                    field,
                    verdict.get(field),
                    expected,
                )
                return False
        return True
    except Exception:  # noqa: BLE001 - unknown state is a failed challenge
        logger.exception("turnstile: verification failed")
        return False
