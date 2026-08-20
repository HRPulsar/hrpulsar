"""Email sender. Supports Resend API (SaaS) and SMTP (self-hosted).

Returns (success: bool, message_id: str | None) for delivery tracking.
"""

import logging
import smtplib
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlsplit

from app.config import email_address_domain, settings

logger = logging.getLogger(__name__)


def enqueue_email(
    to: str,
    subject: str,
    html_body: str,
    *,
    tenant_id: str | None = None,
    template_code: str | None = None,
) -> None:
    """Fire-and-forget email send via Celery, with inline fallback.

    Tries `send_email_task.delay(...)` first — non-blocking, frees the DB
    connection that callers were holding while resend.Emails.send() ran
    synchronously (1–5 s blocking HTTP that pinned the request handler's
    pool slot).

    On `OperationalError` (broker unreachable in community/self-hosted
    builds without Redis) falls back to the inline sender. Any other
    exception is logged and swallowed — callers must not get an error
    bubble for an email that's already been queued/attempted.
    """
    try:
        from kombu.exceptions import OperationalError

        from app.core.tasks import _tenant_is_demo_sync, send_email_task

        try:
            send_email_task.delay(
                to,
                subject,
                html_body,
                tenant_id=tenant_id,
                template_code=template_code,
            )
            return
        except OperationalError:
            logger.warning(
                "Celery broker unavailable — falling back to inline send for %s", to
            )
            # HRP-253 (D5): mirror the in-task demo gate on the
            # broker-down branch — self-hosted installs without Redis
            # still must not leak email from a demo tenant.
            if tenant_id is not None and _tenant_is_demo_sync(tenant_id):
                logger.info(
                    "demo email skipped (inline fallback): tenant=%s recipient=%s",
                    tenant_id,
                    to,
                )
                return
            send_email(to, subject, html_body)
            return
    except Exception:
        logger.exception("enqueue_email failed for %s — email dropped", to)


def email_provider_configured() -> bool:
    """Whether any outbound email provider is configured (HRP-390).

    Mirrors the dispatch order in :func:`send_email` — keep the two in
    sync when adding a provider.
    """
    return bool(settings.resend_api_key or settings.smtp_host)


def send_email(to: str, subject: str, html_body: str) -> tuple[bool, str | None]:
    """Send an email via Resend or SMTP. Returns (success, message_id)."""
    if settings.resend_api_key:
        return _send_via_resend(to, subject, html_body)
    if settings.smtp_host:
        return _send_via_smtp(to, subject, html_body)

    logger.warning(
        "Email not configured (no RESEND_API_KEY or SMTP_HOST), skipping email to %s",
        to,
    )
    return False, None


def _send_via_resend(to: str, subject: str, html_body: str) -> tuple[bool, str | None]:
    try:
        import resend

        resend.api_key = settings.resend_api_key
        result = resend.Emails.send(
            {
                "from": settings.email_from,
                "to": [to],
                "subject": subject,
                "html": html_body,
            }
        )
        message_id = (
            result.get("id")
            if isinstance(result, dict)
            else getattr(result, "id", None)
        )
        logger.info("Email sent via Resend to %s: %s (id=%s)", to, subject, message_id)
        return True, message_id
    except Exception:
        logger.exception("Failed to send email via Resend to %s", to)
        return False, None


def _message_id_domain() -> str:
    """Domain stamped into generated SMTP Message-IDs (HRP-568).

    The EMAIL_FROM address domain first (the message id should carry the
    sending identity), then the public frontend host — the pre-HRP-568
    hardcode reduced to :func:`frontend_url`'s own last-resort default.
    The result is IDNA-encoded so the header stays a valid ASCII msg-id
    even for internationalized sender domains.
    """
    domain = email_address_domain(settings.email_from)
    if not domain:
        from app.core.email_templates import frontend_url

        base = frontend_url()
        if "://" not in base:
            # Schemeless value: urlsplit would read the host as the
            # scheme and report no hostname (same guard as the S3
            # validator in config.py).
            base = f"//{base}"
        domain = (urlsplit(base).hostname or "").lower()
    if domain:
        try:
            return domain.encode("idna").decode("ascii")
        except UnicodeError:
            pass
    return "localhost"


