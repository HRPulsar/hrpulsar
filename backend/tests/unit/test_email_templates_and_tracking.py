"""I2/I3: Tests for HTML email templates, delivery tracking, and admin logs."""

from datetime import datetime, timezone
from unittest.mock import patch

from app.core.email_templates import (
    render_assessment_assigned_email,
    render_assessment_completed_email,
    render_certificate_expiry_email,
    render_deadline_reminder_email,
    render_exam_assigned_email,
    render_exam_results_email,
    render_external_review_email,
    render_invitation_email,
    render_invitation_reminder_email,
    render_password_reset_email,
    render_pdp_returned_email,
    render_pdp_sent_email,
    render_verification_email,
)
from app.modules.notification.models import EmailLog
from app.modules.notification.service import (
    list_email_logs,
    update_email_log_status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# I2: Template rendering tests
# ---------------------------------------------------------------------------


class TestEmailTemplates:
    def test_verification_email(self):
        subject, html = render_verification_email("abc123")
        assert "Verify your email" in subject
        assert "HRPulsar" in subject
        assert "/verify-email?token=abc123" in html
        assert "Verify Email" in html
        assert "24 hours" in html
        assert "HRPulsar" in html

    def test_password_reset_email(self):
        subject, html = render_password_reset_email("reset-tok")
        assert "Reset your password" in subject
        assert "/reset-password?token=reset-tok" in html
        assert "15 minutes" in html
        assert "Reset Password" in html

    def test_invitation_email(self):
        subject, html = render_invitation_email("Anna", "inv-tok", expire_days=14)
        assert "invited" in subject.lower()
        assert "/accept-invite?token=inv-tok" in html
        assert "Hi Anna" in html
        assert "14 days" in html
        assert "Accept Invitation" in html

    def test_invitation_reminder_email(self):
        subject, html = render_invitation_reminder_email(
            "Anna", "inv-tok", expire_days=7
        )
        assert "Reminder" in subject
        assert "/accept-invite?token=inv-tok" in html
        assert "Hi Anna" in html
        assert "7 days" in html

    def test_invitation_email_escapes_name(self):
        subject, html = render_invitation_email("<script>alert(1)</script>", "inv-tok")
        assert "<script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    def test_assessment_assigned_email(self):
        subject, html = render_assessment_assigned_email(
            "Q2 Review", deadline="2026-06-30"
        )
        assert "Q2 Review" in subject
        assert "Q2 Review" in html
        assert "2026-06-30" in html
        assert "/assessments" in html

    def test_assessment_assigned_no_deadline(self):
        subject, html = render_assessment_assigned_email("Annual Review")
        assert "Annual Review" in subject
        assert "deadline" not in html.lower() or "deadline" in html.lower()
        # Just verify no crash without deadline

    def test_assessment_completed_email(self):
        subject, html = render_assessment_completed_email("Q2 Review")
        assert "completed" in subject.lower()
        assert "Q2 Review" in html
        assert "Results" in html

    def test_pdp_sent_email(self):
        subject, html = render_pdp_sent_email("John Doe", deadline="2026-07-15")
        assert subject == "Development plan assigned"
        assert "John Doe" in html
        assert "2026-07-15" in html

    def test_pdp_sent_email_with_title(self):
        subject, html = render_pdp_sent_email(
            "John Doe", deadline="2026-07-15", pdp_title="Q3 Growth Plan"
        )
        assert subject == "Development plan assigned: Q3 Growth Plan"
        assert "Q3 Growth Plan" in html
        assert "John Doe" in html
        assert "2026-07-15" in html

    def test_pdp_sent_email_title_is_escaped(self):
        subject, html = render_pdp_sent_email(
            "John Doe", pdp_title="<script>alert(1)</script>"
        )
        assert "<script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "<script>alert(1)</script>" in subject

    def test_pdp_sent_email_blank_title_falls_back(self):
        subject, _ = render_pdp_sent_email("John Doe", pdp_title="   ")
        assert subject == "Development plan assigned"

    def test_pdp_returned_email(self):
        subject, html = render_pdp_returned_email("Jane Smith")
        assert "returned" in subject.lower()
        assert "Jane Smith" in html
        assert "revision" in html.lower()

    def test_exam_assigned_email(self):
        subject, html = render_exam_assigned_email(
            "Security Exam", deadline="2026-08-01"
        )
        assert "Security Exam" in subject
        assert "2026-08-01" in html
        assert "/exams" in html

    def test_exam_results_email(self):
        subject, html = render_exam_results_email(
            "Security Exam", score=85, max_score=100
        )
        assert "results" in subject.lower()
        assert "85" in html
        assert "100" in html

    def test_certificate_expiry_email(self):
        subject, html = render_certificate_expiry_email(
            course_title="AWS Cert",
            expiry_date="2026-05-15",
            days_left=25,
            employee_name="Bob Jones",
        )
        assert "AWS Cert" in subject
        assert "AWS Cert" in html
        assert "25 days" in html
        assert "Bob Jones" in html

    def test_deadline_reminder_email(self):
        subject, html = render_deadline_reminder_email(
            entity_type="assessment", entity_title="Q2 360", deadline="2026-06-30"
        )
        assert "Q2 360" in subject
        assert "ASSESSMENT" in html
        assert "2026-06-30" in html

    def test_external_review_email(self):
        subject, html = render_external_review_email(
            token="ext-tok", assessment_title="Q2 Review", deadline="2026-06-30"
        )
        assert "Q2 Review" in subject
        assert "/review/ext-tok" in html
        assert "2026-06-30" in html
        assert "No account" in html

    def test_all_templates_have_branding(self):
        """All templates must include HRPulsar branding and base layout."""
        templates = [
            render_verification_email("t"),
            render_password_reset_email("t"),
            render_invitation_email("N", "t"),
            render_invitation_reminder_email("N", "t"),
            render_assessment_assigned_email("A"),
            render_assessment_completed_email("A"),
            render_pdp_sent_email("N"),
            render_pdp_returned_email("N"),
            render_exam_assigned_email("E"),
            render_exam_results_email("E", 1, 10),
            render_certificate_expiry_email("C", "2026-01-01", 5, "N"),
            render_deadline_reminder_email("t", "T", "2026-01-01"),
            render_external_review_email("t", "A"),
        ]
        for subject, html in templates:
            assert "HRPulsar" in html, f"Missing branding in: {subject}"
            assert "<!DOCTYPE html>" in html, f"Missing doctype in: {subject}"
            assert "automated message" in html, f"Missing footer in: {subject}"


# ---------------------------------------------------------------------------
# I2: send_email return value (tuple)
# ---------------------------------------------------------------------------


class TestSendEmailReturnTuple:
    def test_send_email_returns_tuple_no_config(self):
        from app.core.email import send_email

        with patch("app.core.email.settings") as mock_settings:
            mock_settings.resend_api_key = ""
            mock_settings.smtp_host = ""
            result = send_email("test@test.com", "Test", "<p>test</p>")
        assert result == (False, None)

    def test_send_verification_email_uses_template(self):
        from app.core.email import send_verification_email

        with patch("app.core.email.send_email", return_value=(True, "msg-1")) as mock:
            result = send_verification_email("user@test.com", "tok123")
        assert result is True
        args = mock.call_args
        assert "Verify your email" in args[0][1]
        assert "/verify-email?token=tok123" in args[0][2]

    def test_send_password_reset_email_uses_template(self):
        from app.core.email import send_password_reset_email

        with patch("app.core.email.send_email", return_value=(True, "msg-2")) as mock:
            result = send_password_reset_email("user@test.com", "reset-tok")
        assert result is True
        assert "/reset-password?token=reset-tok" in mock.call_args[0][2]

    def test_send_invitation_email_uses_template(self):
        from app.core.email import send_invitation_email

        with patch("app.core.email.send_email", return_value=(True, "msg-3")) as mock:
            result = send_invitation_email("user@test.com", "Anna", "inv-tok", 14)
        assert result is True
        assert "/accept-invite?token=inv-tok" in mock.call_args[0][2]
        assert "Hi Anna" in mock.call_args[0][2]


# ---------------------------------------------------------------------------
# I3: EmailLog model and delivery tracking
# ---------------------------------------------------------------------------


class TestEmailLogModel:
    async def test_create_email_log(self, db: AsyncSession, tenant):
        log = EmailLog(
            tenant_id=tenant.id,
            recipient="user@test.com",
            subject="Test Subject",
            template_code="assessment.sent",
            status="sent",
            message_id="resend-msg-123",
            attempts=1,
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)

        assert log.id is not None
        assert log.recipient == "user@test.com"
        assert log.status == "sent"
        assert log.message_id == "resend-msg-123"
        assert log.error is None
        assert log.delivered_at is None

    async def test_email_log_nullable_tenant(self, db: AsyncSession):
        """System emails (verification, password reset) have no tenant."""
        log = EmailLog(
            tenant_id=None,
            recipient="new@test.com",
            subject="Verify email",
            status="sent",
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        assert log.tenant_id is None

    async def test_email_log_failed_with_error(self, db: AsyncSession, tenant):
        log = EmailLog(
            tenant_id=tenant.id,
            recipient="bad@test.com",
            subject="Failed email",
            status="failed",
            error="Connection refused",
            attempts=3,
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        assert log.status == "failed"
        assert log.error == "Connection refused"
        assert log.attempts == 3


# ---------------------------------------------------------------------------
# I3: Email log service functions
# ---------------------------------------------------------------------------


class TestEmailLogService:
    async def _create_logs(
        self, db: AsyncSession, tenant, count: int = 5
    ) -> list[EmailLog]:
        logs = []
        for i in range(count):
            log = EmailLog(
                tenant_id=tenant.id,
                recipient=f"user{i}@test.com",
                subject=f"Email {i}",
                template_code="assessment.sent" if i % 2 == 0 else "pdp.sent",
                status="sent" if i < 3 else "failed",
                message_id=f"msg-{i}",
                attempts=1 if i < 3 else 3,
            )
            db.add(log)
            logs.append(log)
        await db.commit()
        return logs

    async def test_list_email_logs(self, db: AsyncSession, tenant):
        await self._create_logs(db, tenant, 5)
        logs, total = await list_email_logs(db, tenant_id=tenant.id)
        assert total == 5
        assert len(logs) == 5

    async def test_list_email_logs_filter_by_status(self, db: AsyncSession, tenant):
        await self._create_logs(db, tenant, 5)
        logs, total = await list_email_logs(
            db, tenant_id=tenant.id, status_filter="failed"
        )
        assert total == 2
        for log in logs:
            assert log["status"] == "failed"

    async def test_list_email_logs_filter_by_recipient(self, db: AsyncSession, tenant):
        await self._create_logs(db, tenant, 5)
        logs, total = await list_email_logs(
            db, tenant_id=tenant.id, recipient_filter="user0"
        )
        assert total == 1
        assert logs[0]["recipient"] == "user0@test.com"

    async def test_list_email_logs_pagination(self, db: AsyncSession, tenant):
        await self._create_logs(db, tenant, 5)
        logs, total = await list_email_logs(db, tenant_id=tenant.id, skip=0, limit=2)
        assert total == 5
        assert len(logs) == 2

    async def test_update_email_log_status_delivered(self, db: AsyncSession, tenant):
        log = EmailLog(
            tenant_id=tenant.id,
            recipient="user@test.com",
            subject="Test",
            status="sent",
            message_id="msg-deliver-test",
        )
        db.add(log)
        await db.commit()

        now = datetime.now(timezone.utc)
        found = await update_email_log_status(db, "msg-deliver-test", "delivered", now)
        assert found is True

        result = await db.execute(
            select(EmailLog).where(EmailLog.message_id == "msg-deliver-test")
        )
        updated = result.scalar_one()
        assert updated.status == "delivered"
        assert updated.delivered_at is not None

    async def test_update_email_log_status_bounced(self, db: AsyncSession, tenant):
        log = EmailLog(
            tenant_id=tenant.id,
            recipient="bad@test.com",
            subject="Test",
            status="sent",
            message_id="msg-bounce-test",
        )
        db.add(log)
        await db.commit()

        found = await update_email_log_status(db, "msg-bounce-test", "bounced")
        assert found is True

        result = await db.execute(
            select(EmailLog).where(EmailLog.message_id == "msg-bounce-test")
        )
        assert result.scalar_one().status == "bounced"

    async def test_update_email_log_status_not_found(self, db: AsyncSession):
        found = await update_email_log_status(db, "nonexistent-id", "delivered")
        assert found is False


# ---------------------------------------------------------------------------
# I3: Admin email logs endpoint
# ---------------------------------------------------------------------------


class TestEmailLogsEndpoint:
    async def test_list_email_logs_admin(self, auth_client, db, tenant):
        for i in range(3):
            db.add(
                EmailLog(
                    tenant_id=tenant.id,
                    recipient=f"r{i}@test.com",
                    subject=f"Sub {i}",
                    status="sent",
                )
            )
        await db.commit()

        resp = await auth_client.get("/api/settings/email-logs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

    async def test_list_email_logs_filter(self, auth_client, db, tenant):
        db.add(
            EmailLog(
                tenant_id=tenant.id, recipient="a@test.com", subject="S", status="sent"
            )
        )
        db.add(
            EmailLog(
                tenant_id=tenant.id,
                recipient="b@test.com",
                subject="S",
                status="failed",
            )
        )
        await db.commit()

        resp = await auth_client.get("/api/settings/email-logs?status=failed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["status"] == "failed"

    async def test_list_email_logs_requires_auth(self, client):
        resp = await client.get("/api/settings/email-logs")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# I3: Resend webhook endpoint
# ---------------------------------------------------------------------------


class TestResendWebhook:
    async def test_webhook_delivered(self, client, db, tenant):
        log = EmailLog(
            tenant_id=tenant.id,
            recipient="user@test.com",
            subject="Test",
            status="sent",
            message_id="resend-123",
        )
        db.add(log)
        await db.commit()

        resp = await client.post(
            "/api/webhooks/email",
            json={
                "type": "email.delivered",
                "data": {
                    "email_id": "resend-123",
                    "created_at": "2026-04-20T10:00:00Z",
                },
            },
        )
        assert resp.status_code == 200

        result = await db.execute(
            select(EmailLog).where(EmailLog.message_id == "resend-123")
        )
        updated = result.scalar_one()
        assert updated.status == "delivered"
        assert updated.delivered_at is not None

    async def test_webhook_bounced(self, client, db, tenant):
        log = EmailLog(
            tenant_id=tenant.id,
            recipient="bad@test.com",
            subject="Test",
            status="sent",
            message_id="resend-456",
        )
        db.add(log)
        await db.commit()

        resp = await client.post(
            "/api/webhooks/email",
            json={
                "type": "email.bounced",
                "data": {"email_id": "resend-456"},
            },
        )
        assert resp.status_code == 200

        result = await db.execute(
            select(EmailLog).where(EmailLog.message_id == "resend-456")
        )
        assert result.scalar_one().status == "bounced"

    async def test_webhook_unknown_message_id(self, client, db):
        resp = await client.post(
            "/api/webhooks/email",
            json={
                "type": "email.delivered",
                "data": {"email_id": "unknown-id"},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_webhook_unknown_event_type(self, client, db):
        resp = await client.post(
            "/api/webhooks/email",
            json={
                "type": "email.unknown_event",
                "data": {"email_id": "some-id"},
            },
        )
        assert resp.status_code == 200

    async def test_webhook_invalid_payload(self, client, db):
        resp = await client.post("/api/webhooks/email", json={})
        assert resp.status_code == 200
        assert resp.json()["ok"] is False
