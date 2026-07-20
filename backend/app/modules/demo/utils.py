"""Small helpers shared by demo-aware code paths.

The demo sandbox guards live in three different layers (email, uploads,
Slack), each of which needs a cheap ``is this tenant a demo session``
check. Centralising the lookup keeps the policy in one place and avoids
each caller re-implementing the (trivial) SELECT.

Both sync and async variants are exported because:
- Async (``is_demo_tenant``) is what FastAPI handlers and other ORM
  call-sites use — recruitment uploads, demo router, future webhook
  gates.
- Sync (``is_demo_tenant_sync``) is what Celery tasks use — the email
  task already holds a sync ``Session``, and opening a fresh async
  engine there would be wasted plumbing.

The lookup is a single bool column on ``tenants``; the cost is one
indexed PK fetch per call. No caching layer needed.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session


def _coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def is_demo_tenant(
    db: AsyncSession, tenant_id: uuid.UUID | str | None
) -> bool:
    """Async ``Tenant.is_demo`` lookup. Unknown/invalid tenant → False."""
    from app.modules.company.models import Tenant

    tid = _coerce_uuid(tenant_id)
    if tid is None:
        return False
    result = await db.execute(
        select(Tenant.is_demo).where(Tenant.id == tid)
    )
    flag = result.scalar_one_or_none()
    return bool(flag)


def is_demo_tenant_sync(
    db: Session, tenant_id: uuid.UUID | str | None
) -> bool:
    """Sync sibling of :func:`is_demo_tenant` for Celery / blocking paths."""
    from app.modules.company.models import Tenant

    tid = _coerce_uuid(tenant_id)
    if tid is None:
        return False
    flag = db.execute(
        select(Tenant.is_demo).where(Tenant.id == tid)
    ).scalar_one_or_none()
    return bool(flag)
