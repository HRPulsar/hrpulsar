"""Branded HTML email templates with Jinja2 rendering.

All emails share a common base layout with the installation brand
(HRP-393: BRAND_NAME / BRAND_LOGO_URL / BRAND_ACCENT_COLOR settings,
stock HRPulsar by default), inline CSS, and a consistent footer. Templates are rendered
as Python strings (no external template files needed).

Copy lives in the ``email.*`` section of ``app/i18n/{locale}.json`` (i18n
F4): every ``render_*`` takes a keyword-only ``locale`` (default ``"en"``)
that selects the catalog and fills ``<html lang>``. Markup and the
HTML-escaping policy stay here — values are escaped at the call site and
handed to :func:`translate` as parameters, so catalog strings never decide
what gets escaped.
"""

from jinja2 import BaseLoader, Environment
from markupsafe import escape

from app.config import settings
from app.core.i18n import translate

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


def public_link(path: str, locale: str) -> str:
    """Public (signed-out) deep link carrying the recipient's locale.

    HRP-516: the recipient of an invitation never signs in, so the page
    would otherwise pick its language from their browser — a German
    company's external evaluator on an English-locale laptop got a German
    email and an English form. ``lang`` makes the page open in the
    language the email was written in; the switcher on the page can still
    override it.

    ``path`` may already carry a query (``/accept-invite?token=…``), so
    the separator is chosen rather than hardcoded — a second ``?`` would
    produce a link that no router can parse.
    """
    separator = "&" if "?" in path else "?"
    return f"{frontend_url()}{path}{separator}lang={locale}"


_env = Environment(loader=BaseLoader(), autoescape=True)


# ---------------------------------------------------------------------------
# Base layout
# ---------------------------------------------------------------------------

BASE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="{{ lang }}">
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
                {{ footer_automated | safe }}
                {{ footer_no_reply | safe }}
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


# Compiled once: the layout is a constant, and HRP-568 put _render on the
# per-recipient notification fan-out path where a per-call from_string()
# recompile (~80x the render cost) would be pure waste.
_base_template = _env.from_string(BASE_TEMPLATE)


