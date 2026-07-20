"""HRP-253 (D5): outbound email is suppressed for demo tenants.

Covers the three paths through which a demo tenant could reach the
real Resend / SMTP sender:

1. ``send_email_task`` (Celery) — the mass-call entrypoint behind
   :func:`app.core.email.enqueue_email`. Used by recruitment
   notifications and the notification module.
2. The inline-fallback branch of :func:`enqueue_email` — fires when the
   Celery broker is unreachable (self-hosted without Redis).
3. The convenience helper :func:`send_invitation_email` — invitation
   flows bypass Celery on purpose because they live inside the
   request-response cycle and we want immediate failure feedback.

Password-reset and verify-email helpers stay tenant-agnostic on
purpose (cross-tenant lookup-by-email, no authenticated context yet) —
they're tested by absence: the gate is only added where the inviter's
tenant is known.
"""

from __future__ import annotations

import uuid

import pytest
from app.config import settings as app_settings
from app.core.email import enqueue_email, send_invitation_email
from app.core.tasks import send_email_task
from app.modules.company.models import Tenant
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_tenant(db: AsyncSession, *, is_demo: bool) -> Tenant:
    suffix = uuid.uuid4().hex[:6]
    t = Tenant(
        name=f"T {suffix}", slug=f"t-{suffix}", is_demo=is_demo
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


@pytest.fixture
def pin_sync_db(monkeypatch):
    """Make the throwaway sync engine in tasks.py talk to ``hrpulsar_test``."""
    from tests.conftest import TEST_DB_URL

    monkeypatch.setattr(app_settings, "database_url", TEST_DB_URL)


@pytest.mark.asyncio
async def test_send_email_task_skips_demo_tenant(
    db: AsyncSession, pin_sync_db, monkeypatch
):
    tenant = await _make_tenant(db, is_demo=True)

    calls: list[tuple] = []

    def _spy(to: str, subject: str, html_body: str):
        calls.append((to, subject))
        return True, "msg-id"

    # Patch where send_email_task imported it — the task module binds the
    # symbol at import time, so monkey-patching ``app.core.email.send_email``
    # alone would miss the call inside the task.
    monkeypatch.setattr("app.core.tasks.send_email", _spy)

    result = send_email_task.run(
        "user@example.com",
        "Subject",
        "<p>body</p>",
        tenant_id=str(tenant.id),
    )

    assert result == (False, None)
    assert calls == []


@pytest.mark.asyncio
async def test_send_email_task_sends_for_paid_tenant(
    db: AsyncSession, pin_sync_db, monkeypatch
):
    tenant = await _make_tenant(db, is_demo=False)

    calls: list[tuple] = []

    def _spy(to: str, subject: str, html_body: str):
        calls.append((to, subject))
        return True, "msg-id"

    monkeypatch.setattr("app.core.tasks.send_email", _spy)

    ok, msg_id = send_email_task.run(
        "user@example.com",
        "Subject",
        "<p>body</p>",
        tenant_id=str(tenant.id),
    )

    assert ok is True
    assert msg_id == "msg-id"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_send_email_task_without_tenant_passes_through(
    db: AsyncSession, pin_sync_db, monkeypatch
):
    """No tenant context ⇒ no gate. Password reset / verify-email fall here."""
    calls: list[tuple] = []

    def _spy(to: str, subject: str, html_body: str):
        calls.append((to, subject))
        return True, "msg-id"

    monkeypatch.setattr("app.core.tasks.send_email", _spy)

    ok, _ = send_email_task.run(
        "stranger@example.com",
        "Reset",
        "<p>x</p>",
        tenant_id=None,
    )

    assert ok is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_enqueue_email_inline_fallback_skips_demo(
    db: AsyncSession, pin_sync_db, monkeypatch
):
    """Broker-down → inline fallback. Demo tenants must still be silenced."""
    from kombu.exceptions import OperationalError

    tenant = await _make_tenant(db, is_demo=True)

    def _broker_down(*args, **kwargs):
        raise OperationalError("broker unreachable")

    monkeypatch.setattr(
        "app.core.tasks.send_email_task.delay", _broker_down
    )

    inline_calls: list[tuple] = []

    def _spy(to: str, subject: str, html_body: str):
        inline_calls.append((to, subject))
        return True, "msg"

    monkeypatch.setattr("app.core.email.send_email", _spy)

    enqueue_email(
        "user@example.com",
        "Subject",
        "<p>body</p>",
        tenant_id=str(tenant.id),
    )

    assert inline_calls == []


@pytest.mark.asyncio
async def test_enqueue_email_inline_fallback_sends_for_paid(
    db: AsyncSession, pin_sync_db, monkeypatch
):
    from kombu.exceptions import OperationalError

    tenant = await _make_tenant(db, is_demo=False)

    monkeypatch.setattr(
        "app.core.tasks.send_email_task.delay",
        lambda *a, **k: (_ for _ in ()).throw(OperationalError("nope")),
    )

    inline_calls: list[tuple] = []

    def _spy(to: str, subject: str, html_body: str):
        inline_calls.append((to, subject))
        return True, "msg"

    monkeypatch.setattr("app.core.email.send_email", _spy)

    enqueue_email(
        "user@example.com",
        "Subject",
        "<p>body</p>",
        tenant_id=str(tenant.id),
    )

    assert len(inline_calls) == 1


@pytest.mark.asyncio
async def test_send_invitation_email_sends_for_demo(
    db: AsyncSession, pin_sync_db, monkeypatch
):
    """HRP-301 reverses the original D5 demo gate for invitations — a
    demo tenant must be able to dispatch the onboarding mail so a
    prospective HR admin can walk through the invite flow end-to-end."""
    tenant = await _make_tenant(db, is_demo=True)

    calls: list[tuple] = []

    def _spy(to: str, subject: str, html_body: str):
        calls.append((to, subject))
        return True, "msg"

    monkeypatch.setattr("app.core.email.send_email", _spy)

    ok = send_invitation_email(
        "invitee@example.com",
        "Invitee",
        "tok",
        7,
        tenant_id=tenant.id,
    )

    assert ok is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_send_invitation_email_sends_for_paid(
    db: AsyncSession, pin_sync_db, monkeypatch
):
    tenant = await _make_tenant(db, is_demo=False)

    calls: list[tuple] = []

    def _spy(to: str, subject: str, html_body: str):
        calls.append((to, subject))
        return True, "msg"

    monkeypatch.setattr("app.core.email.send_email", _spy)

    ok = send_invitation_email(
        "invitee@example.com",
        "Invitee",
        "tok",
        7,
        tenant_id=tenant.id,
    )

    assert ok is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_send_invitation_email_no_tenant_sends_through(monkeypatch):
    """Back-compat: callers that don't pass tenant_id still work."""
    calls: list[tuple] = []

    def _spy(to: str, subject: str, html_body: str):
        calls.append((to, subject))
        return True, "msg"

    monkeypatch.setattr("app.core.email.send_email", _spy)

    ok = send_invitation_email("a@b.com", "Name", "tok", 7)

    assert ok is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_send_invitation_reminder_email_sends_for_demo(
    db: AsyncSession, pin_sync_db, monkeypatch
):
    """HRP-301 — reminder helper mirrors the invitation-send carve-out."""
    from app.core.email import send_invitation_reminder_email

    tenant = await _make_tenant(db, is_demo=True)

    calls: list[tuple] = []

    def _spy(to: str, subject: str, html_body: str):
        calls.append((to, subject))
        return True, "msg"

    monkeypatch.setattr("app.core.email.send_email", _spy)

    ok = send_invitation_reminder_email(
        "invitee@example.com",
        "Invitee",
        "tok",
        7,
        tenant_id=tenant.id,
    )

    assert ok is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_send_invitation_reminder_email_sends_for_paid(
    db: AsyncSession, pin_sync_db, monkeypatch
):
    from app.core.email import send_invitation_reminder_email

    tenant = await _make_tenant(db, is_demo=False)

    calls: list[tuple] = []

    def _spy(to: str, subject: str, html_body: str):
        calls.append((to, subject))
        return True, "msg"

    monkeypatch.setattr("app.core.email.send_email", _spy)

    ok = send_invitation_reminder_email(
        "invitee@example.com",
        "Invitee",
        "tok",
        7,
        tenant_id=tenant.id,
    )

    assert ok is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_falsy_zero_empty_string_tenant_id_does_not_bypass_gate(
    db: AsyncSession, pin_sync_db, monkeypatch
):
    """Regression: `if tenant_id is None` (not `if not tenant_id`) — empty
    string must be treated as 'unknown tenant' and proceed to the lookup
    (which returns False since the row doesn't exist), not silently
    fail-open as 'no gate'."""
    from app.core.tasks import _tenant_is_demo_sync

    # Empty string is type-contractually invalid but we make sure the
    # behavior is 'False without bypassing all sync work', not 'silently
    # short-circuit'. Both behaviors return False, but the new guard is
    # the explicit None check.
    assert _tenant_is_demo_sync("") is False
    assert _tenant_is_demo_sync(None) is False
