"""Branded HTML email templates with Jinja2 rendering.

All emails share a common base layout with the installation brand
(HRP-393: BRAND_NAME / BRAND_LOGO_URL / BRAND_ACCENT_COLOR settings,
stock HRPulsar by default), inline CSS, and a consistent footer. Templates are rendered
as Python strings (no external template files needed).
"""

from jinja2 import BaseLoader, Environment
from markupsafe import escape

from app.config import settings

TEXT_COLOR = "#1a1f36"
MUTED_COLOR = "#6b7280"
BG_COLOR = "#f9fafb"
CARD_BG = "#ffffff"


def _brand_name_html() -> str:
    """Brand name (HRP-393) escaped for interpolation into HTML bodies;
    subjects and plain contexts read settings.brand_name directly."""
    return str(escape(settings.brand_name))


def frontend_url() -> str:
    """Base URL for links in outbound email (HRP-390), resolved per call.

    FRONTEND_URL setting first. Without it, SaaS keeps the canonical
    hosted domain (the pre-HRP-390 hardcode — the link base must never
    silently follow CORS_ORIGINS ordering in a multi-tenant deploy),
    while self-hosted falls back to the first CORS origin so deep links
    point at the operator's instance.
    """
    base = (settings.frontend_url or "").rstrip("/")
    if base:
        return base
    if settings.deployment_mode == "saas":
        return "https://hrpulsar.com"
    origins = [
        o.strip().rstrip("/")
        for o in (settings.cors_origins or "").split(",")
        if o.strip()
    ]
    return origins[0] if origins else "https://hrpulsar.com"


_env = Environment(loader=BaseLoader(), autoescape=True)


# ---------------------------------------------------------------------------
# Base layout
# ---------------------------------------------------------------------------

BASE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ subject }}</title>
</head>
<body style="margin: 0; padding: 0; background-color: {{ bg_color }}; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: {{ bg_color }};">
    <tr>
      <td align="center" style="padding: 40px 16px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width: 520px; background-color: {{ card_bg }}; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);">
          <!-- Header -->
          <tr>
            <td style="padding: 32px 32px 0 32px;">
              <a href="{{ frontend_url }}" style="text-decoration: none; border: 0;">
                {{ logo_html | safe }}
              </a>
            </td>
          </tr>
          <!-- Content -->
          <tr>
            <td style="padding: 24px 32px 32px 32px;">
              {{ content | safe }}
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding: 0 32px 24px 32px; border-top: 1px solid #e5e7eb;">
              <p style="margin: 16px 0 0 0; font-size: 12px; line-height: 1.5; color: {{ muted_color }};">
                This is an automated message from <a href="{{ frontend_url }}" style="color: {{ brand_color }}; text-decoration: none;">{{ brand_name }}</a>.
                Please do not reply to this email.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _logo_html(base_url: str) -> str:
    """Header logo markup. A custom BRAND_LOGO_URL drops the fixed width so
    logos with a different aspect ratio scale from the 31px height; the
    stock markup is kept byte-identical for default builds."""
    custom = (settings.brand_logo_url or "").strip()
    name = _brand_name_html()
    if custom:
        return (
            f'<img src="{escape(custom)}" height="31" alt="{name}" '
            f'style="display: block; height: 31px; width: auto; border: 0;">'
        )
    return (
        f'<img src="{base_url}/brand/logo-horizontal-color-light.png" '
        f'width="160" height="31" alt="{name}" '
        f'style="display: block; width: 160px; height: 31px; border: 0;">'
    )


def _render(subject: str, content_html: str) -> str:
    """Render content into the base email layout."""
    base_url = frontend_url()
    tpl = _env.from_string(BASE_TEMPLATE)
    return tpl.render(
        subject=subject,
        content=content_html,
        brand_name=settings.brand_name,
        logo_html=_logo_html(base_url),
        brand_color=settings.brand_accent_color,
        text_color=TEXT_COLOR,
        muted_color=MUTED_COLOR,
        bg_color=BG_COLOR,
        card_bg=CARD_BG,
        frontend_url=base_url,
    )


def _button(url: str, label: str) -> str:
    """Generate a CTA button."""
    return (
        f'<a href="{url}" style="display: inline-block; background: {settings.brand_accent_color}; '
        f"color: #ffffff; padding: 12px 28px; border-radius: 6px; text-decoration: none; "
        f'font-weight: 500; font-size: 14px; line-height: 1;">{label}</a>'
    )


def _heading(text: str) -> str:
    return f'<h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 600; color: {TEXT_COLOR};">{text}</h2>'


def _paragraph(text: str) -> str:
    return f'<p style="margin: 0 0 16px 0; font-size: 14px; line-height: 1.6; color: {TEXT_COLOR};">{text}</p>'


