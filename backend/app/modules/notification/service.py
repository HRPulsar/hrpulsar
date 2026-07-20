import logging
import uuid
from datetime import datetime, timezone

from jinja2 import Template
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import enqueue_email
from app.modules.notification.models import (
    EmailLog,
    Notification,
    NotificationPreference,
    NotificationTemplate,
)

logger = logging.getLogger(__name__)


def _serialize_notification(notif: Notification, template_code: str) -> dict:
    return {
        "id": str(notif.id),
        "template_code": template_code,
        "status": notif.status,
        "context": notif.context,
        "is_read": notif.is_read,
        "created_at": notif.created_at.isoformat() if notif.created_at else None,
    }


# Default event types with all channels enabled
DEFAULT_EVENT_TYPES = [
    "assessment_assigned",
    "assessment_deadline",
    "pdp_sent",
    "pdp_deadline",
    "exam_assigned",
    "invitation_received",
    "general",
]


async def _is_channel_enabled(
    db: AsyncSession, user_id: uuid.UUID, event_type: str, channel: str
) -> bool:
    """Check if a notification channel is enabled for a user. Default: enabled."""
    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.event_type == event_type,
            NotificationPreference.channel == channel,
        )
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        return True  # Default: all enabled
    return pref.enabled


async def send_notification(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    template_code: str,
    recipient_id: uuid.UUID,
    recipient_email: str,
    context: dict,
    event_type: str = "general",
) -> None:
    """Send a notification using a template.

    Checks user preferences before sending. Email is dispatched via
    enqueue_email — Celery task with inline fallback for self-hosted
    builds without a broker.
    """
    result = await db.execute(
        select(NotificationTemplate).where(NotificationTemplate.code == template_code)
    )
    template = result.scalar_one_or_none()
    if not template:
        return

    subject = Template(template.subject_template).render(**context)
    body = Template(template.body_template).render(**context)

    # Check in-app preference
    in_app_enabled = await _is_channel_enabled(db, recipient_id, event_type, "in_app")

    # Record notification (always created when in-app enabled)
    notif = Notification(
        tenant_id=tenant_id,
        template_id=template.id,
        recipient_id=recipient_id,
        context=context,
    )
    if in_app_enabled:
        db.add(notif)

    # Check email preference
    email_enabled = await _is_channel_enabled(db, recipient_id, event_type, "email")

    if email_enabled:
        enqueue_email(
            recipient_email,
            subject,
            body,
            tenant_id=str(tenant_id),
            template_code=template_code,
        )
        if in_app_enabled:
            notif.status = "sent"
            notif.sent_at = datetime.now(timezone.utc)
    elif in_app_enabled:
        # No email to send, but in-app notification is recorded
        notif.status = "sent"
        notif.sent_at = datetime.now(timezone.utc)

    await db.commit()

    # CR12: best-effort live fan-out for in-app notifications
    if in_app_enabled:
        try:
            from app.core.websocket import manager

            await db.refresh(notif)
            await manager.publish_to_user(
                str(tenant_id),
                str(recipient_id),
                {
                    "type": "notification.new",
                    "payload": _serialize_notification(notif, template_code),
                },
            )
        except Exception:
            logger.exception("notification ws broadcast failed")


async def list_notifications(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict]:
    result = await db.execute(
        select(Notification)
        .where(
            Notification.tenant_id == tenant_id, Notification.recipient_id == user_id
        )
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    return [
        {
            "id": n.id,
            "template_id": n.template_id,
            "status": n.status,
            "context": n.context,
            "is_read": n.is_read,
            "sent_at": n.sent_at,
            "created_at": n.created_at,
        }
        for n in result.scalars().all()
    ]


async def get_unread_count(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.tenant_id == tenant_id,
            Notification.recipient_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
    )
    return result.scalar() or 0


async def mark_as_read(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    notification_ids: list[uuid.UUID] | None = None,
) -> int:
    """Mark notifications as read. If notification_ids is None, mark all as read."""
    stmt = (
        update(Notification)
        .where(
            Notification.tenant_id == tenant_id,
            Notification.recipient_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
        .values(is_read=True)
    )
    if notification_ids:
        stmt = stmt.where(Notification.id.in_(notification_ids))

    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# GF10: Notification Preferences
# ---------------------------------------------------------------------------


async def get_preferences(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """Get all notification preferences for a user.

    Returns saved preferences merged with defaults (all enabled).
    """
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    )
    saved = {(p.event_type, p.channel): p for p in result.scalars().all()}

    prefs = []
    for event_type in DEFAULT_EVENT_TYPES:
        for channel in ("email", "in_app"):
            key = (event_type, channel)
            if key in saved:
                p = saved[key]
                prefs.append(
                    {
                        "id": p.id,
                        "event_type": p.event_type,
                        "channel": p.channel,
                        "enabled": p.enabled,
                    }
                )
            else:
                prefs.append(
                    {
                        "id": None,
                        "event_type": event_type,
                        "channel": channel,
                        "enabled": True,
                    }
                )
    return prefs


async def update_preferences(
    db: AsyncSession, user_id: uuid.UUID, items: list
) -> list[dict]:
    """Upsert notification preferences for a user."""
    for item in items:
        result = await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.event_type == item.event_type,
                NotificationPreference.channel == item.channel,
            )
        )
        pref = result.scalar_one_or_none()
        if pref:
            pref.enabled = item.enabled
        else:
            db.add(
                NotificationPreference(
                    user_id=user_id,
                    event_type=item.event_type,
                    channel=item.channel,
                    enabled=item.enabled,
                )
            )
    await db.commit()
    return await get_preferences(db, user_id)


# ---------------------------------------------------------------------------
# I3: Email delivery logs
# ---------------------------------------------------------------------------


async def list_email_logs(
    db: AsyncSession,
    tenant_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 50,
    status_filter: str | None = None,
    recipient_filter: str | None = None,
) -> tuple[list[dict], int]:
    """List email delivery logs. For admin/platform admin use."""
    query = select(EmailLog)
    count_query = select(func.count(EmailLog.id))

    if tenant_id is not None:
        query = query.where(EmailLog.tenant_id == tenant_id)
        count_query = count_query.where(EmailLog.tenant_id == tenant_id)
    if status_filter:
        query = query.where(EmailLog.status == status_filter)
        count_query = count_query.where(EmailLog.status == status_filter)
    if recipient_filter:
        query = query.where(EmailLog.recipient.ilike(f"%{recipient_filter}%"))
        count_query = count_query.where(
            EmailLog.recipient.ilike(f"%{recipient_filter}%")
        )

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(EmailLog.created_at.desc()).offset(skip).limit(limit)
    )
    logs = [
        {
            "id": log.id,
            "tenant_id": log.tenant_id,
            "recipient": log.recipient,
            "subject": log.subject,
            "template_code": log.template_code,
            "status": log.status,
            "message_id": log.message_id,
            "error": log.error,
            "attempts": log.attempts,
            "delivered_at": log.delivered_at,
            "created_at": log.created_at,
        }
        for log in result.scalars().all()
    ]
    return logs, total


async def update_email_log_status(
    db: AsyncSession,
    message_id: str,
    new_status: str,
    timestamp: datetime | None = None,
) -> bool:
    """Update email log status from webhook event. Returns True if found."""
    result = await db.execute(select(EmailLog).where(EmailLog.message_id == message_id))
    log = result.scalar_one_or_none()
    if not log:
        return False

    log.status = new_status
    if new_status == "delivered" and timestamp:
        log.delivered_at = timestamp
    await db.commit()
    return True
