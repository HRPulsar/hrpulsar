"""Tests for app.core.email.enqueue_email — Celery dispatch with inline fallback.

Background: enqueue_email replaces every direct send_email call across
service handlers so the request thread no longer blocks on the Resend HTTP
call (1–5 s) while still holding a DB connection (a driver of a past
pool-exhaustion incident).
"""

from unittest.mock import patch


class TestEnqueueEmail:
    def test_uses_celery_when_broker_available(self):
        """Happy path: send_email_task.delay is called, send_email is not."""
        from app.core import email as email_module

        with (
            patch("app.core.tasks.send_email_task") as mock_task,
            patch.object(email_module, "send_email") as mock_inline,
        ):
            email_module.enqueue_email(
                "user@test.com",
                "Subject",
                "<p>Body</p>",
                tenant_id="tenant-uuid",
                template_code="t.code",
            )

        mock_task.delay.assert_called_once_with(
            "user@test.com",
            "Subject",
            "<p>Body</p>",
            tenant_id="tenant-uuid",
            template_code="t.code",
        )
        mock_inline.assert_not_called()

    def test_falls_back_to_inline_when_broker_unreachable(self):
        """When Celery broker is down, OperationalError triggers inline send_email."""
        from app.core import email as email_module
        from kombu.exceptions import OperationalError

        with (
            patch("app.core.tasks.send_email_task") as mock_task,
            patch.object(
                email_module, "send_email", return_value=(True, "msg-id")
            ) as mock_inline,
        ):
            mock_task.delay.side_effect = OperationalError("broker unreachable")
            email_module.enqueue_email("user@test.com", "Subject", "<p>Body</p>")

        mock_task.delay.assert_called_once()
        mock_inline.assert_called_once_with("user@test.com", "Subject", "<p>Body</p>")

    def test_swallows_unexpected_exceptions(self):
        """Other exceptions must not bubble up to the caller (fire-and-forget)."""
        from app.core import email as email_module

        with (
            patch("app.core.tasks.send_email_task") as mock_task,
            patch.object(email_module, "send_email") as mock_inline,
        ):
            mock_task.delay.side_effect = RuntimeError("connection refused")
            mock_inline.side_effect = RuntimeError("inline blew up too")

            # Must not raise — caller's request must succeed regardless.
            email_module.enqueue_email("user@test.com", "S", "<p>B</p>")
