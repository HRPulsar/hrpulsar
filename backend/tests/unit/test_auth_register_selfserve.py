"""HRP-390: self-serve registration fallbacks for self-hosted installs.

Covers the two rescue hatches that keep a community deployment from
dead-ending on email verification:

- onprem + no email provider → the account is verified at registration
  time (``auto_verified``) and can log in immediately;
- onprem + provider configured but delivery failing → the verification
  link is printed to the backend log so the operator can finish the
  signup by hand. SaaS never logs verification links.
"""

import logging
import uuid

from app.config import settings
from app.modules.auth import service
from app.modules.auth.models import User
from app.modules.auth.schemas import RegisterRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

LINK_MARKER = "EMAIL VERIFICATION LINK"


def _register_data() -> RegisterRequest:
    suffix = uuid.uuid4().hex[:8]
    return RegisterRequest(
        email=f"selfserve-{suffix}@example.com",
        password="password123",
        first_name="Self",
        last_name="Serve",
        company_name=f"SelfServe Corp {suffix}",
    )


def _no_provider(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "")
    monkeypatch.setattr(settings, "smtp_host", "")


async def _get_user(db: AsyncSession, email: str) -> User:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one()


class TestAutoVerify:
    async def test_onprem_without_provider_auto_verifies(
        self, db: AsyncSession, admin_role, monkeypatch
    ):
        monkeypatch.setattr(settings, "deployment_mode", "onprem")
        _no_provider(monkeypatch)
        data = _register_data()

        resp = await service.register(db, data)

        assert resp["auto_verified"] is True
        assert resp["pending_verification"] is False
        user = await _get_user(db, data.email)
        assert user.email_verified_at is not None

        # The whole point: login works immediately, no verification step.
        login = await service.login(db, data.email, "password123")
        assert "access_token" in login

    async def test_saas_without_provider_stays_pending(
        self, db: AsyncSession, admin_role, monkeypatch, caplog
    ):
        monkeypatch.setattr(settings, "deployment_mode", "saas")
        _no_provider(monkeypatch)
        data = _register_data()

        with caplog.at_level(logging.WARNING):
            resp = await service.register(db, data)

        assert resp["auto_verified"] is False
        assert resp["pending_verification"] is True
        user = await _get_user(db, data.email)
        assert user.email_verified_at is None
        # SaaS must never print verification links to the log.
        assert LINK_MARKER not in caplog.text

    async def test_onprem_with_provider_stays_pending(
        self, db: AsyncSession, admin_role, monkeypatch, caplog
    ):
        monkeypatch.setattr(settings, "deployment_mode", "onprem")
        monkeypatch.setattr(settings, "smtp_host", "smtp.test")
        monkeypatch.setattr(settings, "resend_api_key", "")
        monkeypatch.setattr(
            "app.modules.auth.service.send_verification_email", lambda *a, **k: True
        )
        data = _register_data()

        with caplog.at_level(logging.WARNING):
            resp = await service.register(db, data)

        assert resp["auto_verified"] is False
        assert resp["pending_verification"] is True
        user = await _get_user(db, data.email)
        assert user.email_verified_at is None
        assert LINK_MARKER not in caplog.text


class TestVerificationLinkLogFallback:
    async def test_onprem_failed_send_logs_link(
        self, db: AsyncSession, admin_role, monkeypatch, caplog
    ):
        monkeypatch.setattr(settings, "deployment_mode", "onprem")
        monkeypatch.setattr(settings, "smtp_host", "smtp.test")
        monkeypatch.setattr(settings, "resend_api_key", "")
        monkeypatch.setattr(
            "app.modules.auth.service.send_verification_email", lambda *a, **k: False
        )
        data = _register_data()

        with caplog.at_level(logging.WARNING):
            resp = await service.register(db, data)

        assert resp["pending_verification"] is True
        assert LINK_MARKER in caplog.text
        assert "/verify-email?token=" in caplog.text
        assert data.email in caplog.text

    async def test_onprem_send_exception_logs_link(
        self, db: AsyncSession, admin_role, monkeypatch, caplog
    ):
        def _boom(*a, **k):
            raise RuntimeError("smtp down")

        monkeypatch.setattr(settings, "deployment_mode", "onprem")
        monkeypatch.setattr(settings, "smtp_host", "smtp.test")
        monkeypatch.setattr(settings, "resend_api_key", "")
        monkeypatch.setattr("app.modules.auth.service.send_verification_email", _boom)
        data = _register_data()

        with caplog.at_level(logging.WARNING):
            resp = await service.register(db, data)

        # Registration itself must survive the delivery failure.
        assert resp["pending_verification"] is True
        assert LINK_MARKER in caplog.text

    async def test_saas_failed_send_does_not_log_link(
        self, db: AsyncSession, admin_role, monkeypatch, caplog
    ):
        monkeypatch.setattr(settings, "deployment_mode", "saas")
        monkeypatch.setattr(settings, "smtp_host", "smtp.test")
        monkeypatch.setattr(settings, "resend_api_key", "")
        monkeypatch.setattr(
            "app.modules.auth.service.send_verification_email", lambda *a, **k: False
        )
        data = _register_data()

        with caplog.at_level(logging.WARNING):
            await service.register(db, data)

        assert LINK_MARKER not in caplog.text

    async def test_resend_verification_never_raises(
        self, db: AsyncSession, admin_role, monkeypatch
    ):
        """Token creation failure must not escape: a raise on the resend
        path would leak email existence through the response differential
        (and 500 a registration that already committed)."""

        def _boom(*a, **k):
            raise RuntimeError("jwt misconfigured")

        monkeypatch.setattr(settings, "deployment_mode", "onprem")
        monkeypatch.setattr(settings, "smtp_host", "smtp.test")
        monkeypatch.setattr(settings, "resend_api_key", "")
        monkeypatch.setattr(
            "app.modules.auth.service.send_verification_email", lambda *a, **k: True
        )
        data = _register_data()
        await service.register(db, data)

        monkeypatch.setattr(
            "app.modules.auth.service.create_email_verification_token", _boom
        )
        await service.resend_verification(db, data.email)  # must not raise

    async def test_resend_verification_failed_send_logs_link(
        self, db: AsyncSession, admin_role, monkeypatch, caplog
    ):
        monkeypatch.setattr(settings, "deployment_mode", "onprem")
        monkeypatch.setattr(settings, "smtp_host", "smtp.test")
        monkeypatch.setattr(settings, "resend_api_key", "")
        monkeypatch.setattr(
            "app.modules.auth.service.send_verification_email", lambda *a, **k: True
        )
        data = _register_data()
        await service.register(db, data)

        monkeypatch.setattr(
            "app.modules.auth.service.send_verification_email", lambda *a, **k: False
        )
        with caplog.at_level(logging.WARNING):
            await service.resend_verification(db, data.email)

        assert LINK_MARKER in caplog.text
        assert "/verify-email?token=" in caplog.text
