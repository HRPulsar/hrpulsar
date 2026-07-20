"""Append-only audit log for mutating recruitment operations (FR-28).

R4b.1 wires a global decorator (see ``audit_registry.py``) that records
an audit row after every successful mutating service call. The hook is
best-effort — a write failure is swallowed so the parent operation
still succeeds, but the call commits any uncommitted state in the
session (see :func:`record_event` docstring for the contract).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.recruitment.models import RecruitmentAuditLog

log = logging.getLogger(__name__)


async def record_event(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    payload_diff: dict[str, Any] | None = None,
    request: Request | None = None,
) -> RecruitmentAuditLog | None:
    """Record an audit event. Failure is logged but never re-raised.

    Contract for callers: any pending writes on ``db`` MUST be committed
    BEFORE invoking this function. The call performs ``db.commit()`` to
    persist the audit row, which will also commit anything else still
    pending in the session. The decorator in ``audit_registry`` honours
    this by running ``record_event`` AFTER ``await func(...)`` — by then
    the wrapped service has already committed its mutation.
    """

    ip = None
    user_agent = None
    if request is not None:
        ip = request.client.host if request.client and request.client.host else None
        user_agent = request.headers.get("user-agent")
    try:
        entry = RecruitmentAuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload_diff=payload_diff,
            ip=ip,
            user_agent=user_agent,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry
    except Exception:  # pragma: no cover — defence in depth
        log.exception("audit_log.write_failed", extra={"action": action})
        await db.rollback()
        return None


async def list_events(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    action: str | None = None,
    user_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """Return audit events plus a total count. Newest first."""

    filters = [RecruitmentAuditLog.tenant_id == tenant_id]
    if entity_type:
        filters.append(RecruitmentAuditLog.entity_type == entity_type)
    if entity_id:
        filters.append(RecruitmentAuditLog.entity_id == entity_id)
    if action:
        filters.append(RecruitmentAuditLog.action == action)
    if user_id:
        filters.append(RecruitmentAuditLog.user_id == user_id)
    if since:
        filters.append(RecruitmentAuditLog.created_at >= since)
    if until:
        filters.append(RecruitmentAuditLog.created_at <= until)

    base = select(RecruitmentAuditLog).where(and_(*filters))
    total_result = await db.execute(
        select(func.count()).select_from(RecruitmentAuditLog).where(and_(*filters))
    )
    total = int(total_result.scalar_one() or 0)

    result = await db.execute(
        base.order_by(RecruitmentAuditLog.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    events = list(result.scalars().all())

    user_ids = {e.user_id for e in events if e.user_id is not None}
    users: dict[uuid.UUID, User] = {}
    if user_ids:
        # Tenant-scoped lookup: an audit row may carry a user_id from a user
        # that was later moved to another tenant. Re-checking tenant_id here
        # prevents leaking email/name across tenants in the response.
        u_result = await db.execute(
            select(User).where(
                User.id.in_(user_ids), User.tenant_id == tenant_id
            )
        )
        users = {u.id: u for u in u_result.scalars().all()}

    items = []
    for e in events:
        user = users.get(e.user_id) if e.user_id else None
        items.append(
            {
                "id": e.id,
                "user_id": e.user_id,
                "user_email": user.email if user else None,
                "user_name": (
                    f"{user.first_name} {user.last_name}".strip() if user else None
                ),
                "action": e.action,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "payload_diff": e.payload_diff,
                "ip": e.ip,
                "user_agent": e.user_agent,
                "created_at": e.created_at,
            }
        )
    return items, total
