"""Which positions a division head may edit (HRP-631).

Competences, indicators, materials and answer scales are workspace-wide
with no owning column, so their mutations moved to `admin` / `hr` — there
was nothing to scope them by. `Position` is the exception in that wave: it
carries `division_id`, so a division head keeps the right to shape their
own department's roles and loses it everywhere else.

`admin` / `hr` / `platform_admin` keep the workspace. For everyone else a
position is theirs when it sits in a division they manage. A position with
no division at all is refused: `Position` has no author column, so nobody's
subtree owns it, and the same rule applies on the way in — a manager must
file a new position under one of their own divisions.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from fastapi import Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import (
    ADMIN_ROLE_CODES,
    get_current_employee,
    get_managed_division_ids,
)
from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.position.models import Position


def _refuse() -> None:
    raise AppError(
        "outside_division_scope",
        status.HTTP_403_FORBIDDEN,
        detail_extra={},
        detail_code_key="error_code",
    )


async def resolve_managed_divisions(
    db: AsyncSession, current_user: User
) -> tuple[uuid.UUID, ...] | None:
    """``None`` = no restriction. An empty tuple = manages nothing."""
    if any(r.code in ADMIN_ROLE_CODES for r in current_user.roles):
        return None
    emp = await get_current_employee(db, current_user)
    if emp is None:
        return ()
    return tuple(await get_managed_division_ids(db, current_user.tenant_id, emp.id))


async def managed_divisions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> tuple[uuid.UUID, ...] | None:
    """Shared so a request walks the division tree once."""
    return await resolve_managed_divisions(db, current_user)


def assert_division_in_scope(
    allowed: tuple[uuid.UUID, ...] | None, division_id: uuid.UUID | None
) -> None:
    """403 unless the caller may file a position under this division.

    Takes the resolved subtree rather than resolving its own — the routes
    that call it already carry ``managed_divisions``, and resolving twice
    walks the tenant's whole division tree twice.
    """
    if allowed is None:
        return
    if division_id is not None and division_id in allowed:
        return
    _refuse()


async def assert_positions_in_scope(
    db: AsyncSession,
    current_user: User,
    position_ids: Iterable[uuid.UUID],
    allowed: tuple[uuid.UUID, ...] | None,
) -> None:
    """403 unless every id names a position inside the caller's subtree.

    All or nothing: a bulk approve that silently dropped the ids it was
    not allowed to touch would report success for work it did not do.
    """
    if allowed is None:
        return
    ids = list(position_ids)
    if not ids:
        return
    in_scope = await db.scalar(
        select(func.count(Position.id)).where(
            Position.id.in_(ids),
            Position.tenant_id == current_user.tenant_id,
            Position.division_id.in_(allowed),
        )
    )
    if in_scope != len(set(ids)):
        _refuse()


async def position_scope(
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    allowed: tuple[uuid.UUID, ...] | None = Depends(managed_divisions),
) -> None:
    """403 unless the caller manages the position's division.

    A position that does not exist is refused rather than reported
    missing — the rule HRP-629 applies across this epic.
    """
    await assert_positions_in_scope(db, current_user, [position_id], allowed)