def _assessment_url(assessment_id: str | None) -> str:
    """HRP-84 REDO: deep-link straight to the assessment page when we know
    the id; fall back to the list view otherwise (legacy callers).

    The auth middleware appends ``?next=`` for unauthenticated visitors so
    the login form bounces back here after sign-in — the email just needs
    to send the user to the canonical URL.
    """
    if assessment_id:
        return f"{frontend_url()}/assessments/{assessment_id}"
    return f"{frontend_url()}/assessments"


def _muted(text: str) -> str:
    return f'<p style="margin: 16px 0 0 0; font-size: 13px; line-height: 1.5; color: {MUTED_COLOR};">{text}</p>'


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


def render_verification_email(token: str) -> tuple[str, str]:
    """Return (subject, html_body) for email verification."""
    verify_url = f"{frontend_url()}/verify-email?token={token}"
    subject = f"Verify your email — {settings.brand_name}"
    content = (
        _heading("Verify your email")
        + _paragraph(
            f"Click the button below to verify your email address and activate your {_brand_name_html()} account."
        )
        + f'<div style="margin: 24px 0;">{_button(verify_url, "Verify Email")}</div>'
        + _muted(
            "This link expires in 24 hours. If you didn't create an account, ignore this email."
        )
    )
    return subject, _render(subject, content)


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


def render_password_reset_email(token: str) -> tuple[str, str]:
    """Return (subject, html_body) for password reset."""
    reset_url = f"{frontend_url()}/reset-password?token={token}"
    subject = f"Reset your password — {settings.brand_name}"
    content = (
        _heading("Reset your password")
        + _paragraph(
            "We received a request to reset your password. Click the button below to choose a new one."
        )
        + f'<div style="margin: 24px 0;">{_button(reset_url, "Reset Password")}</div>'
        + _muted(
            "This link expires in 15 minutes. If you didn't request a password reset, ignore this email."
        )
    )
    return subject, _render(subject, content)


# ---------------------------------------------------------------------------
# Moderated signup (M-wave)
# ---------------------------------------------------------------------------


def render_signup_verify_email(token: str) -> tuple[str, str]:
    """Verify-email link emailed after /api/signup-request."""
    verify_url = f"{frontend_url()}/verify-email?token={token}&flow=signup"
    subject = f"Confirm your email — {settings.brand_name}"
    content = (
        _heading("Confirm your email")
        + _paragraph(
            f"Thanks for requesting access to {_brand_name_html()}. "
            "Confirm your email address so our team can review your request."
        )
        + f'<div style="margin: 24px 0;">{_button(verify_url, "Confirm Email")}</div>'
        + _muted(
            "After confirming, our team typically reviews new requests "
            "within 24 hours. This link expires in 24 hours."
        )
    )
    return subject, _render(subject, content)


def render_signup_rejected_email(reason: str | None) -> tuple[str, str]:
    """Notification sent after a moderator rejects a signup request."""
    subject = f"Update on your {settings.brand_name} request"
    body = _heading(f"Update on your {_brand_name_html()} request") + _paragraph(
        "We've reviewed your request and unfortunately can't open "
        "an account at this time."
    )
    if reason:
        body += _paragraph(f"Note from our team: {escape(reason)}")
    body += _muted(
        "If this is unexpected, reply to this email and we'll take another look."
    )
    return subject, _render(subject, body)


def render_magic_login_email(token: str, company_name: str | None) -> tuple[str, str]:
    """One-time login link emailed after a signup is approved."""
    login_url = f"{frontend_url()}/magic-login?token={token}"
    subject = f"Welcome to {settings.brand_name} — your account is ready"
    intro = (
        f"Your {_brand_name_html()} account for {escape(company_name)} is ready."
        if company_name
        else f"Your {_brand_name_html()} account is ready."
    )
    content = (
        _heading("You're in")
        + _paragraph(intro)
        + _paragraph("Use the button below to sign in. This link works once.")
        + f'<div style="margin: 24px 0;">{_button(login_url, "Sign in")}</div>'
        + _muted(
            "Link expires in 24 hours. If you didn't request access, "
            "ignore this email."
        )
    )
    return subject, _render(subject, content)


# ---------------------------------------------------------------------------
# Invitation
# ---------------------------------------------------------------------------


def render_invitation_email(
    name: str, token: str, expire_days: int = 7
) -> tuple[str, str]:
    """Return (subject, html_body) for user invitation."""
    accept_url = f"{frontend_url()}/accept-invite?token={token}"
    subject = f"You're invited to join {settings.brand_name}"
    content = (
        _heading(f"Hi {escape(name)}, you're invited!")
        + _paragraph(
            f"You've been invited to join your team on {_brand_name_html()} — "
            "a platform for managing talent, competencies, and employee development."
        )
        + _paragraph("Click the button below to set up your account and get started.")
        + f'<div style="margin: 24px 0;">{_button(accept_url, "Accept Invitation")}</div>'
        + _muted(f"This invitation expires in {expire_days} days.")
    )
    return subject, _render(subject, content)


