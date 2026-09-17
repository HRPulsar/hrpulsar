"""Who reads and who edits a Coverage container (HRP-810).

Visibility is a property of the container, not of its owner: an owner who
leaves must not strand the process. A user reads a container when any of
these holds:

* they manage the section (``MANAGE_ROLES``);
* the container is ``company``-wide;
* they own it;
* one of its rules names their role, their current position or them;
* they do or check one of its steps (HRP-809).

Editing belongs to the section's managers and the owner; everyone else who
reads only reads. A container a user may not read answers 404 on every
route - telling a stranger that a finance process exists is itself the
leak.

The router asks through the dependencies at the bottom, one per kind of
path id, so a route added later carries its guard the way the others do -
``test_work_access.py`` fails a route that has none.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends
from sqlalchemy import ColumnElement, exists, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import get_current_employee
from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.work.models import (
    WorkContainer,
    WorkContainerAccessRule,
    WorkDecompositionSession,
    WorkStep,
)

# ponytail: a constant until HRP-820/821 put Coverage on the tenant's
# section access matrix; the /auth/me contract (``sections.coverage``) and
# ``Actor.manage`` stay, only this line's source changes.
MANAGE_ROLES = frozenset({"admin", "hr"})

Access = Literal["manage", "edit", "read"]
SectionLevel = Literal["manage", "view"]
# What the missing thing was, as the caller asked for it: a step or a run of
# a hidden container is as absent as the container itself.
Missing = Literal["container", "step", "session"]


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    manage: bool
    role_codes: tuple[str, ...]
    employee_id: uuid.UUID | None
    position_id: uuid.UUID | None


async def actor_for(db: AsyncSession, user: User) -> Actor:
    codes = tuple(sorted(r.code for r in user.roles))
    emp = await get_current_employee(db, user)
    return Actor(
        user_id=user.id,
        tenant_id=user.tenant_id,
        manage=bool(MANAGE_ROLES.intersection(codes)),
        role_codes=codes,
        employee_id=emp.id if emp else None,
        position_id=emp.position_id if emp else None,
    )


def visible(actor: Actor) -> ColumnElement[bool]:
    """The read condition on ``WorkContainer``. The tenant filter stays the
    caller's: every query already has one."""
    if actor.manage:
        return true()
    rule = WorkContainerAccessRule
    matches: list[ColumnElement[bool]] = [rule.role_code.in_(actor.role_codes)]
    clauses: list[ColumnElement[bool]] = [
        WorkContainer.visibility == "company",
        WorkContainer.owner_id == actor.user_id,
    ]
    if actor.position_id is not None:
        matches.append(rule.position_id == actor.position_id)
    if actor.employee_id is not None:
        matches.append(rule.employee_id == actor.employee_id)
        clauses.append(
            exists().where(
                WorkStep.container_id == WorkContainer.id,
                or_(
                    WorkStep.executor_employee_id == actor.employee_id,
                    WorkStep.accountable_employee_id == actor.employee_id,
                ),
            )
        )
    clauses.append(exists().where(rule.container_id == WorkContainer.id, or_(*matches)))
    return or_(*clauses)


def _not_found(missing: Missing) -> AppError:
    if missing == "step":
        return AppError("work_step_not_found", 404)
    if missing == "session":
        return AppError("work_decomposition_not_found", 404)
    return AppError("work_container_not_found", 404)


def level(actor: Actor, container: WorkContainer) -> Access:
    """What the actor may do with a container they already read."""
    if actor.manage:
        return "manage"
    if container.owner_id == actor.user_id:
        return "edit"
    return "read"


async def ensure(
    db: AsyncSession,
    actor: Actor,
    container_id: uuid.UUID,
    *,
    edit: bool,
    missing: Missing = "container",
) -> WorkContainer:
    # populate_existing, like service.get_container: a bulk UPDATE earlier
    # in the request leaves the identity-map copy partially expired.
    row = (
        await db.execute(
            select(WorkContainer)
            .where(
                WorkContainer.id == container_id,
                WorkContainer.tenant_id == actor.tenant_id,
                visible(actor),
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise _not_found(missing)
    if edit and level(actor, row) == "read":
        raise AppError("work_container_edit_forbidden", 403)
    return row


async def section_level(db: AsyncSession, user: User) -> SectionLevel | None:
    """``/auth/me.sections.coverage``: the managers always, anyone else once
    at least one container is theirs to read."""
    actor = await actor_for(db, user)
    if actor.manage:
        return "manage"
    found = await db.scalar(
        select(WorkContainer.id)
        .where(WorkContainer.tenant_id == actor.tenant_id, visible(actor))
        .limit(1)
    )
    return "view" if found is not None else None


# --- Route dependencies -------------------------------------------------------


async def current_actor(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Actor:
    return await actor_for(db, current_user)


async def manage_actor(actor: Actor = Depends(current_actor)) -> Actor:
    if not actor.manage:
        raise AppError("auth_insufficient_permissions", 403)
    return actor


async def read_container(
    container_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> Actor:
    await ensure(db, actor, container_id, edit=False)
    return actor


async def edit_container(
    container_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> Actor:
    await ensure(db, actor, container_id, edit=True)
    return actor


async def _container_of_step(
    db: AsyncSession, actor: Actor, step_id: uuid.UUID
) -> uuid.UUID:
    container_id = await db.scalar(
        select(WorkStep.container_id).where(
            WorkStep.id == step_id, WorkStep.tenant_id == actor.tenant_id
        )
    )
    if container_id is None:
        raise _not_found("step")
    return container_id


async def read_step(
    step_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> Actor:
    container_id = await _container_of_step(db, actor, step_id)
    await ensure(db, actor, container_id, edit=False, missing="step")
    return actor


async def edit_step(
    step_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> Actor:
    container_id = await _container_of_step(db, actor, step_id)
    await ensure(db, actor, container_id, edit=True, missing="step")
    return actor


async def _container_of_session(
    db: AsyncSession, actor: Actor, session_id: uuid.UUID
) -> uuid.UUID:
    container_id = await db.scalar(
        select(WorkDecompositionSession.container_id).where(
            WorkDecompositionSession.id == session_id,
            WorkDecompositionSession.tenant_id == actor.tenant_id,
        )
    )
    if container_id is None:
        raise _not_found("session")
    return container_id


async def read_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> Actor:
    container_id = await _container_of_session(db, actor, session_id)
    await ensure(db, actor, container_id, edit=False, missing="session")
    return actor


async def edit_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> Actor:
    container_id = await _container_of_session(db, actor, session_id)
    await ensure(db, actor, container_id, edit=True, missing="session")
    return actor
