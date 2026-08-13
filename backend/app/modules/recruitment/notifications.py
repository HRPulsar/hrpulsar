"""Recruitment notifications dispatcher (R4c, §8.5, SCR-03).

The recruitment service publishes high-level events
(``recruitment.vacancy.assigned`` etc.); this module subscribes the
matching handlers at app startup. Each handler resolves the recipient
user(s) from the payload, then writes notification rows + sends
emails via the existing :mod:`app.modules.notification.service`.

Two execution paths:

* **Async path** — service-layer mutations publish via
  :func:`app.core.events.publish`. Handlers open their own
  :func:`app.database.async_session` because the originating request's
  session may already be closed.
* **Sync path** — Celery tasks fire on their own thread / process with
  a sync :class:`sqlalchemy.orm.Session`. They use :func:`notify_sync`,
  which writes the same rows directly (no event-bus round trip).

Recipients honour the per-user
:class:`~app.modules.notification.models.NotificationPreference` rows
(``in_app`` / ``email`` channels). Cross-tenant leakage is impossible
because every payload carries an explicit ``tenant_id`` and queries
filter on it.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.i18n import resolve_locale
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Tenant
from app.modules.notification.models import (
    Notification,
    NotificationPreference,
    NotificationTemplate,
)
from app.modules.notification.service import render_db_template

log = logging.getLogger(__name__)


# Stable mapping: event name → notification template code.
EVENT_TEMPLATE: dict[str, str] = {
    "recruitment.vacancy.assigned": "recruitment.vacancy_assigned",
    "recruitment.candidate.attached": "recruitment.candidate_attached",
    "recruitment.candidate.stage_changed": "recruitment.candidate_stage_changed",
    "recruitment.interview.scheduled": "recruitment.interview_scheduled",
    "recruitment.interview.transcript_ready": "recruitment.interview_transcript_ready",
    "recruitment.interview.analysis_ready": "recruitment.interview_analysis_ready",
    # HRP-494: AI Insights analyses report under their own codes so the
    # subject names the mode the recruiter paid for and the body can
    # deep-link into the AI Insights block of the right vacancy. The
    # legacy ``interview_analysis_ready`` code above stays for the
    # interview-page cache-hit path, which has no candidate context.
    "recruitment.candidate.resume_analysis_ready": (
        "recruitment.resume_analysis_ready"
    ),
    "recruitment.candidate.resume_analysis_failed": (
        "recruitment.resume_analysis_failed"
    ),
    "recruitment.candidate.full_analysis_ready": ("recruitment.full_analysis_ready"),
    "recruitment.candidate.full_analysis_failed": ("recruitment.full_analysis_failed"),
    "recruitment.report.generated": "recruitment.report_generated",
    "recruitment.consent.signed": "recruitment.consent_signed",
    "recruitment.invite.completed": "recruitment.invite_completed",
    "recruitment.ai.task_failed": "recruitment.ai_task_failed",
    "recruitment.question_set.ready": "recruitment.question_set_ready",
    "recruitment.question_set.failed": "recruitment.question_set_failed",
    # HRP-373: a colleague was added as an evaluator on an assessment round.
    "recruitment.assessment.evaluator_invited": (
        "recruitment.assessment_evaluator_invited"
    ),
}

# Roles that receive fan-out notifications for events without an explicit
# user recipient (e.g. consent signed when the requester is gone, AI task
# failures that need admin attention).
_ADMIN_ROLES = ("admin", "recruiter", "hr", "hrd")


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except (TypeError, ValueError):
            return None
    return None


def _add_absolute_link(ctx: dict[str, Any]) -> None:
    """Expose ``link_url`` for templates that render a click-through.

    Event payloads carry ``link`` as a site-relative path — that is what
    the in-app bell needs. Email leaves the app, so the same target has
    to be absolute; the base comes from ``FRONTEND_URL`` (falling back to
    the deployment's canonical host).
    """
    link = ctx.get("link")
    if not link or ctx.get("link_url"):
        return
    if str(link).startswith(("http://", "https://")):
        ctx["link_url"] = link
        return
    from app.core.email_templates import frontend_url

    ctx["link_url"] = f"{frontend_url()}{link}"


def _dedupe(ids: Iterable[uuid.UUID | None]) -> list[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    out: list[uuid.UUID] = []
    for uid in ids:
        if uid is None or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out


# ---------------------------------------------------------------------------
# Async path — service layer
# ---------------------------------------------------------------------------


async def _async_resolve_users_by_ids(
    db: AsyncSession, tenant_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> list[User]:
    if not user_ids:
        return []
    rows = (
        (
            await db.execute(
                select(User).where(
                    User.id.in_(user_ids),
                    User.tenant_id == tenant_id,
                    User.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _async_resolve_admins(db: AsyncSession, tenant_id: uuid.UUID) -> list[User]:
    rows = (
        (
            await db.execute(
                select(User)
                .join(user_roles, user_roles.c.user_id == User.id)
                .join(Role, Role.id == user_roles.c.role_id)
                .where(
                    User.tenant_id == tenant_id,
                    User.is_active.is_(True),
                    Role.code.in_(_ADMIN_ROLES),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _async_user_pref_enabled(
    db: AsyncSession, user_id: uuid.UUID, event_type: str, channel: str
) -> bool:
    pref = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.event_type == event_type,
                NotificationPreference.channel == channel,
            )
        )
    ).scalar_one_or_none()
    if pref is None:
        return True
    return pref.enabled


def _recipient_locales(
    recipients: list[User], tenant_default: str | None
) -> dict[uuid.UUID, str]:
    """Per-recipient interface locale (i18n F4).

    ``User.language > Tenant.default_locale > deployment default`` —
    the *recipient's* chain, never the acting user's request locale.
    """
    return {
        user.id: resolve_locale(
            user_language=user.language, tenant_default=tenant_default
        )
        for user in recipients
    }


def _pick_template(
    by_locale: dict[str, NotificationTemplate], locale: str
) -> NotificationTemplate | None:
    """Recipient's locale row, falling back to the en row."""
    return by_locale.get(locale) or by_locale.get("en")


async def _async_get_templates(
    db: AsyncSession, template_code: str, locales: set[str]
) -> dict[str, NotificationTemplate]:
    """Template rows for a code keyed by locale, en always included.

    One query per dispatch: recipients of the same event may resolve to
    different locales, and each gets the row of its own locale.
    """
    rows = (
        (
            await db.execute(
                select(NotificationTemplate).where(
                    NotificationTemplate.code == template_code,
                    NotificationTemplate.locale.in_(locales | {"en"}),
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.locale: row for row in rows}


async def _async_dispatch(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    template_code: str,
    event_type: str,
    recipients: list[User],
    context: dict[str, Any],
) -> int:
    """Write notification rows + enqueue emails for each recipient.

    Returns the count of recipients that actually got an in-app row
    (per-user preferences may opt some recipients out).
    """
    if not recipients:
        return 0
    tenant = await db.get(Tenant, tenant_id)
    locales = _recipient_locales(recipients, tenant.default_locale if tenant else None)
    by_locale = await _async_get_templates(db, template_code, set(locales.values()))
    if not by_locale:
        log.warning("notification template not found: %s", template_code)
        return 0

    from app.core.email import enqueue_email

    written = 0
    for user in recipients:
        template = _pick_template(by_locale, locales[user.id])
        if template is None:
            log.warning(
                "notification template not found: %s (locale %s)",
                template_code,
                locales[user.id],
            )
            continue
        try:
            ctx = dict(context)
            ctx.setdefault(
                "recipient_name", f"{user.first_name} {user.last_name}".strip()
            )
            # HRP-442/460: payloads carry a relative ``link`` so in-app
            # notifications can route on it; email needs it absolute.
            _add_absolute_link(ctx)
            subject, body = render_db_template(template, ctx)
        except Exception:
            log.exception("notification render failed: %s", template_code)
            continue

        in_app = await _async_user_pref_enabled(db, user.id, event_type, "in_app")
        email = await _async_user_pref_enabled(db, user.id, event_type, "email")

        notif: Notification | None = None
        if in_app:
            notif = Notification(
                tenant_id=tenant_id,
                template_id=template.id,
                recipient_id=user.id,
                context=ctx,
            )
            db.add(notif)
            written += 1

        if email and user.email:
            try:
                enqueue_email(
                    user.email,
                    subject,
                    body,
                    tenant_id=str(tenant_id),
                    template_code=template_code,
                )
                if notif is not None:
                    notif.status = "sent"
                    notif.sent_at = datetime.now(timezone.utc)
            except Exception:
                log.exception("notification email enqueue failed")
        elif notif is not None:
            notif.status = "sent"
            notif.sent_at = datetime.now(timezone.utc)

    await db.commit()
    return written


async def _async_handle(
    event: str, data: dict[str, Any], *, resolve_recipients
) -> None:
    """Top-level helper used by each per-event handler."""
    tenant_id = _coerce_uuid(data.get("tenant_id"))
    if tenant_id is None:
        log.debug("recruitment notification missing tenant_id: %s", event)
        return

    template_code = EVENT_TEMPLATE.get(event)
    if not template_code:
        log.warning("no template mapping for event %s", event)
        return

    event_type = event  # used for per-user channel preferences

    from app.database import async_session

    async with async_session() as db:
        try:
            recipients = await resolve_recipients(db, tenant_id, data)
        except Exception:
            log.exception("recruitment notification recipient lookup failed: %s", event)
            return
        if not recipients:
            return
        await _async_dispatch(
            db,
            tenant_id=tenant_id,
            template_code=template_code,
            event_type=event_type,
            recipients=recipients,
            context=dict(data),
        )


# ---------------------------------------------------------------------------
# Per-event recipient resolvers
# ---------------------------------------------------------------------------


async def _resolve_vacancy_assigned(
    db: AsyncSession, tenant_id: uuid.UUID, data: dict[str, Any]
) -> list[User]:
    new_owner = _coerce_uuid(data.get("new_owner_id"))
    if not new_owner:
        return []
    return await _async_resolve_users_by_ids(db, tenant_id, [new_owner])


async def _resolve_candidate_attached(
    db: AsyncSession, tenant_id: uuid.UUID, data: dict[str, Any]
) -> list[User]:
    ids = _dedupe(
        [
            _coerce_uuid(data.get("owner_id")),
            _coerce_uuid(data.get("actor_id")),
        ]
    )
    return await _async_resolve_users_by_ids(db, tenant_id, ids)


async def _resolve_candidate_stage(
    db: AsyncSession, tenant_id: uuid.UUID, data: dict[str, Any]
) -> list[User]:
    ids = _dedupe(
        [
            _coerce_uuid(data.get("owner_id")),
            _coerce_uuid(data.get("actor_id")),
        ]
    )
    return await _async_resolve_users_by_ids(db, tenant_id, ids)


async def _resolve_interview_user(
    db: AsyncSession, tenant_id: uuid.UUID, data: dict[str, Any]
) -> list[User]:
    ids = _dedupe(
        [
            _coerce_uuid(data.get("interviewer_id")),
            _coerce_uuid(data.get("owner_id")),
        ]
    )
    return await _async_resolve_users_by_ids(db, tenant_id, ids)


async def _resolve_interview_scheduled(
    db: AsyncSession, tenant_id: uuid.UUID, data: dict[str, Any]
) -> list[User]:
    """HRP-419: only the assigned interviewers, only for future interviews.

    Deliberately narrower than :func:`_resolve_interview_user` (still used
    by the transcript / analysis events): the vacancy owner and the person
    who filled in the Schedule modal are not automatically attendees, and
    an interview backfilled after the fact must not page anyone.
    """

    when = data.get("interview_date_iso")
    if isinstance(when, str) and when:
        try:
            moment = datetime.fromisoformat(when)
        except ValueError:
            moment = None
        if moment is not None:
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            if moment < datetime.now(timezone.utc):
                return []

    raw_ids = data.get("interviewer_ids")
    ids = _dedupe(
        [_coerce_uuid(v) for v in raw_ids]
        if isinstance(raw_ids, list)
        else [_coerce_uuid(data.get("interviewer_id"))]
    )
    if not ids:
        return []
    return await _async_resolve_users_by_ids(db, tenant_id, ids)


async def _resolve_report_user(
    db: AsyncSession, tenant_id: uuid.UUID, data: dict[str, Any]
) -> list[User]:
    uid = _coerce_uuid(data.get("generated_by"))
    if not uid:
        return []
    return await _async_resolve_users_by_ids(db, tenant_id, [uid])


async def _resolve_consent_signed(
    db: AsyncSession, tenant_id: uuid.UUID, data: dict[str, Any]
) -> list[User]:
    uid = _coerce_uuid(data.get("requested_by"))
    if uid:
        return await _async_resolve_users_by_ids(db, tenant_id, [uid])
    return await _async_resolve_admins(db, tenant_id)


async def _resolve_invite_completed(
    db: AsyncSession, tenant_id: uuid.UUID, data: dict[str, Any]
) -> list[User]:
    return await _async_resolve_admins(db, tenant_id)


async def _resolve_ai_failed(
    db: AsyncSession, tenant_id: uuid.UUID, data: dict[str, Any]
) -> list[User]:
    return await _async_resolve_admins(db, tenant_id)


async def _resolve_assessment_evaluator(
    db: AsyncSession, tenant_id: uuid.UUID, data: dict[str, Any]
) -> list[User]:
    """HRP-373: the invited evaluator is the only recipient."""
    uid = _coerce_uuid(data.get("evaluator_user_id"))
    if not uid:
        return []
    return await _async_resolve_users_by_ids(db, tenant_id, [uid])


async def _resolve_question_set_user(
    db: AsyncSession, tenant_id: uuid.UUID, data: dict[str, Any]
) -> list[User]:
    """HRP-205: route to whoever requested the generation."""
    uid = _coerce_uuid(data.get("requested_by"))
    if not uid:
        return []
    return await _async_resolve_users_by_ids(db, tenant_id, [uid])


# ---------------------------------------------------------------------------
# Async handlers (registered in main.py lifespan)
# ---------------------------------------------------------------------------


async def on_vacancy_assigned(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.vacancy.assigned",
        data,
        resolve_recipients=_resolve_vacancy_assigned,
    )


async def on_candidate_attached(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.candidate.attached",
        data,
        resolve_recipients=_resolve_candidate_attached,
    )


async def on_candidate_stage_changed(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.candidate.stage_changed",
        data,
        resolve_recipients=_resolve_candidate_stage,
    )


async def on_interview_scheduled(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.interview.scheduled",
        data,
        resolve_recipients=_resolve_interview_scheduled,
    )


async def on_interview_transcript_ready(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.interview.transcript_ready",
        data,
        resolve_recipients=_resolve_interview_user,
    )


async def on_interview_analysis_ready(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.interview.analysis_ready",
        data,
        resolve_recipients=_resolve_interview_user,
    )


async def on_report_generated(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.report.generated", data, resolve_recipients=_resolve_report_user
    )


async def on_consent_signed(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.consent.signed", data, resolve_recipients=_resolve_consent_signed
    )


async def on_invite_completed(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.invite.completed",
        data,
        resolve_recipients=_resolve_invite_completed,
    )


async def on_ai_task_failed(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.ai.task_failed", data, resolve_recipients=_resolve_ai_failed
    )


async def on_question_set_ready(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.question_set.ready",
        data,
        resolve_recipients=_resolve_question_set_user,
    )


async def on_assessment_evaluator_invited(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.assessment.evaluator_invited",
        data,
        resolve_recipients=_resolve_assessment_evaluator,
    )


async def on_question_set_failed(data: dict[str, Any]) -> None:
    await _async_handle(
        "recruitment.question_set.failed",
        data,
        resolve_recipients=_resolve_question_set_user,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


HANDLERS: dict[str, Any] = {
    "recruitment.vacancy.assigned": on_vacancy_assigned,
    "recruitment.candidate.attached": on_candidate_attached,
    "recruitment.candidate.stage_changed": on_candidate_stage_changed,
    "recruitment.interview.scheduled": on_interview_scheduled,
    "recruitment.interview.transcript_ready": on_interview_transcript_ready,
    "recruitment.interview.analysis_ready": on_interview_analysis_ready,
    "recruitment.report.generated": on_report_generated,
    "recruitment.consent.signed": on_consent_signed,
    "recruitment.invite.completed": on_invite_completed,
    "recruitment.ai.task_failed": on_ai_task_failed,
    "recruitment.question_set.ready": on_question_set_ready,
    "recruitment.question_set.failed": on_question_set_failed,
    "recruitment.assessment.evaluator_invited": on_assessment_evaluator_invited,
}


def register() -> None:
    """Subscribe all recruitment handlers to the in-process event bus."""
    from app.core.events import subscribe

    for event, handler in HANDLERS.items():
        subscribe(event, handler)


# ---------------------------------------------------------------------------
# Sync path — used by Celery tasks
# ---------------------------------------------------------------------------


def _sync_resolve_admins(db: Session, tenant_id: uuid.UUID) -> list[User]:
    rows = (
        (
            db.execute(
                select(User)
                .join(user_roles, user_roles.c.user_id == User.id)
                .join(Role, Role.id == user_roles.c.role_id)
                .where(
                    User.tenant_id == tenant_id,
                    User.is_active.is_(True),
                    Role.code.in_(_ADMIN_ROLES),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def _sync_resolve_users(
    db: Session, tenant_id: uuid.UUID, ids: list[uuid.UUID]
) -> list[User]:
    if not ids:
        return []
    rows = (
        (
            db.execute(
                select(User).where(
                    User.id.in_(ids),
                    User.tenant_id == tenant_id,
                    User.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def _sync_user_pref(
    db: Session, user_id: uuid.UUID, event_type: str, channel: str
) -> bool:
    pref = (
        db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.event_type == event_type,
                NotificationPreference.channel == channel,
            )
        )
    ).scalar_one_or_none()
    if pref is None:
        return True
    return pref.enabled


def notify_sync(
    db: Session,
    *,
    event: str,
    tenant_id: uuid.UUID,
    context: dict[str, Any],
    recipient_ids: list[uuid.UUID] | None = None,
    fallback_admins: bool = False,
) -> int:
    """Synchronous notification dispatch used by Celery tasks.

    Resolves ``recipient_ids`` to user rows (filtered by tenant), writes
    in-app notification rows and enqueues emails. Returns the number of
    in-app rows written.

    When ``fallback_admins`` is True and no recipients are supplied, the
    tenant's admin/recruiter/hr/hrd users receive the notification —
    used for AI-task-failed events without a known initiator.
    """
    template_code = EVENT_TEMPLATE.get(event)
    if not template_code:
        log.warning("notify_sync: no template mapping for %s", event)
        return 0

    ids = _dedupe(recipient_ids or [])
    recipients = _sync_resolve_users(db, tenant_id, ids)
    if not recipients and fallback_admins:
        recipients = _sync_resolve_admins(db, tenant_id)

    if not recipients:
        return 0

    # Recipients are resolved before the template lookup: the set of
    # locales in play decides which template rows to fetch (i18n F4).
    tenant = db.get(Tenant, tenant_id)
    locales = _recipient_locales(recipients, tenant.default_locale if tenant else None)
    rows = (
        db.execute(
            select(NotificationTemplate).where(
                NotificationTemplate.code == template_code,
                NotificationTemplate.locale.in_(set(locales.values()) | {"en"}),
            )
        )
        .scalars()
        .all()
    )
    by_locale = {row.locale: row for row in rows}
    if not by_locale:
        log.warning("notify_sync: template missing: %s", template_code)
        return 0

    from app.core.email import enqueue_email

    written = 0
    for user in recipients:
        template = _pick_template(by_locale, locales[user.id])
        if template is None:
            log.warning(
                "notify_sync: template missing: %s (locale %s)",
                template_code,
                locales[user.id],
            )
            continue
        try:
            ctx = dict(context)
            ctx.setdefault(
                "recipient_name", f"{user.first_name} {user.last_name}".strip()
            )
            # HRP-442/460: payloads carry a relative ``link`` so in-app
            # notifications can route on it; email needs it absolute.
            _add_absolute_link(ctx)
            subject, body = render_db_template(template, ctx)
        except Exception:
            log.exception("notify_sync render failed for %s", template_code)
            continue

        in_app = _sync_user_pref(db, user.id, event, "in_app")
        email = _sync_user_pref(db, user.id, event, "email")

        notif: Notification | None = None
        if in_app:
            notif = Notification(
                tenant_id=tenant_id,
                template_id=template.id,
                recipient_id=user.id,
                context=ctx,
            )
            db.add(notif)
            written += 1

        if email and user.email:
            try:
                enqueue_email(
                    user.email,
                    subject,
                    body,
                    tenant_id=str(tenant_id),
                    template_code=template_code,
                )
                if notif is not None:
                    notif.status = "sent"
                    notif.sent_at = datetime.now(timezone.utc)
            except Exception:
                log.exception("notify_sync email enqueue failed")
        elif notif is not None:
            notif.status = "sent"
            notif.sent_at = datetime.now(timezone.utc)

    db.commit()
    return written