def render_invitation_reminder_email(
    name: str, token: str, expire_days: int = 7
) -> tuple[str, str]:
    """Return (subject, html_body) for invitation reminder."""
    accept_url = f"{frontend_url()}/accept-invite?token={token}"
    subject = f"Reminder: You're invited to join {settings.brand_name}"
    content = (
        _heading(f"Hi {escape(name)}, your invitation is waiting")
        + _paragraph(
            f"You have a pending invitation to join your team on {_brand_name_html()}. Don't miss out!"
        )
        + f'<div style="margin: 24px 0;">{_button(accept_url, "Accept Invitation")}</div>'
        + _muted(f"This invitation expires in {expire_days} days.")
    )
    return subject, _render(subject, content)


# ---------------------------------------------------------------------------
# Assessment notifications
# ---------------------------------------------------------------------------


def render_assessment_assigned_email(
    assessment_title: str,
    deadline: str | None = None,
    assessment_id: str | None = None,
) -> tuple[str, str]:
    """Generic Evaluate-employee email used for peer / subordinate / external
    participants and as a fallback for unknown roles."""
    subject = f"Evaluate employee: {assessment_title}"
    deadline_line = f" The deadline is <strong>{deadline}</strong>." if deadline else ""
    content = (
        _heading("Evaluate employee")
        + _paragraph(
            f"You have been assigned as a participant in the assessment "
            f'"<strong>{assessment_title}</strong>".{deadline_line}'
        )
        + _paragraph(f"Please log in to {_brand_name_html()} to submit your evaluation.")
        + f'<div style="margin: 24px 0;">{_button(_assessment_url(assessment_id), "Open Assessment")}</div>'
    )
    return subject, _render(subject, content)


def render_assessment_completed_email(
    assessment_title: str, assessment_id: str | None = None
) -> tuple[str, str]:
    """HRP-84: self-role completion email — "Your assessment has completed"."""
    subject = f"Your assessment has completed: {assessment_title}"
    content = (
        _heading("Your assessment has completed")
        + _paragraph(
            f'The assessment "<strong>{assessment_title}</strong>" has been '
            f"completed. Results are now available."
        )
        + f'<div style="margin: 24px 0;">{_button(_assessment_url(assessment_id), "View Results")}</div>'
    )
    return subject, _render(subject, content)


# HRP-84: per-role messaging on lifecycle events (send / late-add / complete /
# cancel). Distinct subjects/headings let participants triage their inbox
# without opening every assessment email.


def render_assessment_self_evaluate_email(
    assessment_title: str,
    deadline: str | None = None,
    assessment_id: str | None = None,
) -> tuple[str, str]:
    """Self-role: "Evaluate yourself" email triggered on Draft → Sent."""
    subject = f"Evaluate yourself: {assessment_title}"
    deadline_line = f" The deadline is <strong>{deadline}</strong>." if deadline else ""
    content = (
        _heading("Evaluate yourself")
        + _paragraph(
            f'The self-assessment "<strong>{assessment_title}</strong>" is '
            f"now open for you.{deadline_line}"
        )
        + _paragraph(f"Please log in to {_brand_name_html()} and complete your evaluation.")
        + f'<div style="margin: 24px 0;">{_button(_assessment_url(assessment_id), "Open Assessment")}</div>'
    )
    return subject, _render(subject, content)


def render_assessment_manager_evaluate_email(
    assessment_title: str,
    employee_name: str | None = None,
    deadline: str | None = None,
    assessment_id: str | None = None,
) -> tuple[str, str]:
    """Manager role: "Evaluate your employee" email."""
    who = f" of <strong>{employee_name}</strong>" if employee_name else ""
    subject = f"Evaluate your employee: {assessment_title}"
    deadline_line = f" The deadline is <strong>{deadline}</strong>." if deadline else ""
    content = (
        _heading("Evaluate your employee")
        + _paragraph(
            f'The assessment "<strong>{assessment_title}</strong>"{who} is '
            f"ready for your input.{deadline_line}"
        )
        + _paragraph(f"Please log in to {_brand_name_html()} and submit your evaluation.")
        + f'<div style="margin: 24px 0;">{_button(_assessment_url(assessment_id), "Open Assessment")}</div>'
    )
    return subject, _render(subject, content)


def render_assessment_manager_completed_email(
    assessment_title: str,
    employee_name: str | None = None,
    assessment_id: str | None = None,
) -> tuple[str, str]:
    """Manager role: "Your employee assessment has completed"."""
    who = f" for <strong>{employee_name}</strong>" if employee_name else ""
    subject = f"Employee assessment completed: {assessment_title}"
    content = (
        _heading("Your employee assessment has completed")
        + _paragraph(
            f'The assessment "<strong>{assessment_title}</strong>"{who} has '
            f"been completed. Results are now available."
        )
        + f'<div style="margin: 24px 0;">{_button(_assessment_url(assessment_id), "View Results")}</div>'
    )
    return subject, _render(subject, content)