def _send_via_smtp(to: str, subject: str, html_body: str) -> tuple[bool, str | None]:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.email_from
        msg["To"] = to
        # Generate a message ID for tracking
        message_id = f"{uuid.uuid4().hex}@{_message_id_domain()}"
        msg["Message-ID"] = f"<{message_id}>"
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_user:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.email_from, to, msg.as_string())

        logger.info("Email sent via SMTP to %s: %s (id=%s)", to, subject, message_id)
        return True, message_id
    except Exception:
        logger.exception(
            "Failed to send email via SMTP to %s (relay %s:%s)",
            to,
            settings.smtp_host,
            settings.smtp_port,
        )
        return False, None


# --- Convenience email senders using branded templates ---
#
# i18n F4: every sender takes a keyword-only ``locale`` resolved by the
# caller from the *recipient's* context (User.language > Tenant.default_locale
# > Accept-Language > deployment default, see ``app.core.i18n``). The
# default stays ``"en"`` so a caller that has no recipient context keeps
# the pre-F4 output byte-for-byte.


def send_verification_email(to: str, token: str, *, locale: str = "en") -> bool:
    """Send email verification link."""
    from app.core.email_templates import render_verification_email

    subject, html = render_verification_email(token, locale=locale)
    ok, _ = send_email(to, subject, html)
    return ok


def send_signup_verify_email(to: str, token: str, *, locale: str = "en") -> bool:
    """Send the M-wave signup verification link."""
    from app.core.email_templates import render_signup_verify_email

    subject, html = render_signup_verify_email(token, locale=locale)
    ok, _ = send_email(to, subject, html)
    return ok


def send_signup_rejected_email(
    to: str, reason: str | None, *, locale: str = "en"
) -> bool:
    """Notify the visitor that their signup request was rejected."""
    from app.core.email_templates import render_signup_rejected_email

    subject, html = render_signup_rejected_email(reason, locale=locale)
    ok, _ = send_email(to, subject, html)
    return ok


def send_magic_login_email(
    to: str, token: str, company_name: str | None, *, locale: str = "en"
) -> bool:
    """Send the one-time magic-login link issued by Slack approval."""
    from app.core.email_templates import render_magic_login_email

    subject, html = render_magic_login_email(token, company_name, locale=locale)
    ok, _ = send_email(to, subject, html)
    return ok


def send_password_reset_email(to: str, token: str, *, locale: str = "en") -> bool:
    """Send password reset link."""
    from app.core.email_templates import render_password_reset_email

    subject, html = render_password_reset_email(token, locale=locale)
    ok, _ = send_email(to, subject, html)
    return ok


def send_invitation_email(
    to: str,
    name: str,
    token: str,
    expire_days: int = 7,
    *,
    tenant_id: uuid.UUID | str | None = None,
    locale: str = "en",
) -> bool:
    """Send user invitation.

    HRP-301 reverses the HRP-253 (D5) demo gate for invitations: demo
    tenants need a working invitation flow so a prospective HR admin can
    walk through the full onboarding loop. ``tenant_id`` is still
    accepted (and stamped on the EmailLog when this routes through
    Celery) so the lookup is available for non-invitation flows that
    keep the gate.
    """
    from app.core.email_templates import render_invitation_email

    subject, html = render_invitation_email(name, token, expire_days, locale=locale)
    ok, _ = send_email(to, subject, html)
    return ok


def send_invitation_reminder_email(
    to: str,
    name: str,
    token: str,
    expire_days: int = 7,
    *,
    tenant_id: uuid.UUID | str | None = None,
    locale: str = "en",
) -> bool:
    """Send invitation reminder. See ``send_invitation_email`` for the
    HRP-301 carve-out from the D5 demo email gate."""
    from app.core.email_templates import render_invitation_reminder_email

    subject, html = render_invitation_reminder_email(
        name, token, expire_days, locale=locale
    )
    ok, _ = send_email(to, subject, html)
    return ok
