"""Regression: endpoints that send mail must not block on the Resend HTTP call.

Before POOL_HOLD_REDUCTION (2026-04-30) ``send_email`` ran inline after
``db.commit()`` and held the request handler's pool slot for 1–5 seconds while
``resend.Emails.send()`` blocked on the network. After the refactor every
caller uses ``enqueue_email`` which delegates to a Celery task — the HTTP
handler should return well under 200 ms even when the would-be email work
would otherwise be slow.

The moderated signup endpoint is exercised here because it has no auth
requirement and exercises the same fire-and-forget contract.
"""

from __future__ import annotations

import time

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.load]


async def test_signup_request_returns_fast(client: AsyncClient, monkeypatch):
    """POST /api/signup-request completes in <200ms when the email
    helper is mocked.

    Even if Resend would block, the request handler must hand off and
    return immediately. We patch the send helper itself with a no-op so
    a misconfigured test environment can't accidentally hit Resend.
    """
    from app.modules.signup import service as signup_service

    async def _noop_send(_row, **_kwargs):
        return None

    monkeypatch.setattr(signup_service, "_send_signup_verify_email", _noop_send)
    monkeypatch.setattr(signup_service, "_enforce_rate_limit", _noop_send)

    payload = {
        "email": "fast-path@test.com",
        "first_name": "Fast",
        "last_name": "Path",
        "company_name": "Acme",
        "role": "founder",
    }

    t0 = time.monotonic()
    resp = await client.post("/api/signup-request", json=payload)
    elapsed = time.monotonic() - t0

    assert resp.status_code in (200, 201), resp.text
    # 200ms is generous; locally this lands at <30ms, CI ~80ms.
    assert elapsed < 0.2, f"signup-request took {elapsed:.3f}s — expected <0.2s"