def render_assessment_self_cancelled_email(
    assessment_title: str,
    assessment_id: str | None = None,
) -> tuple[str, str]:
    """Self-role: "Your assessment cancelled"."""
    subject = f"Your assessment cancelled: {assessment_title}"
    content = (
        _heading("Your assessment cancelled")
        + _paragraph(
            f'The assessment "<strong>{assessment_title}</strong>" has been '
            f"cancelled. No further action is required from you."
        )
        + f'<div style="margin: 24px 0;">{_button(_assessment_url(assessment_id), "Open Assessment")}</div>'
    )
    return subject, _render(subject, content)


def render_assessment_manager_cancelled_email(
    assessment_title: str,
    employee_name: str | None = None,
    assessment_id: str | None = None,
) -> tuple[str, str]:
    """Manager role: "Your employee assessment cancelled"."""
    who = f" for <strong>{employee_name}</strong>" if employee_name else ""
    subject = f"Employee assessment cancelled: {assessment_title}"
    content = (
        _heading("Your employee assessment cancelled")
        + _paragraph(
            f'The assessment "<strong>{assessment_title}</strong>"{who} has '
            f"been cancelled. No further action is required from you."
        )
        + f'<div style="margin: 24px 0;">{_button(_assessment_url(assessment_id), "Open Assessment")}</div>'
    )
    return subject, _render(subject, content)


def render_assessment_peer_cancelled_email(
    assessment_title: str,
    employee_name: str | None = None,
    assessment_id: str | None = None,
) -> tuple[str, str]:
    """Peer / subordinate / external reviewer: "Evaluation cancelled".

    HRP-84 REDO: mid-flight reviewers receive a dedicated copy (they were
    evaluating someone, not being evaluated themselves and not the
    employee's manager) so the inbox copy matches what they were actually
    asked to do.
    """
    who = f" of <strong>{employee_name}</strong>" if employee_name else ""
    subject = f"Evaluation cancelled: {assessment_title}"
    content = (
        _heading("Evaluation cancelled")
        + _paragraph(
            f'The evaluation{who} for "<strong>{assessment_title}</strong>" '
            f"has been cancelled. No further action is required from you."
        )
        + f'<div style="margin: 24px 0;">{_button(_assessment_url(assessment_id), "Open Assessment")}</div>'
    )
    return subject, _render(subject, content)


# ---------------------------------------------------------------------------
# PDP notifications
# ---------------------------------------------------------------------------


def render_pdp_sent_email(
    employee_name: str,
    deadline: str | None = None,
    *,
    pdp_title: str | None = None,
) -> tuple[str, str]:
    """Return (subject, html_body) for PDP assignment."""
    title = (pdp_title or "").strip()
    subject = (
        f"Development plan assigned: {title}" if title else "Development plan assigned"
    )
    heading_html = (
        f"Development plan assigned: {escape(title)}"
        if title
        else "Development plan assigned"
    )
    deadline_line = f" The deadline is <strong>{deadline}</strong>." if deadline else ""
    intro = (
        f'The development plan "<strong>{escape(title)}</strong>" has been assigned to '
        f"<strong>{employee_name}</strong>.{deadline_line}"
        if title
        else f"A personal development plan has been assigned to "
        f"<strong>{employee_name}</strong>.{deadline_line}"
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + _paragraph("Please review the plan items and start working on them.")
        + f'<div style="margin: 24px 0;">{_button(frontend_url() + "/development", "View Plan")}</div>'
    )
    return subject, _render(subject, content)


def render_pdp_returned_email(
    employee_name: str, pdp_title: str | None = None
) -> tuple[str, str]:
    """Return (subject, html_body) for PDP return to the plan owner."""
    title = (pdp_title or "").strip()
    subject = (
        f"Development plan returned: {title}" if title else "Development plan returned"
    )
    heading_html = (
        f"Development plan returned: {escape(title)}"
        if title
        else "Development plan returned"
    )
    intro = (
        f'The development plan "<strong>{escape(title)}</strong>" assigned to '
        f"<strong>{employee_name}</strong> has been returned for revision."
        if title
        else f"The development plan for <strong>{employee_name}</strong> has been "
        f"returned for revision."
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + _paragraph("Please review the comments and update the plan.")
        + f'<div style="margin: 24px 0;">{_button(frontend_url() + "/development", "View Plan")}</div>'
    )
    return subject, _render(subject, content)


def render_pdp_review_submitted_email(
    employee_name: str, pdp_title: str | None = None
) -> tuple[str, str]:
    """Reviewer notification: the employee has submitted their plan for review."""
    title = (pdp_title or "").strip()
    subject = (
        f"Your employee's development plan submitted for review: {title}"
        if title
        else "Your employee's development plan submitted for review"
    )
    heading_html = (
        f"Plan submitted for review: {escape(title)}"
        if title
        else "Plan submitted for review"
    )
    intro = (
        f"<strong>{employee_name}</strong> has submitted their development plan "
        f'"<strong>{escape(title)}</strong>" for your review.'
        if title
        else f"<strong>{employee_name}</strong> has submitted their development plan "
        f"for your review."
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + _paragraph("Open the plan to accept items or return it with comments.")
        + f'<div style="margin: 24px 0;">{_button(frontend_url() + "/development", "View Plan")}</div>'
    )
    return subject, _render(subject, content)


