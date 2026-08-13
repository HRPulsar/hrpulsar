"""Dedicated suite for ``app.modules.notification.service`` (review item [25]).

Focus: ``send_notification`` channel gating (per-user preferences), template
rendering, and the email-log webhook update path. Templates are global rows
on the shared test DB, so every test creates its own uniquely-coded template.
"""

import uuid
from datetime import datetime, timezone

import pytest_asyncio
from app.modules.notification import service as notification_service
from app.modules.notification.models import (
    EmailLog,
    Notification,
    NotificationPreference,
    NotificationTemplate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def template(db: AsyncSession):
    tpl = NotificationTemplate(
        code=f"test.notify.{uuid.uuid4().hex[:8]}",
        subject_template="Hello {{ name }}",
        body_template="Body for {{ name }}",
        notification_type="email",
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return tpl


@pytest_asyncio.fixture
def sent_emails(monkeypatch):
    """Capture enqueue_email calls made by the notification service."""
    calls: list[dict] = []

    def _capture(to, subject, body, **kwargs):
        calls.append({"to": to, "subject": subject, "body": body, **kwargs})

    monkeypatch.setattr(notification_service, "enqueue_email", _capture)
    return calls


async def _set_preference(
    db: AsyncSession, user_id, event_type: str, channel: str, enabled: bool
) -> None:
    db.add(
        NotificationPreference(
            user_id=user_id,
            event_type=event_type,
            channel=channel,
            enabled=enabled,
        )
    )
    await db.commit()


async def _notifications_for(db: AsyncSession, tenant_id, user_id):
    result = await db.execute(
        select(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.recipient_id == user_id,
        )
    )
    return result.scalars().all()


class TestSendNotification:
    async def test_missing_template_is_noop(
        self, db: AsyncSession, tenant, user, sent_emails
    ):
        await notification_service.send_notification(
            db,
            tenant.id,
            f"missing.{uuid.uuid4().hex[:8]}",
            user.id,
            user.email,
            {"name": "X"},
        )
        assert sent_emails == []
        assert await _notifications_for(db, tenant.id, user.id) == []

    async def test_default_sends_email_and_records_in_app(
        self, db: AsyncSession, tenant, user, template, sent_emails
    ):
        await notification_service.send_notification(
            db,
            tenant.id,
            template.code,
            user.id,
            user.email,
            {"name": "Alice"},
        )

        assert len(sent_emails) == 1
        assert sent_emails[0]["to"] == user.email
        assert sent_emails[0]["subject"] == "Hello Alice"
        # HRP-568: the fragment is delivered inside the branded layout.
        assert "Body for Alice" in sent_emails[0]["body"]
        assert sent_emails[0]["template_code"] == template.code
        assert sent_emails[0]["tenant_id"] == str(tenant.id)

        notifs = await _notifications_for(db, tenant.id, user.id)
        assert len(notifs) == 1
        assert notifs[0].status == "sent"
        assert notifs[0].sent_at is not None
        assert notifs[0].context == {"name": "Alice"}

    async def test_email_disabled_still_records_in_app(
        self, db: AsyncSession, tenant, user, template, sent_emails
    ):
        await _set_preference(db, user.id, "general", "email", enabled=False)

        await notification_service.send_notification(
            db, tenant.id, template.code, user.id, user.email, {"name": "B"}
        )

        assert sent_emails == []
        notifs = await _notifications_for(db, tenant.id, user.id)
        assert len(notifs) == 1
        assert notifs[0].status == "sent"

    async def test_in_app_disabled_still_sends_email(
        self, db: AsyncSession, tenant, user, template, sent_emails
    ):
        await _set_preference(db, user.id, "general", "in_app", enabled=False)

        await notification_service.send_notification(
            db, tenant.id, template.code, user.id, user.email, {"name": "C"}
        )

        assert len(sent_emails) == 1
        assert await _notifications_for(db, tenant.id, user.id) == []

    async def test_both_channels_disabled(
        self, db: AsyncSession, tenant, user, template, sent_emails
    ):
        await _set_preference(db, user.id, "general", "email", enabled=False)
        await _set_preference(db, user.id, "general", "in_app", enabled=False)

        await notification_service.send_notification(
            db, tenant.id, template.code, user.id, user.email, {"name": "D"}
        )

        assert sent_emails == []
        assert await _notifications_for(db, tenant.id, user.id) == []

    async def test_preference_is_event_type_scoped(
        self, db: AsyncSession, tenant, user, template, sent_emails
    ):
        """Disabling one event type must not mute a different one."""
        await _set_preference(db, user.id, "pdp_sent", "email", enabled=False)

        await notification_service.send_notification(
            db,
            tenant.id,
            template.code,
            user.id,
            user.email,
            {"name": "E"},
            event_type="general",
        )

        assert len(sent_emails) == 1

    async def test_ws_broadcast_failure_does_not_raise(
        self, db: AsyncSession, tenant, user, template, sent_emails, monkeypatch
    ):
        from app.core.websocket import manager

        async def _boom(*args, **kwargs):
            raise RuntimeError("ws down")

        monkeypatch.setattr(manager, "publish_to_user", _boom)

        await notification_service.send_notification(
            db, tenant.id, template.code, user.id, user.email, {"name": "F"}
        )

        # Email + in-app record survive the failed live fan-out.
        assert len(sent_emails) == 1
        notifs = await _notifications_for(db, tenant.id, user.id)
        assert len(notifs) == 1


class TestEmailLogWebhookUpdate:
    async def test_unknown_message_id_returns_false(self, db: AsyncSession):
        ok = await notification_service.update_email_log_status(
            db, f"missing-{uuid.uuid4().hex}", "delivered"
        )
        assert ok is False

    async def test_delivered_sets_timestamp(self, db: AsyncSession, tenant):
        message_id = f"msg-{uuid.uuid4().hex[:12]}"
        db.add(
            EmailLog(
                tenant_id=tenant.id,
                recipient="log@test.com",
                subject="s",
                status="sent",
                message_id=message_id,
            )
        )
        await db.commit()

        delivered_at = datetime.now(timezone.utc)
        ok = await notification_service.update_email_log_status(
            db, message_id, "delivered", timestamp=delivered_at
        )
        assert ok is True

        log = (
            await db.execute(select(EmailLog).where(EmailLog.message_id == message_id))
        ).scalar_one()
        assert log.status == "delivered"
        assert log.delivered_at is not None

    async def test_non_delivered_status_keeps_delivered_at_empty(
        self, db: AsyncSession, tenant
    ):
        message_id = f"msg-{uuid.uuid4().hex[:12]}"
        db.add(
            EmailLog(
                tenant_id=tenant.id,
                recipient="log2@test.com",
                subject="s",
                status="sent",
                message_id=message_id,
            )
        )
        await db.commit()

        ok = await notification_service.update_email_log_status(
            db, message_id, "bounced", timestamp=datetime.now(timezone.utc)
        )
        assert ok is True

        log = (
            await db.execute(select(EmailLog).where(EmailLog.message_id == message_id))
        ).scalar_one()
        assert log.status == "bounced"
        assert log.delivered_at is None


class TestBrandPlaceholder:
    """HRP-515: seeded templates reference ``{{ brand_name }}`` — the render
    path injects the installation's brand; branded installs override it via
    the BRAND_NAME setting, callers via the context."""

    def _template(self) -> NotificationTemplate:
        return NotificationTemplate(
            code=f"test.brand.{uuid.uuid4().hex[:8]}",
            subject_template="Welcome to {{ brand_name }}",
            body_template="<p>Join {{ company_name }} on {{ brand_name }}.</p>",
            notification_type="email",
        )

    def test_render_injects_settings_brand(self):
        subject, body = notification_service.render_db_template(
            self._template(), {"company_name": "Acme"}
        )
        assert subject == "Welcome to HRPulsar"
        assert "<p>Join Acme on HRPulsar.</p>" in body

    def test_body_wrapped_in_branded_layout(self):
        """HRP-568: DB-template emails go out in the shared branded layout
        (logo header, footer) instead of as bare HTML fragments."""
        subject, body = notification_service.render_db_template(
            self._template(), {"company_name": "Acme"}
        )
        assert body.startswith("<!DOCTYPE html>")
        assert "<p>Join Acme on HRPulsar.</p>" in body
        assert "This is an automated message from" in body
        assert "<img src=" in body

    def test_context_values_are_escaped_in_body(self):
        """HRP-568: free-text context (names, titles) cannot inject live
        markup into the branded email body — the body template renders
        with autoescape."""
        _, body = notification_service.render_db_template(
            self._template(),
            {"company_name": 'Evil <a href="https://evil.example">link</a>'},
        )
        assert '<a href="https://evil.example">' not in body
        assert "Evil &lt;a href=" in body

    def test_layout_footer_follows_template_locale(self):
        """The layout footer is written in the template row's language —
        the language the email itself is written in."""
        tpl = self._template()
        tpl.locale = "de"
        _, body = notification_service.render_db_template(tpl, {"company_name": "Acme"})
        assert "Dies ist eine automatisch generierte Nachricht" in body
        assert '<html lang="de">' in body

    def test_brand_setting_overrides_default(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "brand_name", "TalentWerk")
        subject, body = notification_service.render_db_template(
            self._template(), {"company_name": "Acme"}
        )
        assert subject == "Welcome to TalentWerk"
        assert "on TalentWerk." in body

    def test_brand_escaped_in_body_raw_in_subject(self, monkeypatch):
        """Mirrors the HRP-393 invariant pinned by
        test_white_label_branding: HTML bodies get the escaped brand,
        plain-text subjects the raw one."""
        from app.config import settings

        monkeypatch.setattr(settings, "brand_name", "Baker & Sons <Ltd>")
        subject, body = notification_service.render_db_template(
            self._template(), {"company_name": "Acme"}
        )
        assert subject == "Welcome to Baker & Sons <Ltd>"
        assert "on Baker &amp; Sons &lt;Ltd&gt;." in body

    def test_caller_override_wins_and_context_not_mutated(self):
        ctx = {"company_name": "Acme", "brand_name": "Custom"}
        subject, _ = notification_service.render_db_template(self._template(), ctx)
        assert subject == "Welcome to Custom"
        assert ctx == {"company_name": "Acme", "brand_name": "Custom"}

    async def test_send_notification_renders_brand(
        self, db: AsyncSession, tenant, user, sent_emails
    ):
        tpl = self._template()
        db.add(tpl)
        await db.commit()

        await notification_service.send_notification(
            db, tenant.id, tpl.code, user.id, user.email, {"company_name": "Acme"}
        )

        assert len(sent_emails) == 1
        assert sent_emails[0]["subject"] == "Welcome to HRPulsar"
        notifs = await _notifications_for(db, tenant.id, user.id)
        assert len(notifs) == 1
        # The injected key must not leak into the persisted context.
        assert notifs[0].context == {"company_name": "Acme"}