def _render(subject: str, content_html: str, *, locale: str = "en") -> str:
    """Render content into the base email layout."""
    base_url = frontend_url()
    brand_link = (
        f'<a href="{base_url}" style="color: {settings.brand_accent_color}; '
        f'text-decoration: none;">{_brand_name_html()}</a>'
    )
    return _base_template.render(
        subject=subject,
        content=content_html,
        lang=locale,
        logo_html=_logo_html(base_url),
        footer_automated=translate(
            "email.footer_automated", locale, brand_link=brand_link
        ),
        footer_no_reply=translate("email.footer_no_reply", locale),
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


def render_verification_email(token: str, *, locale: str = "en") -> tuple[str, str]:
    """Return (subject, html_body) for email verification."""
    verify_url = f"{frontend_url()}/verify-email?token={token}"
    subject = translate(
        "email.verification.subject", locale, brand_name=settings.brand_name
    )
    button = _button(verify_url, translate("email.verification.button", locale))
    content = (
        _heading(translate("email.verification.heading", locale))
        + _paragraph(
            translate("email.verification.body", locale, brand_name=_brand_name_html())
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
        + _muted(translate("email.verification.note", locale))
    )
    return subject, _render(subject, content, locale=locale)


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


def render_password_reset_email(token: str, *, locale: str = "en") -> tuple[str, str]:
    """Return (subject, html_body) for password reset."""
    reset_url = f"{frontend_url()}/reset-password?token={token}"
    subject = translate(
        "email.password_reset.subject", locale, brand_name=settings.brand_name
    )
    button = _button(reset_url, translate("email.password_reset.button", locale))
    content = (
        _heading(translate("email.password_reset.heading", locale))
        + _paragraph(translate("email.password_reset.body", locale))
        + f'<div style="margin: 24px 0;">{button}</div>'
        + _muted(translate("email.password_reset.note", locale))
    )
    return subject, _render(subject, content, locale=locale)


# ---------------------------------------------------------------------------
# Moderated signup (M-wave)
# ---------------------------------------------------------------------------


def render_signup_verify_email(token: str, *, locale: str = "en") -> tuple[str, str]:
    """Verify-email link emailed after /api/signup-request."""
    verify_url = f"{frontend_url()}/verify-email?token={token}&flow=signup"
    subject = translate(
        "email.signup_verify.subject", locale, brand_name=settings.brand_name
    )
    button = _button(verify_url, translate("email.signup_verify.button", locale))
    content = (
        _heading(translate("email.signup_verify.heading", locale))
        + _paragraph(
            translate("email.signup_verify.body", locale, brand_name=_brand_name_html())
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
        + _muted(translate("email.signup_verify.note", locale))
    )
    return subject, _render(subject, content, locale=locale)


def render_signup_rejected_email(
    reason: str | None, *, locale: str = "en"
) -> tuple[str, str]:
    """Notification sent after a moderator rejects a signup request."""
    subject = translate(
        "email.signup_rejected.subject", locale, brand_name=settings.brand_name
    )
    body = _heading(
        translate(
            "email.signup_rejected.heading", locale, brand_name=_brand_name_html()
        )
    ) + _paragraph(translate("email.signup_rejected.body", locale))
    if reason:
        body += _paragraph(
            translate("email.signup_rejected.reason", locale, reason=escape(reason))
        )
    body += _muted(translate("email.signup_rejected.note", locale))
    return subject, _render(subject, body, locale=locale)


def render_magic_login_email(
    token: str, company_name: str | None, *, locale: str = "en"
) -> tuple[str, str]:
    """One-time login link emailed after a signup is approved."""
    login_url = f"{frontend_url()}/magic-login?token={token}"
    subject = translate(
        "email.magic_login.subject", locale, brand_name=settings.brand_name
    )
    intro = (
        translate(
            "email.magic_login.intro",
            locale,
            brand_name=_brand_name_html(),
            company_name=escape(company_name),
        )
        if company_name
        else translate(
            "email.magic_login.intro_no_company",
            locale,
            brand_name=_brand_name_html(),
        )
    )
    button = _button(login_url, translate("email.magic_login.button", locale))
    content = (
        _heading(translate("email.magic_login.heading", locale))
        + _paragraph(intro)
        + _paragraph(translate("email.magic_login.body", locale))
        + f'<div style="margin: 24px 0;">{button}</div>'
        + _muted(translate("email.magic_login.note", locale))
    )
    return subject, _render(subject, content, locale=locale)


# ---------------------------------------------------------------------------
# Invitation
# ---------------------------------------------------------------------------


def render_invitation_email(
    name: str, token: str, expire_days: int = 7, *, locale: str = "en"
) -> tuple[str, str]:
    """Return (subject, html_body) for user invitation."""
    accept_url = public_link(f"/accept-invite?token={token}", locale)
    subject = translate(
        "email.invitation.subject", locale, brand_name=settings.brand_name
    )
    button = _button(accept_url, translate("email.invitation.button", locale))
    content = (
        _heading(translate("email.invitation.heading", locale, name=escape(name)))
        + _paragraph(
            translate("email.invitation.intro", locale, brand_name=_brand_name_html())
        )
        + _paragraph(translate("email.invitation.body", locale))
        + f'<div style="margin: 24px 0;">{button}</div>'
        + _muted(translate("email.invitation.note", locale, expire_days=expire_days))
    )
    return subject, _render(subject, content, locale=locale)


def render_invitation_reminder_email(
    name: str, token: str, expire_days: int = 7, *, locale: str = "en"
) -> tuple[str, str]:
    """Return (subject, html_body) for invitation reminder."""
    accept_url = public_link(f"/accept-invite?token={token}", locale)
    subject = translate(
        "email.invitation_reminder.subject", locale, brand_name=settings.brand_name
    )
    button = _button(accept_url, translate("email.invitation_reminder.button", locale))
    content = (
        _heading(
            translate("email.invitation_reminder.heading", locale, name=escape(name))
        )
        + _paragraph(
            translate(
                "email.invitation_reminder.body", locale, brand_name=_brand_name_html()
            )
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
        + _muted(
            translate("email.invitation_reminder.note", locale, expire_days=expire_days)
        )
    )
    return subject, _render(subject, content, locale=locale)


# ---------------------------------------------------------------------------
# Assessment notifications
# ---------------------------------------------------------------------------


def render_assessment_assigned_email(
    assessment_title: str,
    deadline: str | None = None,
    assessment_id: str | None = None,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Generic Evaluate-employee email used for peer / subordinate / external
    participants and as a fallback for unknown roles."""
    subject = translate(
        "email.assessment_assigned.subject", locale, assessment_title=assessment_title
    )
    deadline_line = (
        translate("email.assessment_assigned.deadline_line", locale, deadline=deadline)
        if deadline
        else ""
    )
    button = _button(
        _assessment_url(assessment_id),
        translate("email.assessment_assigned.button", locale),
    )
    content = (
        _heading(translate("email.assessment_assigned.heading", locale))
        + _paragraph(
            translate(
                "email.assessment_assigned.intro",
                locale,
                assessment_title=escape(assessment_title),
                deadline_line=deadline_line,
            )
        )
        + _paragraph(
            translate(
                "email.assessment_assigned.body",
                locale,
                brand_name=_brand_name_html(),
            )
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_assessment_completed_email(
    assessment_title: str, assessment_id: str | None = None, *, locale: str = "en"
) -> tuple[str, str]:
    """HRP-84: self-role completion email — "Your assessment has completed"."""
    subject = translate(
        "email.assessment_completed.subject", locale, assessment_title=assessment_title
    )
    button = _button(
        _assessment_url(assessment_id),
        translate("email.assessment_completed.button", locale),
    )
    content = (
        _heading(translate("email.assessment_completed.heading", locale))
        + _paragraph(
            translate(
                "email.assessment_completed.body",
                locale,
                assessment_title=escape(assessment_title),
            )
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


# HRP-84: per-role messaging on lifecycle events (send / late-add / complete /
# cancel). Distinct subjects/headings let participants triage their inbox
# without opening every assessment email.


def render_assessment_self_evaluate_email(
    assessment_title: str,
    deadline: str | None = None,
    assessment_id: str | None = None,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Self-role: "Evaluate yourself" email triggered on Draft → Sent."""
    subject = translate(
        "email.assessment_self_evaluate.subject",
        locale,
        assessment_title=assessment_title,
    )
    deadline_line = (
        translate(
            "email.assessment_self_evaluate.deadline_line", locale, deadline=deadline
        )
        if deadline
        else ""
    )
    button = _button(
        _assessment_url(assessment_id),
        translate("email.assessment_self_evaluate.button", locale),
    )
    content = (
        _heading(translate("email.assessment_self_evaluate.heading", locale))
        + _paragraph(
            translate(
                "email.assessment_self_evaluate.intro",
                locale,
                assessment_title=escape(assessment_title),
                deadline_line=deadline_line,
            )
        )
        + _paragraph(
            translate(
                "email.assessment_self_evaluate.body",
                locale,
                brand_name=_brand_name_html(),
            )
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_assessment_manager_evaluate_email(
    assessment_title: str,
    employee_name: str | None = None,
    deadline: str | None = None,
    assessment_id: str | None = None,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Manager role: "Evaluate your employee" email."""
    who = (
        translate(
            "email.assessment_manager_evaluate.who",
            locale,
            employee_name=escape(employee_name),
        )
        if employee_name
        else ""
    )
    subject = translate(
        "email.assessment_manager_evaluate.subject",
        locale,
        assessment_title=assessment_title,
    )
    deadline_line = (
        translate(
            "email.assessment_manager_evaluate.deadline_line", locale, deadline=deadline
        )
        if deadline
        else ""
    )
    button = _button(
        _assessment_url(assessment_id),
        translate("email.assessment_manager_evaluate.button", locale),
    )
    content = (
        _heading(translate("email.assessment_manager_evaluate.heading", locale))
        + _paragraph(
            translate(
                "email.assessment_manager_evaluate.intro",
                locale,
                assessment_title=escape(assessment_title),
                who=who,
                deadline_line=deadline_line,
            )
        )
        + _paragraph(
            translate(
                "email.assessment_manager_evaluate.body",
                locale,
                brand_name=_brand_name_html(),
            )
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_assessment_manager_completed_email(
    assessment_title: str,
    employee_name: str | None = None,
    assessment_id: str | None = None,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Manager role: "Your employee assessment has completed"."""
    who = (
        translate(
            "email.assessment_manager_completed.who",
            locale,
            employee_name=escape(employee_name),
        )
        if employee_name
        else ""
    )
    subject = translate(
        "email.assessment_manager_completed.subject",
        locale,
        assessment_title=assessment_title,
    )
    button = _button(
        _assessment_url(assessment_id),
        translate("email.assessment_manager_completed.button", locale),
    )
    content = (
        _heading(translate("email.assessment_manager_completed.heading", locale))
        + _paragraph(
            translate(
                "email.assessment_manager_completed.body",
                locale,
                assessment_title=escape(assessment_title),
                who=who,
            )
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_assessment_self_cancelled_email(
    assessment_title: str,
    assessment_id: str | None = None,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Self-role: "Your assessment cancelled"."""
    subject = translate(
        "email.assessment_self_cancelled.subject",
        locale,
        assessment_title=assessment_title,
    )
    button = _button(
        _assessment_url(assessment_id),
        translate("email.assessment_self_cancelled.button", locale),
    )
    content = (
        _heading(translate("email.assessment_self_cancelled.heading", locale))
        + _paragraph(
            translate(
                "email.assessment_self_cancelled.body",
                locale,
                assessment_title=escape(assessment_title),
            )
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_assessment_manager_cancelled_email(
    assessment_title: str,
    employee_name: str | None = None,
    assessment_id: str | None = None,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Manager role: "Your employee assessment cancelled"."""
    who = (
        translate(
            "email.assessment_manager_cancelled.who",
            locale,
            employee_name=escape(employee_name),
        )
        if employee_name
        else ""
    )
    subject = translate(
        "email.assessment_manager_cancelled.subject",
        locale,
        assessment_title=assessment_title,
    )
    button = _button(
        _assessment_url(assessment_id),
        translate("email.assessment_manager_cancelled.button", locale),
    )
    content = (
        _heading(translate("email.assessment_manager_cancelled.heading", locale))
        + _paragraph(
            translate(
                "email.assessment_manager_cancelled.body",
                locale,
                assessment_title=escape(assessment_title),
                who=who,
            )
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_assessment_peer_cancelled_email(
    assessment_title: str,
    employee_name: str | None = None,
    assessment_id: str | None = None,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Peer / subordinate / external reviewer: "Evaluation cancelled".

    HRP-84 REDO: mid-flight reviewers receive a dedicated copy (they were
    evaluating someone, not being evaluated themselves and not the
    employee's manager) so the inbox copy matches what they were actually
    asked to do.
    """
    who = (
        translate(
            "email.assessment_peer_cancelled.who",
            locale,
            employee_name=escape(employee_name),
        )
        if employee_name
        else ""
    )
    subject = translate(
        "email.assessment_peer_cancelled.subject",
        locale,
        assessment_title=assessment_title,
    )
    button = _button(
        _assessment_url(assessment_id),
        translate("email.assessment_peer_cancelled.button", locale),
    )
    content = (
        _heading(translate("email.assessment_peer_cancelled.heading", locale))
        + _paragraph(
            translate(
                "email.assessment_peer_cancelled.body",
                locale,
                assessment_title=escape(assessment_title),
                who=who,
            )
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


# ---------------------------------------------------------------------------
# PDP notifications
# ---------------------------------------------------------------------------


def render_pdp_sent_email(
    employee_name: str,
    deadline: str | None = None,
    *,
    pdp_title: str | None = None,
    locale: str = "en",
) -> tuple[str, str]:
    """Return (subject, html_body) for PDP assignment."""
    title = (pdp_title or "").strip()
    deadline_line = (
        translate("email.pdp_sent.deadline_line", locale, deadline=deadline)
        if deadline
        else ""
    )
    if title:
        subject = translate("email.pdp_sent.subject", locale, title=title)
        heading_html = translate("email.pdp_sent.heading", locale, title=escape(title))
        intro = translate(
            "email.pdp_sent.intro",
            locale,
            title=escape(title),
            employee_name=escape(employee_name),
            deadline_line=deadline_line,
        )
    else:
        subject = translate("email.pdp_sent.subject_untitled", locale)
        heading_html = translate("email.pdp_sent.heading_untitled", locale)
        intro = translate(
            "email.pdp_sent.intro_untitled",
            locale,
            employee_name=escape(employee_name),
            deadline_line=deadline_line,
        )
    button = _button(
        frontend_url() + "/development", translate("email.pdp_sent.button", locale)
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + _paragraph(translate("email.pdp_sent.body", locale))
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_pdp_returned_email(
    employee_name: str, pdp_title: str | None = None, *, locale: str = "en"
) -> tuple[str, str]:
    """Return (subject, html_body) for PDP return to the plan owner."""
    title = (pdp_title or "").strip()
    if title:
        subject = translate("email.pdp_returned.subject", locale, title=title)
        heading_html = translate(
            "email.pdp_returned.heading", locale, title=escape(title)
        )
        intro = translate(
            "email.pdp_returned.intro",
            locale,
            title=escape(title),
            employee_name=escape(employee_name),
        )
    else:
        subject = translate("email.pdp_returned.subject_untitled", locale)
        heading_html = translate("email.pdp_returned.heading_untitled", locale)
        intro = translate(
            "email.pdp_returned.intro_untitled",
            locale,
            employee_name=escape(employee_name),
        )
    button = _button(
        frontend_url() + "/development", translate("email.pdp_returned.button", locale)
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + _paragraph(translate("email.pdp_returned.body", locale))
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_pdp_review_submitted_email(
    employee_name: str, pdp_title: str | None = None, *, locale: str = "en"
) -> tuple[str, str]:
    """Reviewer notification: the employee has submitted their plan for review."""
    title = (pdp_title or "").strip()
    if title:
        subject = translate("email.pdp_review_submitted.subject", locale, title=title)
        heading_html = translate(
            "email.pdp_review_submitted.heading", locale, title=escape(title)
        )
        intro = translate(
            "email.pdp_review_submitted.intro",
            locale,
            title=escape(title),
            employee_name=escape(employee_name),
        )
    else:
        subject = translate("email.pdp_review_submitted.subject_untitled", locale)
        heading_html = translate("email.pdp_review_submitted.heading_untitled", locale)
        intro = translate(
            "email.pdp_review_submitted.intro_untitled",
            locale,
            employee_name=escape(employee_name),
        )
    button = _button(
        frontend_url() + "/development",
        translate("email.pdp_review_submitted.button", locale),
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + _paragraph(translate("email.pdp_review_submitted.body", locale))
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_pdp_done_to_employee_email(
    employee_name: str | None, pdp_title: str | None = None, *, locale: str = "en"
) -> tuple[str, str]:
    """Employee notification: their development plan has been completed.

    HRP-584: ``employee_name=None`` picks the ``_noname`` copy instead of
    substituting a generic "The employee" placeholder into the greeting.
    """
    title = (pdp_title or "").strip()
    if title:
        subject = translate("email.pdp_done_to_employee.subject", locale, title=title)
        heading_html = translate(
            "email.pdp_done_to_employee.heading", locale, title=escape(title)
        )
        intro = (
            translate(
                "email.pdp_done_to_employee.intro",
                locale,
                title=escape(title),
                employee_name=escape(employee_name),
            )
            if employee_name
            else translate(
                "email.pdp_done_to_employee.intro_noname",
                locale,
                title=escape(title),
            )
        )
    else:
        subject = translate("email.pdp_done_to_employee.subject_untitled", locale)
        heading_html = translate("email.pdp_done_to_employee.heading_untitled", locale)
        intro = (
            translate(
                "email.pdp_done_to_employee.intro_untitled",
                locale,
                employee_name=escape(employee_name),
            )
            if employee_name
            else translate("email.pdp_done_to_employee.intro_untitled_noname", locale)
        )
    button = _button(
        frontend_url() + "/development",
        translate("email.pdp_done_to_employee.button", locale),
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_pdp_done_to_reviewer_email(
    employee_name: str | None, pdp_title: str | None = None, *, locale: str = "en"
) -> tuple[str, str]:
    """Reviewer notification: their employee's plan has been completed.

    HRP-584: ``employee_name=None`` (owner record gone, HRP-244) picks the
    ``_noname`` copy instead of a generic placeholder name.
    """
    title = (pdp_title or "").strip()
    if title:
        subject = translate("email.pdp_done_to_reviewer.subject", locale, title=title)
        heading_html = translate(
            "email.pdp_done_to_reviewer.heading", locale, title=escape(title)
        )
        intro = (
            translate(
                "email.pdp_done_to_reviewer.intro",
                locale,
                title=escape(title),
                employee_name=escape(employee_name),
            )
            if employee_name
            else translate(
                "email.pdp_done_to_reviewer.intro_noname",
                locale,
                title=escape(title),
            )
        )
    else:
        subject = translate("email.pdp_done_to_reviewer.subject_untitled", locale)
        heading_html = translate("email.pdp_done_to_reviewer.heading_untitled", locale)
        intro = (
            translate(
                "email.pdp_done_to_reviewer.intro_untitled",
                locale,
                employee_name=escape(employee_name),
            )
            if employee_name
            else translate("email.pdp_done_to_reviewer.intro_untitled_noname", locale)
        )
    button = _button(
        frontend_url() + "/development",
        translate("email.pdp_done_to_reviewer.button", locale),
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_pdp_cancelled_to_employee_email(
    employee_name: str | None, pdp_title: str | None = None, *, locale: str = "en"
) -> tuple[str, str]:
    """Employee notification: their development plan has been cancelled.

    HRP-584: ``employee_name=None`` picks the ``_noname`` copy instead of
    substituting a generic placeholder name.
    """
    title = (pdp_title or "").strip()
    if title:
        subject = translate(
            "email.pdp_cancelled_to_employee.subject", locale, title=title
        )
        heading_html = translate(
            "email.pdp_cancelled_to_employee.heading", locale, title=escape(title)
        )
        intro = (
            translate(
                "email.pdp_cancelled_to_employee.intro",
                locale,
                title=escape(title),
                employee_name=escape(employee_name),
            )
            if employee_name
            else translate(
                "email.pdp_cancelled_to_employee.intro_noname",
                locale,
                title=escape(title),
            )
        )
    else:
        subject = translate("email.pdp_cancelled_to_employee.subject_untitled", locale)
        heading_html = translate(
            "email.pdp_cancelled_to_employee.heading_untitled", locale
        )
        intro = (
            translate(
                "email.pdp_cancelled_to_employee.intro_untitled",
                locale,
                employee_name=escape(employee_name),
            )
            if employee_name
            else translate(
                "email.pdp_cancelled_to_employee.intro_untitled_noname", locale
            )
        )
    button = _button(
        frontend_url() + "/development",
        translate("email.pdp_cancelled_to_employee.button", locale),
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_pdp_cancelled_to_reviewer_email(
    employee_name: str | None, pdp_title: str | None = None, *, locale: str = "en"
) -> tuple[str, str]:
    """Reviewer notification: their employee's plan has been cancelled.

    HRP-584: ``employee_name=None`` (owner record gone, HRP-244) picks the
    ``_noname`` copy instead of a generic placeholder name.
    """
    title = (pdp_title or "").strip()
    if title:
        subject = translate(
            "email.pdp_cancelled_to_reviewer.subject", locale, title=title
        )
        heading_html = translate(
            "email.pdp_cancelled_to_reviewer.heading", locale, title=escape(title)
        )
        intro = (
            translate(
                "email.pdp_cancelled_to_reviewer.intro",
                locale,
                title=escape(title),
                employee_name=escape(employee_name),
            )
            if employee_name
            else translate(
                "email.pdp_cancelled_to_reviewer.intro_noname",
                locale,
                title=escape(title),
            )
        )
    else:
        subject = translate("email.pdp_cancelled_to_reviewer.subject_untitled", locale)
        heading_html = translate(
            "email.pdp_cancelled_to_reviewer.heading_untitled", locale
        )
        intro = (
            translate(
                "email.pdp_cancelled_to_reviewer.intro_untitled",
                locale,
                employee_name=escape(employee_name),
            )
            if employee_name
            else translate(
                "email.pdp_cancelled_to_reviewer.intro_untitled_noname", locale
            )
        )
    button = _button(
        frontend_url() + "/development",
        translate("email.pdp_cancelled_to_reviewer.button", locale),
    )
    content = (
        _heading(heading_html)
        + _paragraph(intro)
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


# ---------------------------------------------------------------------------
# Exam notifications
# ---------------------------------------------------------------------------


def render_exam_assigned_email(
    exam_title: str, deadline: str | None = None, *, locale: str = "en"
) -> tuple[str, str]:
    """Return (subject, html_body) for exam assignment."""
    subject = translate("email.exam_assigned.subject", locale, exam_title=exam_title)
    deadline_line = (
        translate("email.exam_assigned.deadline_line", locale, deadline=deadline)
        if deadline
        else ""
    )
    button = _button(
        frontend_url() + "/exams", translate("email.exam_assigned.button", locale)
    )
    content = (
        _heading(translate("email.exam_assigned.heading", locale))
        + _paragraph(
            translate(
                "email.exam_assigned.body",
                locale,
                exam_title=escape(exam_title),
                deadline_line=deadline_line,
            )
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


def render_exam_results_email(
    exam_title: str, score: int | float, max_score: int | float, *, locale: str = "en"
) -> tuple[str, str]:
    """Return (subject, html_body) for exam results."""
    subject = translate("email.exam_results.subject", locale, exam_title=exam_title)
    button = _button(
        frontend_url() + "/exams", translate("email.exam_results.button", locale)
    )
    content = (
        _heading(translate("email.exam_results.heading", locale))
        + _paragraph(
            translate("email.exam_results.body", locale, exam_title=escape(exam_title))
        )
        + f'<div style="margin: 0 0 16px 0; padding: 16px; background: {BG_COLOR}; border-radius: 6px; text-align: center;">'
        + f'<span style="font-size: 24px; font-weight: 700; color: {TEXT_COLOR};">{score}</span>'
        + f'<span style="font-size: 16px; color: {MUTED_COLOR};"> / {max_score}</span>'
        + "</div>"
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


# ---------------------------------------------------------------------------
# Certificate expiry
# ---------------------------------------------------------------------------


def render_certificate_expiry_email(
    course_title: str,
    expiry_date: str,
    days_left: int,
    employee_name: str,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Return (subject, html_body) for certificate expiry warning."""
    subject = translate(
        "email.certificate_expiry.subject", locale, course_title=course_title
    )
    button = _button(
        frontend_url() + "/employees",
        translate("email.certificate_expiry.button", locale),
    )
    content = (
        _heading(translate("email.certificate_expiry.heading", locale))
        + _paragraph(
            translate(
                "email.certificate_expiry.intro",
                locale,
                course_title=escape(course_title),
                employee_name=escape(employee_name),
                expiry_date=expiry_date,
                days_left=days_left,
            )
        )
        + _paragraph(translate("email.certificate_expiry.body", locale))
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


# ---------------------------------------------------------------------------
# Deadline reminder
# ---------------------------------------------------------------------------


def render_deadline_reminder_email(
    entity_type: str, entity_title: str, deadline: str, *, locale: str = "en"
) -> tuple[str, str]:
    """Return (subject, html_body) for deadline reminder.

    HRP-584: known entity kinds get a localized label. Keys stay literal
    so the translate-key catalog guard sees them; an unknown kind degrades
    to the raw upper-cased code so the value stays visible.
    """
    subject = translate(
        "email.deadline_reminder.subject", locale, entity_title=entity_title
    )
    kind = entity_type.lower()
    if kind == "assessment":
        type_label = translate("email.deadline_reminder.type_assessment", locale)
    elif kind == "pdp":
        type_label = translate("email.deadline_reminder.type_pdp", locale)
    elif kind == "exam":
        type_label = translate("email.deadline_reminder.type_exam", locale)
    else:
        type_label = entity_type.upper()
    button = _button(
        frontend_url(),
        translate(
            "email.deadline_reminder.button", locale, brand_name=_brand_name_html()
        ),
    )
    content = (
        _heading(translate("email.deadline_reminder.heading", locale))
        + _paragraph(
            translate(
                "email.deadline_reminder.body",
                locale,
                type_label=type_label,
                entity_title=escape(entity_title),
                deadline=deadline,
            )
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


# ---------------------------------------------------------------------------
# External review invitation
# ---------------------------------------------------------------------------


def render_external_review_email(
    token: str,
    assessment_title: str,
    deadline: str | None = None,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Return (subject, html_body) for external reviewer invitation."""
    review_url = public_link(f"/review/{token}", locale)
    subject = translate(
        "email.external_review.subject", locale, assessment_title=assessment_title
    )
    deadline_line = (
        translate("email.external_review.deadline_line", locale, deadline=deadline)
        if deadline
        else ""
    )
    button = _button(review_url, translate("email.external_review.button", locale))
    content = (
        _heading(translate("email.external_review.heading", locale))
        + _paragraph(
            translate(
                "email.external_review.intro",
                locale,
                assessment_title=assessment_title,
                deadline_line=deadline_line,
            )
        )
        + _paragraph(translate("email.external_review.body", locale))
        + f'<div style="margin: 24px 0;">{button}</div>'
    )
    return subject, _render(subject, content, locale=locale)


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
    locale: str = "en",
) -> tuple[str, str]:
    """Return (subject, html_body) for an external evaluator's recruiting invite."""
    invite_url = public_link(f"/recruitment/invite/{token}", locale)
    subject = _sanitize_subject(
        translate(
            "email.recruitment_invite.subject", locale, candidate_name=candidate_name
        )
    )
    vacancy_line = (
        translate(
            "email.recruitment_invite.vacancy_line",
            locale,
            vacancy_title=escape(vacancy_title),
        )
        if vacancy_title
        else ""
    )
    button = _button(invite_url, translate("email.recruitment_invite.button", locale))
    content = (
        _heading(
            translate(
                "email.recruitment_invite.heading",
                locale,
                candidate_name=escape(candidate_name),
            )
        )
        + _paragraph(
            translate(
                "email.recruitment_invite.body",
                locale,
                candidate_name=escape(candidate_name),
                vacancy_line=vacancy_line,
            )
        )
        + f'<div style="margin: 24px 0;">{button}</div>'
        + _muted(
            translate(
                "email.recruitment_invite.note",
                locale,
                expires_in_days=expires_in_days,
            )
        )
    )
    return subject, _render(subject, content, locale=locale)


def render_manager_assessment_invite_email(
    token: str,
    candidate_name: str,
    vacancy_title: str | None = None,
    *,
    evaluator_name: str | None = None,
    personal_message: str | None = None,
    expires_in_days: int = 7,
    locale: str = "en",
) -> tuple[str, str]:
    """Return (subject, html_body) for an HRP-186 external evaluator invite.

    Unlike :func:`render_recruitment_invite_email` (legacy R3 flow), the
    button targets the ``/public/assessments/{token}`` page and the body
    carries the recruiter's optional personal message.
    """
    invite_url = public_link(f"/public/assessments/{token}", locale)
    subject = _sanitize_subject(
        translate(
            "email.manager_assessment_invite.subject",
            locale,
            candidate_name=candidate_name,
        )
    )
    greeting = (
        _paragraph(
            translate(
                "email.manager_assessment_invite.greeting",
                locale,
                evaluator_name=escape(evaluator_name),
            )
        )
        if evaluator_name
        else ""
    )
    vacancy_line = (
        translate(
            "email.manager_assessment_invite.vacancy_line",
            locale,
            vacancy_title=escape(vacancy_title),
        )
        if vacancy_title
        else ""
    )
    message_block = ""
    if personal_message and personal_message.strip():
        message_block = _muted(
            translate("email.manager_assessment_invite.message_label", locale)
        ) + _paragraph(
            translate(
                "email.manager_assessment_invite.message_body",
                locale,
                personal_message=escape(personal_message.strip()),
            )
        )
    button = _button(
        invite_url, translate("email.manager_assessment_invite.button", locale)
    )
    content = (
        _heading(
            translate(
                "email.manager_assessment_invite.heading",
                locale,
                candidate_name=escape(candidate_name),
            )
        )
        + greeting
        + _paragraph(
            translate(
                "email.manager_assessment_invite.body",
                locale,
                candidate_name=escape(candidate_name),
                vacancy_line=vacancy_line,
            )
        )
        + message_block
        + f'<div style="margin: 24px 0;">{button}</div>'
        + _muted(
            translate(
                "email.manager_assessment_invite.note",
                locale,
                expires_in_days=expires_in_days,
            )
        )
    )
    return subject, _render(subject, content, locale=locale)


def render_recruitment_consent_email(
    token: str,
    candidate_name: str,
    template_body: str,
    *,
    expires_in_days: int = 14,
    locale: str = "en",
) -> tuple[str, str]:
    """Return (subject, html_body) for a candidate consent magic-link email."""

    consent_url = public_link(f"/recruitment/consent/{token}", locale)
    subject = _sanitize_subject(translate("email.recruitment_consent.subject", locale))
    summary = (template_body or "").strip()
    if len(summary) > 600:
        summary = summary[:600].rsplit(" ", 1)[0] + "…"
    summary_html = _muted(escape(summary)) if summary else ""
    button = _button(consent_url, translate("email.recruitment_consent.button", locale))
    content = (
        _heading(
            translate(
                "email.recruitment_consent.heading",
                locale,
                candidate_name=escape(candidate_name),
            )
        )
        + _paragraph(translate("email.recruitment_consent.body", locale))
        + summary_html
        + f'<div style="margin: 24px 0;">{button}</div>'
        + _muted(
            translate(
                "email.recruitment_consent.note",
                locale,
                expires_in_days=expires_in_days,
            )
        )
    )
    return subject, _render(subject, content, locale=locale)


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
    cta_label: str | None,
    locale: str = "en",
) -> tuple[str, str]:
    """Shared shell for the HRP-211 Talent Market emails.

    ``cta_label`` is required and localized by the caller (i18n F7 —
    the old "Open card" default was an untranslatable hardcode).
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
    return subject, _render(subject, body, locale=locale)


def render_talent_market_matched_email(
    title: str, card_id: str, *, locale: str = "en"
) -> tuple[str, str]:
    """HRP-211: card published — candidate currently `matched`."""
    safe = escape(title)
    return _render_talent_email(
        subject=translate("email.talent_market_matched.subject", locale, title=title),
        heading=translate("email.talent_market_matched.heading", locale),
        paragraphs=[
            translate("email.talent_market_matched.intro", locale, title=safe),
            translate("email.talent_market_matched.body", locale),
        ],
        card_id=card_id,
        cta_label=translate("email.talent_market_matched.button", locale),
        locale=locale,
    )


def render_talent_market_not_matched_email(
    title: str, card_id: str, *, locale: str = "en"
) -> tuple[str, str]:
    """HRP-211: card published — candidate currently `not_matched`."""
    safe = escape(title)
    return _render_talent_email(
        subject=translate(
            "email.talent_market_not_matched.subject", locale, title=title
        ),
        heading=translate("email.talent_market_not_matched.heading", locale),
        paragraphs=[
            translate("email.talent_market_not_matched.intro", locale, title=safe),
            translate("email.talent_market_not_matched.body", locale),
        ],
        card_id=card_id,
        cta_label=translate("email.talent_market_not_matched.button", locale),
        locale=locale,
    )


def render_talent_market_appointed_self_email(
    title: str, card_id: str, *, locale: str = "en"
) -> tuple[str, str]:
    """HRP-211: employee appointment notification."""
    safe = escape(title)
    return _render_talent_email(
        subject=translate(
            "email.talent_market_appointed_self.subject", locale, title=title
        ),
        heading=translate("email.talent_market_appointed_self.heading", locale),
        paragraphs=[
            translate("email.talent_market_appointed_self.body", locale, title=safe),
        ],
        card_id=card_id,
        cta_label=translate("email.talent_market_appointed_self.button", locale),
        locale=locale,
    )


def render_talent_market_appointed_manager_email(
    title: str, employee_name: str | None, card_id: str, *, locale: str = "en"
) -> tuple[str, str]:
    """HRP-211: manager-side appointment notification."""
    safe_title = escape(title)
    who = (
        translate(
            "email.talent_market_appointed_manager.who",
            locale,
            employee_name=escape(employee_name),
        )
        if employee_name
        else translate("email.talent_market_appointed_manager.who_unknown", locale)
    )
    return _render_talent_email(
        subject=translate(
            "email.talent_market_appointed_manager.subject", locale, title=title
        ),
        heading=translate("email.talent_market_appointed_manager.heading", locale),
        paragraphs=[
            translate(
                "email.talent_market_appointed_manager.body",
                locale,
                who=who,
                title=safe_title,
            ),
        ],
        card_id=card_id,
        cta_label=translate("email.talent_market_appointed_manager.button", locale),
        locale=locale,
    )


def render_talent_market_completed_email(
    title: str, card_id: str, *, locale: str = "en"
) -> tuple[str, str]:
    """HRP-211: card moved to Completed — sent to every matched /
    not_matched candidate."""
    safe = escape(title)
    return _render_talent_email(
        subject=translate("email.talent_market_completed.subject", locale, title=title),
        heading=translate("email.talent_market_completed.heading", locale),
        paragraphs=[
            translate("email.talent_market_completed.body", locale, title=safe),
        ],
        card_id=card_id,
        cta_label=translate("email.talent_market_completed.button", locale),
        locale=locale,
    )


def render_talent_market_cancelled_self_email(
    title: str, card_id: str, *, locale: str = "en"
) -> tuple[str, str]:
    """HRP-211: appointed employee notification when the card is cancelled."""
    safe = escape(title)
    return _render_talent_email(
        subject=translate(
            "email.talent_market_cancelled_self.subject", locale, title=title
        ),
        heading=translate("email.talent_market_cancelled_self.heading", locale),
        paragraphs=[
            translate("email.talent_market_cancelled_self.body", locale, title=safe),
        ],
        card_id=card_id,
        cta_label=translate("email.talent_market_cancelled_self.button", locale),
        locale=locale,
    )


def render_talent_market_cancelled_manager_email(
    title: str, employee_name: str | None, card_id: str, *, locale: str = "en"
) -> tuple[str, str]:
    """HRP-211: manager notification — single appointed employee cancelled
    (used from Draft cancel)."""
    safe_title = escape(title)
    who = (
        translate(
            "email.talent_market_cancelled_manager.who",
            locale,
            employee_name=escape(employee_name),
        )
        if employee_name
        else translate("email.talent_market_cancelled_manager.who_unknown", locale)
    )
    return _render_talent_email(
        subject=translate(
            "email.talent_market_cancelled_manager.subject", locale, title=title
        ),
        heading=translate("email.talent_market_cancelled_manager.heading", locale),
        paragraphs=[
            translate(
                "email.talent_market_cancelled_manager.body",
                locale,
                who=who,
                title=safe_title,
            ),
        ],
        card_id=card_id,
        cta_label=translate("email.talent_market_cancelled_manager.button", locale),
        locale=locale,
    )


def render_talent_market_cancelled_manager_plural_email(
    title: str, employee_names: list[str], card_id: str, *, locale: str = "en"
) -> tuple[str, str]:
    """HRP-211: manager notification — multiple appointed employees were
    cancelled in one transition (Published cancel can hit several)."""
    safe_title = escape(title)
    name_line = (
        ", ".join(f"<strong>{escape(n)}</strong>" for n in employee_names)
        if employee_names
        else translate(
            "email.talent_market_cancelled_manager_plural.names_unknown", locale
        )
    )
    return _render_talent_email(
        subject=translate(
            "email.talent_market_cancelled_manager_plural.subject", locale, title=title
        ),
        heading=translate(
            "email.talent_market_cancelled_manager_plural.heading", locale
        ),
        paragraphs=[
            translate(
                "email.talent_market_cancelled_manager_plural.body",
                locale,
                name_line=name_line,
                title=safe_title,
            ),
        ],
        card_id=card_id,
        cta_label=translate(
            "email.talent_market_cancelled_manager_plural.button", locale
        ),
        locale=locale,
    )


def render_talent_market_cancelled_generic_email(
    title: str, card_id: str, *, locale: str = "en"
) -> tuple[str, str]:
    """HRP-211: matched / not_matched candidates notification when the
    card transitions from Published to Cancelled."""
    safe = escape(title)
    return _render_talent_email(
        subject=translate(
            "email.talent_market_cancelled_generic.subject", locale, title=title
        ),
        heading=translate("email.talent_market_cancelled_generic.heading", locale),
        paragraphs=[
            translate("email.talent_market_cancelled_generic.body", locale, title=safe),
        ],
        card_id=card_id,
        cta_label=translate("email.talent_market_cancelled_generic.button", locale),
        locale=locale,
    )


def render_talent_market_removed_candidate_email(
    title: str, card_id: str, *, locale: str = "en"
) -> tuple[str, str]:
    """HRP-245: notify a candidate when they are removed from the
    Candidates block of a Published card.

    No "Open card" button (HRP-245 redo): a removed employee has no
    access to the Talent Market card any more.
    """
    safe = escape(title)
    return _render_talent_email(
        subject=translate(
            "email.talent_market_removed_candidate.subject", locale, title=title
        ),
        heading=translate("email.talent_market_removed_candidate.heading", locale),
        paragraphs=[
            translate("email.talent_market_removed_candidate.body", locale, title=safe),
        ],
        card_id=card_id,
        cta_label=None,
        locale=locale,
    )


def render_talent_market_reacted_manager_email(
    title: str, employee_name: str | None, card_id: str, *, locale: str = "en"
) -> tuple[str, str]:
    """HRP-213: manager-side notification when an employee reacts to a
    Published card they're a candidate on."""
    safe_title = escape(title)
    who = (
        translate(
            "email.talent_market_reacted_manager.who",
            locale,
            employee_name=escape(employee_name),
        )
        if employee_name
        else translate("email.talent_market_reacted_manager.who_unknown", locale)
    )
    return _render_talent_email(
        subject=translate(
            "email.talent_market_reacted_manager.subject", locale, title=title
        ),
        heading=translate("email.talent_market_reacted_manager.heading", locale),
        paragraphs=[
            translate(
                "email.talent_market_reacted_manager.body",
                locale,
                who=who,
                title=safe_title,
            ),
        ],
        card_id=card_id,
        cta_label=translate("email.talent_market_reacted_manager.button", locale),
        locale=locale,
    )