def render_pdp_done_to_employee_email(
    employee_name: str, pdp_title: str | None = None
) -> tuple[str, str]:
    """Employee notification: their development plan has been completed."""
    title = (pdp_title or "").strip()
    subject = (
        f"Your development plan completed: {title}"
        if title
        else "Your development plan completed"
    )
    heading_html = (
        f"Development plan completed: {escape(title)}"
        if title
        else "Development plan completed"
    )
    intro = (
        f"Congratulations, <strong>{employee_name}</strong> — your development plan "
        f'"<strong>{escape(title)}</strong>" is now marked as completed.'
        if title
        else f"Congratulations, <strong>{employee_name}</strong> — your development "
        f"plan is now marked as completed."
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + f'<div style="margin: 24px 0;">{_button(frontend_url() + "/development", "View Plan")}</div>'
    )
    return subject, _render(subject, content)


def render_pdp_done_to_reviewer_email(
    employee_name: str, pdp_title: str | None = None
) -> tuple[str, str]:
    """Reviewer notification: their employee's plan has been completed."""
    title = (pdp_title or "").strip()
    subject = (
        f"Your employee's development plan completed: {title}"
        if title
        else "Your employee's development plan completed"
    )
    heading_html = (
        f"Employee's plan completed: {escape(title)}"
        if title
        else "Employee's plan completed"
    )
    intro = (
        f"<strong>{employee_name}</strong> has completed the development plan "
        f'"<strong>{escape(title)}</strong>".'
        if title
        else f"<strong>{employee_name}</strong> has completed their development plan."
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + f'<div style="margin: 24px 0;">{_button(frontend_url() + "/development", "View Plan")}</div>'
    )
    return subject, _render(subject, content)


def render_pdp_cancelled_to_employee_email(
    employee_name: str, pdp_title: str | None = None
) -> tuple[str, str]:
    """Employee notification: their development plan has been cancelled."""
    title = (pdp_title or "").strip()
    subject = (
        f"Your development plan cancelled: {title}"
        if title
        else "Your development plan cancelled"
    )
    heading_html = (
        f"Development plan cancelled: {escape(title)}"
        if title
        else "Development plan cancelled"
    )
    intro = (
        f'The development plan "<strong>{escape(title)}</strong>" assigned to '
        f"<strong>{employee_name}</strong> has been cancelled."
        if title
        else f"The development plan for <strong>{employee_name}</strong> has been cancelled."
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + f'<div style="margin: 24px 0;">{_button(frontend_url() + "/development", "View Plans")}</div>'
    )
    return subject, _render(subject, content)


def render_pdp_cancelled_to_reviewer_email(
    employee_name: str, pdp_title: str | None = None
) -> tuple[str, str]:
    """Reviewer notification: their employee's plan has been cancelled."""
    title = (pdp_title or "").strip()
    subject = (
        f"Your employee's development plan cancelled: {title}"
        if title
        else "Your employee's development plan cancelled"
    )
    heading_html = (
        f"Employee's plan cancelled: {escape(title)}"
        if title
        else "Employee's plan cancelled"
    )
    intro = (
        f"The development plan for <strong>{employee_name}</strong> "
        f'("<strong>{escape(title)}</strong>") has been cancelled.'
        if title
        else f"The development plan for <strong>{employee_name}</strong> has been cancelled."
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + f'<div style="margin: 24px 0;">{_button(frontend_url() + "/development", "View Plans")}</div>'
    )
    return subject, _render(subject, content)


# ---------------------------------------------------------------------------
# Exam notifications
# ---------------------------------------------------------------------------


def render_exam_assigned_email(
    exam_title: str, deadline: str | None = None
) -> tuple[str, str]:
    """Return (subject, html_body) for exam assignment."""
    subject = f"Exam assigned: {exam_title}"
    deadline_line = f" The deadline is <strong>{deadline}</strong>." if deadline else ""
    content = (
        _heading("Exam assigned")
        + _paragraph(
            f'You have been assigned the exam "<strong>{exam_title}</strong>".{deadline_line}'
        )
        + f'<div style="margin: 24px 0;">{_button(frontend_url() + "/exams", "View Exam")}</div>'
    )
    return subject, _render(subject, content)


