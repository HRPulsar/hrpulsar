"""In-product feedback: validate, then publish a neutral domain event.

Nothing is persisted — feedback is a notification, not a record: the
team reads it in a chat channel and acts on it there. Core therefore
only publishes ``feedback.submitted`` on the in-process bus; the
enterprise Slack handler (``ee/slack_notifications.py``) subscribes and
fans it out. Core stays chat-agnostic, and a community build simply has
no subscriber — the endpoint still accepts the submission (HRP-586).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AppError
from app.core.events import publish
from app.core.redis import redis_client
from app.modules.auth.models import User
from app.modules.company.models import Tenant
from app.modules.feedback.schemas import FeedbackCreate

logger = logging.getLogger(__name__)


async def _enforce_rate_limit(user_id: uuid.UUID) -> None:
    """Per-user hourly cap on submissions.

    The endpoint fans straight out to the operators' chat, and public
    demo sandboxes hand any visitor a valid token — without a cap five
    demo tokens buy unlimited 2000-char pings. Fails open: Redis is
    optional in community builds and feedback is a convenience channel,
    so a flaky throttle store must not refuse the submission itself.
    """
    limit = settings.feedback_rate_limit_per_user_per_hour
    if limit <= 0:
        return
    try:
        async with redis_client() as client:
            key = f"feedback:rl:{user_id}"
            async with client.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                # NX: the window is anchored at the first submission, so
                # refused retries can't hold the user over cap forever.
                pipe.expire(key, 3600, nx=True)
                count, _ = await pipe.execute()
            if count > limit:
                raise AppError(
                    "feedback_rate_limited", status.HTTP_429_TOO_MANY_REQUESTS
                )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.warning(
            "feedback rate-limit unavailable — accepting without a cap",
            exc_info=True,
        )


async def submit_feedback(
    db: AsyncSession, user: User, payload: FeedbackCreate
) -> None:
    """Publish a user's feedback. Empty submissions are rejected."""
    message = (payload.message or "").strip()
    if not payload.rating and not message and not payload.clarity:
        raise AppError("feedback_empty", status.HTTP_400_BAD_REQUEST)
    await _enforce_rate_limit(user.id)

    tenant_name, tenant_is_demo = "", False
    if user.tenant_id:
        row = (
            await db.execute(
                select(Tenant.name, Tenant.is_demo).where(Tenant.id == user.tenant_id)
            )
        ).first()
        if row:
            tenant_name, tenant_is_demo = row[0] or "", bool(row[1])

    await publish(
        "feedback.submitted",
        {
            "source": payload.source,
            "rating": payload.rating,
            "message": message,
            "clarity": payload.clarity,
            "contact_email": payload.contact_email,
            "user_email": user.email,
            "user_name": " ".join(
                p for p in (user.first_name, user.last_name) if p
            ).strip(),
            "tenant_name": tenant_name,
            "tenant_is_demo": tenant_is_demo,
        },
    )
