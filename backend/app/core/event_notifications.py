"""GF11 Improve: Event-driven notification dispatcher.

When employee events are created, send notifications to relevant users.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Event types that trigger notifications (mapped to notification template codes)
EVENT_NOTIFICATION_MAP: dict[str, str] = {
    "compensation_change": "compensation_changed",
    "division_change": "division_changed",
    "position_change": "position_changed",
    "assessment_complete": "assessment_completed",
    "pdp_complete": "pdp_completed",
    "exam_complete": "exam_completed",
    "certification_earned": "certification_earned",
    "grade_change": "grade_changed",
    "termination": "employee_terminated",
    "status_inactive": "employee_inactive",
    "status_reactivated": "employee_reactivated",
}


async def on_employee_event(data: dict[str, Any]) -> None:
    """Handle employee event creation and dispatch notifications.

    Expected data keys:
        tenant_id, employee_id, user_id, user_email, event_type, description
    """
    event_type = data.get("event_type", "")
    template_code = EVENT_NOTIFICATION_MAP.get(event_type)
    if not template_code:
        return

    tenant_id = data.get("tenant_id")
    user_id = data.get("user_id")
    user_email = data.get("user_email")
    if not all([tenant_id, user_id, user_email]):
        logger.debug("Missing data for event notification: %s", data)
        return

    # At this point all three are guaranteed non-None by the check above
    assert tenant_id is not None and user_id is not None and user_email is not None

    try:
        from app.database import async_session
        from app.modules.notification.service import send_notification

        async with async_session() as db:
            await send_notification(
                db=db,
                tenant_id=tenant_id,
                template_code=template_code,
                recipient_id=user_id,
                recipient_email=user_email,
                context={
                    "event_type": event_type,
                    "description": data.get("description", ""),
                    "employee_name": data.get("employee_name", ""),
                },
                event_type=event_type,
            )
    except Exception:
        logger.exception("Failed to send event notification for %s", event_type)