def render_exam_results_email(
    exam_title: str, score: int | float, max_score: int | float
) -> tuple[str, str]:
    """Return (subject, html_body) for exam results."""
    subject = f"Exam results: {exam_title}"
    content = (
        _heading("Exam results")
        + _paragraph(
            f'Your results for the exam "<strong>{exam_title}</strong>" are ready.'
        )
        + f'<div style="margin: 0 0 16px 0; padding: 16px; background: {BG_COLOR}; border-radius: 6px; text-align: center;">'
        + f'<span style="font-size: 24px; font-weight: 700; color: {TEXT_COLOR};">{score}</span>'
        + f'<span style="font-size: 16px; color: {MUTED_COLOR};"> / {max_score}</span>'
        + "</div>"
        + f'<div style="margin: 24px 0;">{_button(frontend_url() + "/exams", "View Details")}</div>'
    )
    return subject, _render(subject, content)


# ---------------------------------------------------------------------------
# Certificate expiry
# ---------------------------------------------------------------------------


def render_certificate_expiry_email(
    course_title: str, expiry_date: str, days_left: int, employee_name: str
) -> tuple[str, str]:
    """Return (subject, html_body) for certificate expiry warning."""
    subject = f"Certificate expiring soon: {course_title}"
    content = (
        _heading("Certificate expiring soon")
        + _paragraph(
            f'The certificate for "<strong>{course_title}</strong>" '
            f"({employee_name}) expires on <strong>{expiry_date}</strong> "
            f"({days_left} days remaining)."
        )
        + _paragraph("Please arrange for renewal before the expiration date.")
        + f'<div style="margin: 24px 0;">{_button(frontend_url() + "/employees", "View Employee")}</div>'
    )
    return subject, _render(subject, content)


# ---------------------------------------------------------------------------
# Deadline reminder
# ---------------------------------------------------------------------------


def render_deadline_reminder_email(
    entity_type: str, entity_title: str, deadline: str
) -> tuple[str, str]:
    """Return (subject, html_body) for deadline reminder."""
    subject = f"Deadline approaching: {entity_title}"
    type_label = entity_type.upper()
    content = (
        _heading("Deadline approaching")
        + _paragraph(
            f'The {type_label} "<strong>{entity_title}</strong>" '
            f"has a deadline of <strong>{deadline}</strong>. "
            f"Please make sure to complete it on time."
        )
        + f'<div style="margin: 24px 0;">{_button(frontend_url(), f"Open {_brand_name_html()}")}</div>'
    )
    return subject, _render(subject, content)


# ---------------------------------------------------------------------------
# External review invitation
# ---------------------------------------------------------------------------


def render_external_review_email(
    token: str, assessment_title: str, deadline: str | None = None
) -> tuple[str, str]:
    """Return (subject, html_body) for external reviewer invitation."""
    review_url = f"{frontend_url()}/review/{token}"
    subject = f"Review request: {assessment_title}"
    deadline_line = (
        f" Please complete by <strong>{deadline}</strong>." if deadline else ""
    )
    content = (
        _heading("Review request")
        + _paragraph(
            f"You have been invited to participate as an external reviewer in the assessment "
            f'"<strong>{assessment_title}</strong>".{deadline_line}'
        )
        + _paragraph(
            "Click the button below to submit your evaluation. No account is needed."
        )
        + f'<div style="margin: 24px 0;">{_button(review_url, "Start Review")}</div>'
    )
    return subject, _render(subject, content)


# ---------------------------------------------------------------------------
# Recruitment — invited evaluator (FR-20)
# ---------------------------------------------------------------------------


def _sanitize_subject(text: str) -> str:
    """Strip CR/LF and collapse whitespace to prevent SMTP header injection."""
    return " ".join(text.split())


def render_recruitment_invite_email(
    token: str,
    candidate_name: str,
    vacancy_title: str | None = None,
    *,
    expires_in_days: int = 7,
) -> tuple[str, str]:
    """Return (subject, html_body) for an external evaluator's recruiting invite."""
    invite_url = f"{frontend_url()}/recruitment/invite/{token}"
    subject = _sanitize_subject(f"Invitation to evaluate candidate {candidate_name}")
    vacancy_line = (
        f' for the role of "<strong>{escape(vacancy_title)}</strong>"'
        if vacancy_title
        else ""
    )
    content = (
        _heading(f"Candidate evaluation: {escape(candidate_name)}")
        + _paragraph(
            f"You've been invited to evaluate candidate <strong>{escape(candidate_name)}</strong>{vacancy_line}. "
            "The link below gives you direct access — no account is required."
        )
        + f'<div style="margin: 24px 0;">{_button(invite_url, "Open evaluation form")}</div>'
        + _muted(f"This link is valid for {expires_in_days} days.")
    )
    return subject, _render(subject, content)


