import asyncio
import contextlib
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from jwt import PyJWTError as JWTError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.core.websocket import manager
from app.database import async_session, get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.notification import service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["notifications"])


class MarkReadRequest(BaseModel):
    notification_ids: list[uuid.UUID] | None = None


class NotificationPrefItem(BaseModel):
    event_type: str
    channel: str = Field(pattern="^(email|in_app)$")
    enabled: bool


class NotificationPrefUpdate(BaseModel):
    preferences: list[NotificationPrefItem]


@router.get("/notifications")
async def list_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_notifications(db, current_user.tenant_id, current_user.id)


@router.get("/notifications/unread-count")
async def unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    count = await service.get_unread_count(db, current_user.tenant_id, current_user.id)
    return {"count": count}


@router.post("/notifications/mark-read")
async def mark_as_read(
    data: MarkReadRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    updated = await service.mark_as_read(
        db, current_user.tenant_id, current_user.id, data.notification_ids
    )
    return {"updated": updated}


# --- GF10: Notification Preferences ---


@router.get("/settings/notifications")
async def get_notification_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_preferences(db, current_user.id)


@router.put("/settings/notifications")
async def update_notification_preferences(
    data: NotificationPrefUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.update_preferences(db, current_user.id, data.preferences)


# --- I3: Email delivery logs ---


@router.get("/settings/email-logs")
async def list_email_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: str | None = Query(None),
    recipient: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """List email delivery logs for the current tenant (admin only)."""
    logs, total = await service.list_email_logs(
        db,
        tenant_id=current_user.tenant_id,
        skip=skip,
        limit=limit,
        status_filter=status,
        recipient_filter=recipient,
    )
    return {"items": logs, "total": total}


# --- CR12: WebSocket channel for real-time notifications + AI-session updates ---


_WS_HEARTBEAT_INTERVAL_SECONDS = 30


async def _resolve_ws_user(db: AsyncSession, token: str) -> User | None:
    """Decode JWT and load the active user. Returns None on any failure."""
    try:
        payload = decode_token(token)
    except JWTError:
        return None
    user_id = payload.get("sub")
    token_type = payload.get("type")
    if not user_id or token_type != "access":
        return None
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


async def _ws_heartbeat(ws: WebSocket) -> None:
    """Send periodic ping frames so dead sockets are detected and closed."""
    try:
        while True:
            await asyncio.sleep(_WS_HEARTBEAT_INTERVAL_SECONDS)
            await ws.send_text(json.dumps({"type": "ping"}))
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - any send failure means a dead socket
        return


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
) -> None:
    """Realtime channel: in-app notifications + AI generation session updates.

    JWT comes via query-param because browsers cannot set custom headers on the
    native WebSocket constructor. Invalid/expired tokens are rejected with
    close code 1008 (policy violation).
    """
    # Use a short-lived session for auth only — holding a pooled connection for
    # the full WS lifetime trips idle_in_transaction_session_timeout and leaves
    # SQLAlchemy trying to roll back on a dead asyncpg socket at teardown.
    async with async_session() as db:
        user = await _resolve_ws_user(db, token)
    if user is None:
        await websocket.close(code=1008)
        return

    tenant_id = str(user.tenant_id)
    user_id = str(user.id)

    await websocket.accept()
    await manager.connect(tenant_id, user_id, websocket)
    heartbeat_task = asyncio.create_task(_ws_heartbeat(websocket))

    try:
        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws endpoint error")
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await heartbeat_task
        await manager.disconnect(tenant_id, user_id, websocket)


# --- I3: Resend webhook for delivery status updates ---


@router.post("/webhooks/email", include_in_schema=False)
async def resend_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Resend webhook events for email delivery tracking.

    Resend sends events: email.sent, email.delivered, email.bounced,
    email.complained, email.delivery_delayed.
    No auth — Resend signs webhooks but we accept all for simplicity.
    """
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - malformed webhook payload rejected
        return {"ok": False}

    event_type = payload.get("type", "")
    data = payload.get("data", {})
    email_id = data.get("email_id") or data.get("id")

    if not email_id:
        return {"ok": False}

    # Map Resend event types to our status
    status_map = {
        "email.delivered": "delivered",
        "email.bounced": "bounced",
        "email.complained": "complained",
        "email.delivery_delayed": "sent",  # still in transit
    }
    new_status = status_map.get(event_type)
    if not new_status:
        return {"ok": True}

    timestamp = None
    if ts := data.get("created_at"):
        try:
            timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            timestamp = datetime.now(timezone.utc)

    await service.update_email_log_status(db, email_id, new_status, timestamp)
    return {"ok": True}