def render_manager_assessment_invite_email(
    token: str,
    candidate_name: str,
    vacancy_title: str | None = None,
    *,
    evaluator_name: str | None = None,
    personal_message: str | None = None,
    expires_in_days: int = 7,
) -> tuple[str, str]:
    """Return (subject, html_body) for an HRP-186 external evaluator invite.

    Unlike :func:`render_recruitment_invite_email` (legacy R3 flow), the
    button targets the ``/public/assessments/{token}`` page and the body
    carries the recruiter's optional personal message.
    """
    invite_url = f"{frontend_url()}/public/assessments/{token}"
    subject = _sanitize_subject(f"Invitation to evaluate candidate {candidate_name}")
    greeting = (
        _paragraph(f"Hi <strong>{escape(evaluator_name)}</strong>,")
        if evaluator_name
        else ""
    )
    vacancy_line = (
        f' for the role of "<strong>{escape(vacancy_title)}</strong>"'
        if vacancy_title
        else ""
    )
    message_block = ""
    if personal_message and personal_message.strip():
        message_block = _muted("Message from the recruiter:") + _paragraph(
            f"<em>&ldquo;{escape(personal_message.strip())}&rdquo;</em>"
        )
    content = (
        _heading(f"Candidate evaluation: {escape(candidate_name)}")
        + greeting
        + _paragraph(
            f"You've been invited to evaluate candidate <strong>{escape(candidate_name)}</strong>{vacancy_line}. "
            "The link below gives you direct access — no account is required."
        )
        + message_block
        + f'<div style="margin: 24px 0;">{_button(invite_url, "Open evaluation form")}</div>'
        + _muted(f"This link is valid for {expires_in_days} days.")
    )
    return subject, _render(subject, content)


def render_recruitment_consent_email(
    token: str,
    candidate_name: str,
    template_body: str,
    *,
    expires_in_days: int = 14,
) -> tuple[str, str]:
    """Return (subject, html_body) for a candidate consent magic-link email."""

    consent_url = f"{frontend_url()}/recruitment/consent/{token}"
    subject = _sanitize_subject("Consent for interview recording and analysis")
    summary = (template_body or "").strip()
    if len(summary) > 600:
        summary = summary[:600].rsplit(" ", 1)[0] + "…"
    summary_html = _muted(escape(summary)) if summary else ""
    content = (
        _heading(f"Hello, {escape(candidate_name)}")
        + _paragraph(
            "To run an interview with recording and AI-powered analysis, "
            "we need your consent. Please review the terms and confirm "
            "via the link below — no account is required."
        )
        + summary_html
        + f'<div style="margin: 24px 0;">{_button(consent_url, "Review and sign consent")}</div>'
        + _muted(f"This link is valid for {expires_in_days} days.")
    )
    return subject, _render(subject, content)


# ---------------------------------------------------------------------------
# HRP-211 — Talent Market lifecycle notifications
#
# Six events: publish (matched / not-matched), candidate-added (matched /
# not-matched), appoint (employee + manager), complete (matched/not),
# cancel from Draft (employee + manager), cancel from Published
# (employee + manager plural + matched/not). Every email points back at
# the card detail page so a clicked link drops the recipient on the
# card after login.
# ---------------------------------------------------------------------------


def _talent_market_card_url(card_id: str) -> str:
    return f"{frontend_url()}/talent-market/{card_id}"


def _render_talent_email(
    *,
    subject: str,
    heading: str,
    paragraphs: list[str],
    card_id: str,
    cta_label: str | None = "Open card",
) -> tuple[str, str]:
    """Shared shell for the HRP-211 Talent Market emails.

    ``cta_label=None`` drops the card button — used when the recipient no
    longer has access to the card (HRP-245 redo).
    """
    body = _heading(heading)
    for p in paragraphs:
        body += _paragraph(p)
    if cta_label is not None:
        body += (
            f'<div style="margin: 24px 0;">'
            f"{_button(_talent_market_card_url(card_id), cta_label)}"
            f"</div>"
        )
    return subject, _render(subject, body)


def render_talent_market_matched_email(title: str, card_id: str) -> tuple[str, str]:
    """HRP-211: card published — candidate currently `matched`."""
    safe = escape(title)
    return _render_talent_email(
        subject=f"You're matched candidate: {title}",
        heading="You're a matched candidate",
        paragraphs=[
            f'You\'ve been picked as a matched candidate for "<strong>{safe}</strong>".',
            "Open the card to review the role and the requirements.",
        ],
        card_id=card_id,
    )


def render_talent_market_not_matched_email(title: str, card_id: str) -> tuple[str, str]:
    """HRP-211: card published — candidate currently `not_matched`."""
    safe = escape(title)
    return _render_talent_email(
        subject=f"You're a candidate: {title}",
        heading="You're a candidate",
        paragraphs=[
            f'You\'ve been added as a candidate on "<strong>{safe}</strong>".',
            "Open the card to see the requirements and where you stand.",
        ],
        card_id=card_id,
    )


def render_talent_market_appointed_self_email(
    title: str, card_id: str
) -> tuple[str, str]:
    """HRP-211: employee appointment notification."""
    safe = escape(title)
    return _render_talent_email(
        subject=f"You are appointed! {title}",
        heading="You're appointed",
        paragraphs=[
            f'You\'ve been appointed on "<strong>{safe}</strong>". ' "Congratulations!",
        ],
        card_id=card_id,
    )


def render_talent_market_appointed_manager_email(
    title: str, employee_name: str | None, card_id: str
) -> tuple[str, str]:
    """HRP-211: manager-side appointment notification."""
    safe_title = escape(title)
    who = (
        f" <strong>{escape(employee_name)}</strong>"
        if employee_name
        else " an employee"
    )
    return _render_talent_email(
        subject=f"Your employee appointed: {title}",
        heading="Your employee was appointed",
        paragraphs=[
            f'{who} has just been appointed on "<strong>{safe_title}</strong>".',
        ],
        card_id=card_id,
    )


def render_talent_market_completed_email(title: str, card_id: str) -> tuple[str, str]:
    """HRP-211: card moved to Completed — sent to every matched /
    not_matched candidate."""
    safe = escape(title)
    return _render_talent_email(
        subject=f"Appointment completed: {title}",
        heading="The appointment is complete",
        paragraphs=[
            f'The talent card "<strong>{safe}</strong>" has been marked '
            "Completed. The role is filled.",
        ],
        card_id=card_id,
    )


def render_talent_market_cancelled_self_email(
    title: str, card_id: str
) -> tuple[str, str]:
    """HRP-211: appointed employee notification when the card is cancelled."""
    safe = escape(title)
    return _render_talent_email(
        subject=f"Your appointment cancelled: {title}",
        heading="Your appointment was cancelled",
        paragraphs=[
            f'The appointment on "<strong>{safe}</strong>" has been ' "cancelled.",
        ],
        card_id=card_id,
    )


def render_talent_market_cancelled_manager_email(
    title: str, employee_name: str | None, card_id: str
) -> tuple[str, str]:
    """HRP-211: manager notification — single appointed employee cancelled
    (used from Draft cancel)."""
    safe_title = escape(title)
    who = (
        f" <strong>{escape(employee_name)}</strong>"
        if employee_name
        else " your employee"
    )
    return _render_talent_email(
        subject=f"Your employee's appointment cancelled: {title}",
        heading="Your employee's appointment was cancelled",
        paragraphs=[
            f"The appointment{who} on "
            f'"<strong>{safe_title}</strong>" has been cancelled.',
        ],
        card_id=card_id,
    )


def render_talent_market_cancelled_manager_plural_email(
    title: str, employee_names: list[str], card_id: str
) -> tuple[str, str]:
    """HRP-211: manager notification — multiple appointed employees were
    cancelled in one transition (Published cancel can hit several)."""
    safe_title = escape(title)
    name_line = (
        ", ".join(f"<strong>{escape(n)}</strong>" for n in employee_names)
        if employee_names
        else "your employees"
    )
    return _render_talent_email(
        subject=f"Your employees' appointment cancelled: {title}",
        heading="Your employees' appointment was cancelled",
        paragraphs=[
            f"The appointments for {name_line} on "
            f'"<strong>{safe_title}</strong>" have been cancelled.',
        ],
        card_id=card_id,
    )


def render_talent_market_cancelled_generic_email(
    title: str, card_id: str
) -> tuple[str, str]:
    """HRP-211: matched / not_matched candidates notification when the
    card transitions from Published to Cancelled."""
    safe = escape(title)
    return _render_talent_email(
        subject=f"Cancelled: {title}",
        heading="The talent card was cancelled",
        paragraphs=[
            f'The talent card "<strong>{safe}</strong>" you were on has '
            "been cancelled.",
        ],
        card_id=card_id,
    )


def render_talent_market_removed_candidate_email(
    title: str, card_id: str
) -> tuple[str, str]:
    """HRP-245: notify a candidate when they are removed from the
    Candidates block of a Published card.

    No "Open card" button (HRP-245 redo): a removed employee has no
    access to the Talent Market card any more.
    """
    safe = escape(title)
    return _render_talent_email(
        subject=f"You are not considered more: {title}",
        heading="You are not considered any more",
        paragraphs=[
            f"You have been removed from the candidates list on "
            f'"<strong>{safe}</strong>".',
        ],
        card_id=card_id,
        cta_label=None,
    )


def render_talent_market_reacted_manager_email(
    title: str, employee_name: str | None, card_id: str
) -> tuple[str, str]:
    """HRP-213: manager-side notification when an employee reacts to a
    Published card they're a candidate on."""
    safe_title = escape(title)
    who = (
        f"<strong>{escape(employee_name)}</strong>"
        if employee_name
        else "Your employee"
    )
    return _render_talent_email(
        subject=f"Your employee has reacted: {title}",
        heading="Your employee reacted to a talent card",
        paragraphs=[
            f"{who} has reacted to the talent card "
            f'"<strong>{safe_title}</strong>".',
        ],
        card_id=card_id,
    )
