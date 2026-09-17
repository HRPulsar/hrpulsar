"""Work containers and steps (HRP-754).

Every step mutation that changes content flips the step to
``tenant_edited`` here, in the service, so a handler added later cannot
forget the lifecycle (REFACTOR_PLAN §4.3). ``accept_container`` flips
every step of the container to ``accepted`` in one statement and pins the
catalog version the breakdown now stands on.

Reads return plain dicts (a step carries its primitive codes in catalog
order); containers come back as rows.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Integer,
    column,
    delete,
    func,
    or_,
    select,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import billing_hooks
from app.core.errors import AppError, exception_summary
from app.modules.auth.models import User
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from app.modules.primitives.catalog_data import CATALOG_VERSION
from app.modules.primitives.models import Primitive
from app.modules.work.models import (
    ACTIVE_STATUSES,
    QUOTE_MAX,
    WorkContainer,
    WorkContainerAccessLog,
    WorkContainerAccessRule,
    WorkDecompositionSession,
    WorkHireNeed,
    WorkStep,
    WorkStepPrimitive,
    WorkStepSkill,
)
from app.modules.work.schemas import (
    AccessRuleRef,
    ContainerAccessUpdate,
    ContainerCreate,
    ContainerUpdate,
    HireNeedCreate,
    ReclassifyRequest,
    StepCreate,
    StepUpdate,
)

logger = logging.getLogger(__name__)

# Reorder must name every step of the container in one request, so the
# container is capped where StepOrder is.
MAX_STEPS_PER_CONTAINER = 500

# What an "unknown code" error quotes back: enough to recognise the typo,
# not enough to make the message a mirror. A real code is 10 characters.
UNKNOWN_CODES_ECHOED = 5
CODE_ECHO_MAX = 10

ASSIGNEE_FIELDS = frozenset({"executor_employee_id", "accountable_employee_id"})
# Fields a PATCH may change without touching the step's content.
NON_CONTENT_FIELDS = (
    frozenset({"gap_label", "hours_per_run", "runs_per_year"}) | ASSIGNEE_FIELDS
)

STEP_FIELDS = (
    "title",
    "description",
    "responsibility",
    "reversibility",
    "hours_per_run",
    "runs_per_year",
    "output_type",
    "gap_label",
    "notes",
    "executor_employee_id",
    "accountable_employee_id",
)


# --- Containers -------------------------------------------------------------


async def get_container(
    db: AsyncSession, tenant_id: uuid.UUID, container_id: uuid.UUID
) -> WorkContainer:
    # populate_existing: a bulk UPDATE earlier in the same session (accept)
    # leaves the identity-map copy partially expired, and an expired
    # attribute read outside a greenlet is a crash, not a query.
    row = await db.get(WorkContainer, container_id, populate_existing=True)
    if row is None or row.tenant_id != tenant_id:
        raise AppError("work_container_not_found", 404)
    return row


async def list_containers(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    visible_to: ColumnElement[bool],
    type: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[WorkContainer], int]:
    # No default: an unfiltered list is the dangerous value (HRP-810).
    stmt = select(WorkContainer).where(WorkContainer.tenant_id == tenant_id, visible_to)
    if type:
        stmt = stmt.where(WorkContainer.type == type)
    if status:
        stmt = stmt.where(WorkContainer.status == status)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = await db.execute(
        stmt.order_by(WorkContainer.updated_at.desc(), WorkContainer.id)
        .offset(skip)
        .limit(limit)
    )
    return list(rows.scalars().all()), total


async def _writable_container(
    db: AsyncSession, tenant_id: uuid.UUID, container_id: uuid.UUID
) -> WorkContainer:
    """An archived container is read-only: its breakdown is history."""
    row = await get_container(db, tenant_id, container_id)
    if row.status == "archived":
        raise AppError("work_container_archived", 409)
    return row


async def _locked_container(
    db: AsyncSession, tenant_id: uuid.UUID, container_id: uuid.UUID
) -> WorkContainer:
    """``_writable_container`` under a row lock, for the writers whose
    result depends on what the container already holds: appending a step
    reads ``max(position)`` and the step count, reorder and apply renumber
    the whole list. Two of those at once would otherwise put two steps on
    one position - and every later reorder is then refused for good, since
    it must name each position exactly once."""
    row = (
        await db.execute(
            select(WorkContainer)
            .where(
                WorkContainer.id == container_id, WorkContainer.tenant_id == tenant_id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError("work_container_not_found", 404)
    if row.status == "archived":
        raise AppError("work_container_archived", 409)
    return row


def _content_changed(container: WorkContainer) -> None:
    """``active`` means every step is accepted: a content change after
    accept reopens the breakdown, as apply does."""
    if container.status == "active":
        container.status = "draft"


async def _derive_status(db: AsyncSession, container: WorkContainer) -> None:
    """The inverse of ``_content_changed`` for a deletion: with the step
    gone, a breakdown whose every remaining step is accepted is active
    again - otherwise a step added and removed leaves the container ``draft``
    with nothing left to accept."""
    if container.status == "archived":
        return
    total, pending = (
        await db.execute(
            select(
                func.count(WorkStep.id),
                func.count(WorkStep.id).filter(WorkStep.state != "accepted"),
            ).where(WorkStep.container_id == container.id)
        )
    ).one()
    if total and not pending:
        container.status = "active"
    elif not total and container.status == "active":
        # The last step went: ``active`` would claim a breakdown that no
        # longer exists - the same lie ``accept_container`` refuses.
        container.status = "draft"


async def _ensure_owner(
    db: AsyncSession, tenant_id: uuid.UUID, owner_id: uuid.UUID | None
) -> None:
    if owner_id is None:
        return
    owner = await db.get(User, owner_id)
    if owner is None or owner.tenant_id != tenant_id:
        raise AppError("user_not_found", 404)


async def create_container(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: ContainerCreate,
    *,
    user_id: uuid.UUID | None,
) -> WorkContainer:
    # HRP-810: a process always has someone who answers for it.
    payload = data.model_dump()
    payload["owner_id"] = payload["owner_id"] or user_id
    await _ensure_owner(db, tenant_id, payload["owner_id"])
    row = WorkContainer(
        tenant_id=tenant_id,
        created_by_id=user_id,
        catalog_version=CATALOG_VERSION,
        **payload,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_container(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    container_id: uuid.UUID,
    data: ContainerUpdate,
    *,
    user_id: uuid.UUID | None = None,
) -> WorkContainer:
    row = await get_container(db, tenant_id, container_id)
    changes = data.model_dump(exclude_unset=True)
    # Archived is history: only un-archiving passes, never a content edit -
    # and a new owner, since the old one may leave long after the archive
    # (HRP-810).
    if row.status == "archived" and set(changes) - {"status", "owner_id"}:
        raise AppError("work_container_archived", 409)
    if "owner_id" in changes:
        await _ensure_owner(db, tenant_id, changes["owner_id"])
        if changes["owner_id"] != row.owner_id:
            before, after = row.owner_id, changes["owner_id"]
            # Names, not only ids: the history still reads after an account
            # is gone, the way a rule keeps its label.
            names = await _user_names(db, tenant_id, {u for u in (before, after) if u})
            _log_access(
                db,
                row,
                "owner_changed",
                {
                    "from": _str(before),
                    "to": _str(after),
                    "from_name": names.get(before) if before else None,
                    "to_name": names.get(after) if after else None,
                },
                user_id,
            )
    for key, value in changes.items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_container(
    db: AsyncSession, tenant_id: uuid.UUID, container_id: uuid.UUID
) -> None:
    row = await get_container(db, tenant_id, container_id)
    await db.delete(row)
    await db.commit()


async def accept_container(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    container_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    can_manage: bool,
) -> WorkContainer:
    """Accept the whole breakdown: every step → ``accepted``, the container
    → ``active``, ``catalog_version`` re-pinned to the current catalog. The
    container's owner may accept; ``can_manage`` is the admin / hr bypass."""
    row = await _writable_container(db, tenant_id, container_id)
    if not can_manage and row.owner_id != user_id:
        raise AppError("work_container_accept_forbidden", 403)
    # ``active`` means every step is accepted; on an empty breakdown that
    # is a claim about nothing - and the coverage screen then reads an
    # active process with no work in it.
    if not await db.scalar(
        select(func.count(WorkStep.id)).where(WorkStep.container_id == row.id)
    ):
        raise AppError("work_container_accept_empty", 422)
    await db.execute(
        update(WorkStep)
        .where(WorkStep.container_id == row.id, WorkStep.state != "accepted")
        .values(state="accepted")
    )
    row.status = "active"
    row.catalog_version = CATALOG_VERSION
    await db.commit()
    await db.refresh(row)
    return row


# --- Access (HRP-810) ---------------------------------------------------------

ACCESS_HISTORY_LIMIT = 50


def _str(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _log_access(
    db: AsyncSession,
    container: WorkContainer,
    action: str,
    payload: dict[str, Any],
    user_id: uuid.UUID | None,
) -> None:
    db.add(
        WorkContainerAccessLog(
            tenant_id=container.tenant_id,
            container_id=container.id,
            actor_id=user_id,
            action=action,
            payload=payload,
        )
    )


def _rule_key(rule: AccessRuleRef | WorkContainerAccessRule) -> tuple[str, str]:
    if rule.role_code is not None:
        return ("role_code", rule.role_code)
    if rule.position_id is not None:
        return ("position_id", str(rule.position_id))
    return ("employee_id", str(rule.employee_id))


async def _rule_labels(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    rules: Sequence[AccessRuleRef | WorkContainerAccessRule],
) -> dict[tuple[str, str], str]:
    """Titles of the positions and names of the employees the rules name,
    within the tenant - a key missing here is a stranger's id."""
    labels: dict[tuple[str, str], str] = {}
    position_ids = [r.position_id for r in rules if r.position_id is not None]
    employee_ids = [r.employee_id for r in rules if r.employee_id is not None]
    if position_ids:
        rows = await db.execute(
            select(Position.id, Position.title).where(
                Position.id.in_(position_ids), Position.tenant_id == tenant_id
            )
        )
        labels |= {("position_id", str(pid)): title for pid, title in rows.all()}
    if employee_ids:
        rows = await db.execute(
            select(Employee.id, User.first_name, User.last_name, User.email)
            .join(User, User.id == Employee.user_id)
            .where(Employee.id.in_(employee_ids), Employee.tenant_id == tenant_id)
        )
        # A person without a name in their card is still a person, not an
        # id: the chip and the history fall back to the email.
        labels |= {
            ("employee_id", str(eid)): f"{first} {last}".strip() or email
            for eid, first, last, email in rows.all()
        }
    return labels


async def _user_names(
    db: AsyncSession, tenant_id: uuid.UUID, user_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Names within the tenant - an id from anywhere else stays unnamed,
    the way ``_rule_labels`` leaves a stranger's id unlabelled."""
    if not user_ids:
        return {}
    rows = await db.execute(
        select(User.id, User.first_name, User.last_name, User.email).where(
            User.id.in_(list(user_ids)), User.tenant_id == tenant_id
        )
    )
    return {
        uid: f"{first} {last}".strip() or email for uid, first, last, email in rows.all()
    }


async def _user_active(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """Left means what login means: an employee on leave is still with the
    company. An account with no employee card (an admin who never got one)
    counts by the account alone."""
    from app.modules.auth.service import BLOCKED_EMPLOYEE_STATUSES

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return False
    status = await db.scalar(
        select(Employee.status).where(
            Employee.user_id == user_id, Employee.tenant_id == tenant_id
        )
    )
    return status not in BLOCKED_EMPLOYEE_STATUSES


async def _ensure_current_employee(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> None:
    """A rule may name anyone still with the company - on leave included,
    unlike a step assignment, which needs someone at work."""
    from app.modules.auth.service import BLOCKED_EMPLOYEE_STATUSES

    found = await db.scalar(
        select(Employee.id).where(
            Employee.id == employee_id,
            Employee.tenant_id == tenant_id,
            Employee.status.not_in(BLOCKED_EMPLOYEE_STATUSES),
        )
    )
    if found is None:
        raise AppError("work_access_employee_invalid", 422)


async def list_people(
    db: AsyncSession, tenant_id: uuid.UUID, *, reveal_status: bool = True
) -> list[dict[str, Any]]:
    """HRP-810: the people an editor of a process can name - every current
    employee, with what the company directory already shows everyone (name,
    email, position). Not the directory's scope: an owner who heads one
    division still names someone from another. ``assignable`` marks who can
    take a step (HRP-809 needs someone at work); with the terminated already
    out of the list it is the leave status the directory withholds (HRP-623),
    so without ``reveal_status`` everyone reads as assignable and the
    assignment itself refuses a person on leave."""
    from app.modules.auth.service import BLOCKED_EMPLOYEE_STATUSES

    rows = await db.execute(
        select(
            Employee.id,
            Employee.user_id,
            Employee.status,
            Employee.position_title,
            User.first_name,
            User.last_name,
            User.email,
        )
        .join(User, User.id == Employee.user_id)
        .where(
            Employee.tenant_id == tenant_id,
            Employee.status.not_in(BLOCKED_EMPLOYEE_STATUSES),
        )
        .order_by(User.last_name, User.first_name, Employee.id)
    )
    return [
        {
            "employee_id": employee_id,
            "user_id": user_id,
            "name": f"{first} {last}".strip(),
            "email": email,
            "position_title": position_title,
            "assignable": status == "active" if reveal_status else True,
        }
        for employee_id, user_id, status, position_title, first, last, email in rows.all()
    ]


async def get_container_access(
    db: AsyncSession, tenant_id: uuid.UUID, container_id: uuid.UUID
) -> dict[str, Any]:
    container = await get_container(db, tenant_id, container_id)
    rules = (
        (
            await db.execute(
                select(WorkContainerAccessRule)
                .where(WorkContainerAccessRule.container_id == container.id)
                .order_by(
                    WorkContainerAccessRule.created_at, WorkContainerAccessRule.id
                )
            )
        )
        .scalars()
        .all()
    )
    log = (
        (
            await db.execute(
                select(WorkContainerAccessLog)
                .where(WorkContainerAccessLog.container_id == container.id)
                .order_by(
                    WorkContainerAccessLog.created_at.desc(),
                    WorkContainerAccessLog.id,
                )
                .limit(ACCESS_HISTORY_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    labels = await _rule_labels(db, tenant_id, rules)
    people = {e.actor_id for e in log if e.actor_id is not None}
    if container.owner_id is not None:
        people.add(container.owner_id)
    names = await _user_names(db, tenant_id, people)
    owner = None
    if container.owner_id is not None:
        owner = {
            "user_id": container.owner_id,
            "name": names.get(container.owner_id, ""),
            "active": await _user_active(db, tenant_id, container.owner_id),
        }
    return {
        "visibility": container.visibility,
        "owner": owner,
        "rules": [
            {
                "role_code": r.role_code,
                "position_id": r.position_id,
                "employee_id": r.employee_id,
                "label": labels.get(_rule_key(r)),
            }
            for r in rules
        ],
        "history": [
            {
                "action": e.action,
                "actor_name": names.get(e.actor_id) if e.actor_id else None,
                "payload": e.payload,
                "created_at": e.created_at,
            }
            for e in log
        ],
    }


async def set_container_access(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    container_id: uuid.UUID,
    data: ContainerAccessUpdate,
    *,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    """Replace the visibility and the rules, logging every difference. Not
    a content edit: an accepted breakdown stays accepted. The container row
    is locked so two saves cannot both insert the same rule."""
    container = (
        await db.execute(
            select(WorkContainer)
            .where(
                WorkContainer.id == container_id, WorkContainer.tenant_id == tenant_id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if container is None:
        raise AppError("work_container_not_found", 404)

    wanted: dict[tuple[str, str], AccessRuleRef] = {}
    for ref in data.rules:
        targets = (ref.role_code, ref.position_id, ref.employee_id)
        if sum(v is not None for v in targets) != 1:
            raise AppError("work_access_rule_invalid", 422)
        wanted.setdefault(_rule_key(ref), ref)
    current = {
        _rule_key(r): r
        for r in (
            await db.execute(
                select(WorkContainerAccessRule).where(
                    WorkContainerAccessRule.container_id == container.id
                )
            )
        ).scalars()
    }
    added = [ref for key, ref in wanted.items() if key not in current]
    removed = [row for key, row in current.items() if key not in wanted]
    labels = await _rule_labels(db, tenant_id, [*added, *removed])
    for ref in added:
        if ref.employee_id is not None:
            await _ensure_current_employee(db, tenant_id, ref.employee_id)
        elif ref.position_id is not None and _rule_key(ref) not in labels:
            raise AppError("work_access_position_invalid", 422)

    def payload(rule: AccessRuleRef | WorkContainerAccessRule) -> dict[str, Any]:
        kind, target = _rule_key(rule)
        return {kind: target, "label": labels.get((kind, target))}

    if data.visibility != container.visibility:
        _log_access(
            db,
            container,
            "visibility_changed",
            {"from": container.visibility, "to": data.visibility},
            user_id,
        )
        container.visibility = data.visibility
    for row in removed:
        _log_access(db, container, "rule_removed", payload(row), user_id)
        await db.delete(row)
    for ref in added:
        db.add(
            WorkContainerAccessRule(
                tenant_id=tenant_id,
                container_id=container.id,
                role_code=ref.role_code,
                position_id=ref.position_id,
                employee_id=ref.employee_id,
            )
        )
        _log_access(db, container, "rule_added", payload(ref), user_id)
    await db.commit()
    return await get_container_access(db, tenant_id, container_id)


# --- Steps ------------------------------------------------------------------


async def _step_links(
    db: AsyncSession, step_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Capability links per step in catalog order, as ``StepCapability``."""
    out: dict[uuid.UUID, list[dict[str, Any]]] = {sid: [] for sid in step_ids}
    if step_ids:
        rows = await db.execute(
            select(
                WorkStepPrimitive.step_id,
                Primitive.code,
                WorkStepPrimitive.confidence,
                WorkStepPrimitive.quote,
                WorkStepPrimitive.confirmed_at,
            )
            .join(Primitive, Primitive.id == WorkStepPrimitive.primitive_id)
            .where(WorkStepPrimitive.step_id.in_(list(step_ids)))
            .order_by(Primitive.sort_index, Primitive.code)
        )
        for step_id, code, confidence, quote, confirmed_at in rows.all():
            out[step_id].append(
                {
                    "code": code,
                    "confidence": confidence,
                    "quote": quote,
                    "confirmed": confirmed_at is not None,
                }
            )
    return out


async def _step_reads(
    db: AsyncSession, steps: Sequence[WorkStep]
) -> list[dict[str, Any]]:
    links = await _step_links(db, [s.id for s in steps])
    return [
        {
            "id": s.id,
            "container_id": s.container_id,
            "position": s.position,
            **{field: getattr(s, field) for field in STEP_FIELDS},
            "state": s.state,
            "primitive_codes": [c["code"] for c in links[s.id]],
            "capabilities": links[s.id],
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        }
        for s in steps
    ]


async def _step_read(db: AsyncSession, step: WorkStep) -> dict[str, Any]:
    return (await _step_reads(db, [step]))[0]


async def _get_step(
    db: AsyncSession, tenant_id: uuid.UUID, step_id: uuid.UUID
) -> WorkStep:
    row = await db.get(WorkStep, step_id, populate_existing=True)
    if row is None or row.tenant_id != tenant_id:
        raise AppError("work_step_not_found", 404)
    return row


async def _writable_step(
    db: AsyncSession, tenant_id: uuid.UUID, step_id: uuid.UUID
) -> tuple[WorkStep, WorkContainer]:
    row = await _get_step(db, tenant_id, step_id)
    container = await _writable_container(db, tenant_id, row.container_id)
    return row, container


def _ordered_steps(container_id: uuid.UUID):
    return (
        select(WorkStep)
        .where(WorkStep.container_id == container_id)
        .order_by(WorkStep.position, WorkStep.created_at)
    )


async def list_steps(
    db: AsyncSession, tenant_id: uuid.UUID, container_id: uuid.UUID
) -> list[dict[str, Any]]:
    await get_container(db, tenant_id, container_id)
    rows = await db.execute(_ordered_steps(container_id))
    return await _step_reads(db, rows.scalars().all())


async def _active_by_code(db: AsyncSession, codes: Sequence[str]) -> list[Primitive]:
    wanted = list(dict.fromkeys(codes))
    if not wanted:
        return []
    rows = await db.execute(
        select(Primitive).where(
            Primitive.code.in_(wanted), Primitive.retired_in.is_(None)
        )
    )
    found = {p.code: p for p in rows.scalars().all()}
    unknown = [code for code in wanted if code not in found]
    if unknown:
        # The codes come straight from the request: echoed back whole, the
        # 404 is a mirror for whatever the caller sent.
        raise AppError(
            "primitive_not_found",
            404,
            codes=", ".join(c[:CODE_ECHO_MAX] for c in unknown[:UNKNOWN_CODES_ECHOED]),
        )
    return [found[code] for code in wanted]


def _evidence_of(step: Mapping[str, Any]) -> dict[str, tuple[float | None, str | None]]:
    """code -> (confidence, quote) from a payload step (HRP-776); the first
    entry per code wins, as in the worker's ``_normalise``."""
    out: dict[str, tuple[float | None, str | None]] = {}
    for e in step.get("evidence") or []:
        # Cut like the worker cuts: a reclassification comes straight from
        # the model, without ``tasks._normalise`` in between.
        quote = (e.get("quote") or "")[:QUOTE_MAX] or None
        out.setdefault(e["code"], (e.get("confidence"), quote))
    return out


async def _replace_links(
    db: AsyncSession,
    step: WorkStep,
    primitives: Sequence[Primitive],
    *,
    source: str,
    evidence: Mapping[str, tuple[float | None, str | None]] | None = None,
) -> bool:
    """Make the step's links equal to ``primitives``. A code that was
    already linked keeps its ``source`` - that is the provenance the
    column exists for; only the codes added now carry ``source``. A code
    in ``evidence`` (a fresh proposal of the model) takes the new
    confidence and quote and loses its confirmation: it is a new claim."""
    evidence = evidence or {}
    wanted = {p.id: p for p in primitives}
    existing = {
        row.primitive_id: row
        for row in (
            await db.execute(
                select(WorkStepPrimitive).where(WorkStepPrimitive.step_id == step.id)
            )
        )
        .scalars()
        .all()
    }
    if existing.keys() - wanted.keys():
        await db.execute(
            delete(WorkStepPrimitive).where(
                WorkStepPrimitive.step_id == step.id,
                WorkStepPrimitive.primitive_id.in_(existing.keys() - wanted.keys()),
            )
        )
    for pid, primitive in wanted.items():
        confidence, quote = evidence.get(primitive.code, (None, None))
        row = existing.get(pid)
        if row is None:
            db.add(
                WorkStepPrimitive(
                    tenant_id=step.tenant_id,
                    step_id=step.id,
                    primitive_id=pid,
                    source=source,
                    confidence=confidence,
                    quote=quote,
                )
            )
        elif primitive.code in evidence:
            row.confidence, row.quote, row.confirmed_at = confidence, quote, None
    return existing.keys() != wanted.keys()


async def create_step(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    container_id: uuid.UUID,
    data: StepCreate,
) -> dict[str, Any]:
    """Append a step the tenant typed in — it is ``tenant_edited`` from the
    start, as are its primitive links."""
    container = await _locked_container(db, tenant_id, container_id)
    primitives = await _active_by_code(db, data.primitive_codes)
    last, count = (
        await db.execute(
            select(func.max(WorkStep.position), func.count()).where(
                WorkStep.container_id == container_id
            )
        )
    ).one()
    if count >= MAX_STEPS_PER_CONTAINER:
        raise AppError("work_step_limit_reached", 409, limit=MAX_STEPS_PER_CONTAINER)
    _content_changed(container)
    step = WorkStep(
        tenant_id=tenant_id,
        container_id=container_id,
        position=(last or 0) + 1,
        state="tenant_edited",
        **data.model_dump(exclude={"primitive_codes"}),
    )
    db.add(step)
    await db.flush()
    await _replace_links(db, step, primitives, source="tenant_edited")
    await db.commit()
    await db.refresh(step)
    return await _step_read(db, step)


async def _ensure_active_employee(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> None:
    # One answer for a stranger, a missing id and a terminated employee:
    # the error must not tell another tenant's ids apart.
    found = await db.scalar(
        select(Employee.id).where(
            Employee.id == employee_id,
            Employee.tenant_id == tenant_id,
            Employee.status == "active",
        )
    )
    if found is None:
        raise AppError("work_step_employee_invalid", 422)


async def update_step(
    db: AsyncSession, tenant_id: uuid.UUID, step_id: uuid.UUID, data: StepUpdate
) -> dict[str, Any]:
    step, container = await _writable_step(db, tenant_id, step_id)
    changes = {
        key: value
        for key, value in data.model_dump(exclude_unset=True).items()
        if getattr(step, key) != value
    }
    for key in ASSIGNEE_FIELDS & changes.keys():
        if changes[key] is not None:
            await _ensure_active_employee(db, tenant_id, changes[key])
    if changes:
        for key, value in changes.items():
            setattr(step, key, value)
        # The gap label is routing, the hours are arithmetic and the
        # assignees are people, not content: none reopens an accepted
        # breakdown.
        if set(changes) - NON_CONTENT_FIELDS:
            step.state = "tenant_edited"
            _content_changed(container)
        await db.commit()
        await db.refresh(step)
    return await _step_read(db, step)


async def _prune_hire_needs(
    db: AsyncSession, tenant_id: uuid.UUID, container_id: uuid.UUID
) -> None:
    """After steps of the container were deleted: drop the ids the hire
    needs still point at, and the need itself once nothing is left - a need
    naming deleted steps offers the same handoff again on every coverage
    read. The draft vacancy stays: it is Recruitment's record and may
    already carry candidates."""
    alive = {
        str(sid)
        for sid in (
            await db.execute(
                select(WorkStep.id).where(WorkStep.container_id == container_id)
            )
        )
        .scalars()
        .all()
    }
    needs = (
        (
            await db.execute(
                select(WorkHireNeed).where(
                    WorkHireNeed.tenant_id == tenant_id,
                    WorkHireNeed.container_id == container_id,
                )
            )
        )
        .scalars()
        .all()
    )
    for need in needs:
        kept = [sid for sid in need.step_ids if sid in alive]
        if not kept:
            await db.delete(need)
        elif len(kept) != len(need.step_ids):
            need.step_ids = kept


async def delete_step(
    db: AsyncSession, tenant_id: uuid.UUID, step_id: uuid.UUID
) -> None:
    """Reject is delete: a rejected step is indistinguishable from one that
    never existed (§4.3)."""
    step, container = await _writable_step(db, tenant_id, step_id)
    await db.delete(step)
    await db.flush()
    await _prune_hire_needs(db, tenant_id, container.id)
    await _derive_status(db, container)
    await db.commit()


async def set_step_primitives(
    db: AsyncSession, tenant_id: uuid.UUID, step_id: uuid.UUID, codes: Sequence[str]
) -> dict[str, Any]:
    """The capability picker saved: the resulting set is what the company
    says the step needs, so every code in it counts as confirmed (HRP-776)
    - the ones it kept as much as the ones it added."""
    step, container = await _writable_step(db, tenant_id, step_id)
    primitives = await _active_by_code(db, codes)
    if await _replace_links(db, step, primitives, source="tenant_edited"):
        step.state = "tenant_edited"
        _content_changed(container)
    await db.execute(
        update(WorkStepPrimitive)
        .where(
            WorkStepPrimitive.step_id == step.id,
            WorkStepPrimitive.confirmed_at.is_(None),
        )
        .values(confirmed_at=datetime.now(UTC))
    )
    await db.commit()
    await db.refresh(step)
    return await _step_read(db, step)


async def remove_step_primitive(
    db: AsyncSession, tenant_id: uuid.UUID, step_id: uuid.UUID, code: str
) -> dict[str, Any]:
    """A chip's remove button (HRP-776): drop one code and nothing else -
    unlike the picker, it vouches for no other code on the step. A content
    change, so the step reopens."""
    step, container = await _writable_step(db, tenant_id, step_id)
    row = (
        await db.execute(
            select(WorkStepPrimitive)
            .join(Primitive, Primitive.id == WorkStepPrimitive.primitive_id)
            .where(WorkStepPrimitive.step_id == step.id, Primitive.code == code)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError("work_step_capability_not_found", 404, capability=code)
    await db.delete(row)
    step.state = "tenant_edited"
    _content_changed(container)
    await db.commit()
    await db.refresh(step)
    return await _step_read(db, step)


async def confirm_step_primitive(
    db: AsyncSession, tenant_id: uuid.UUID, step_id: uuid.UUID, code: str
) -> dict[str, Any]:
    """A chip click: the company vouches for a code the model was unsure
    of (HRP-776). Not a content change - the step's state stays."""
    step, _container = await _writable_step(db, tenant_id, step_id)
    row = (
        await db.execute(
            select(WorkStepPrimitive)
            .join(Primitive, Primitive.id == WorkStepPrimitive.primitive_id)
            .where(WorkStepPrimitive.step_id == step.id, Primitive.code == code)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError("work_step_capability_not_found", 404, capability=code)
    if row.confirmed_at is None:
        row.confirmed_at = datetime.now(UTC)
        await db.commit()
    return await _step_read(db, step)


async def reorder_steps(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    container_id: uuid.UUID,
    step_ids: Sequence[uuid.UUID],
) -> list[dict[str, Any]]:
    """Renumber the container's steps in the given order with one
    ``UPDATE ... FROM (VALUES ...)``. The list must name every step of the
    container exactly once. Order is not content: states stay as they are."""
    await _locked_container(db, tenant_id, container_id)
    existing = set(
        (
            await db.execute(
                select(WorkStep.id).where(WorkStep.container_id == container_id)
            )
        )
        .scalars()
        .all()
    )
    if len(set(step_ids)) != len(step_ids) or set(step_ids) != existing:
        raise AppError("work_step_order_mismatch", 422)
    new_order = values(
        column("id", UUID(as_uuid=True)), column("position", Integer), name="new_order"
    ).data([(sid, index) for index, sid in enumerate(step_ids, start=1)])
    await db.execute(
        update(WorkStep)
        .where(WorkStep.id == new_order.c.id, WorkStep.container_id == container_id)
        .values(position=new_order.c.position)
    )
    await db.commit()
    rows = await db.execute(_ordered_steps(container_id))
    return await _step_reads(db, rows.scalars().all())


async def reclassify_step(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    step_id: uuid.UUID,
    data: ReclassifyRequest,
) -> dict[str, Any]:
    """Reclassify one step by the company's comment (HRP-775, decision
    2026-09-09, clarification of decision 4): one synchronous call of the second
    pass over the whole breakdown, narrowed to this step with the comment
    in context. The answer replaces the step's codes, responsibility and
    output type; the other steps are context only. A failure raises, so
    the billing wrapper charges only a delivered classification."""
    from app.modules.ai import providers as ai_providers
    from app.modules.ai_settings import service as ai_settings_service
    from app.modules.work import tasks

    step, container = await _writable_step(db, tenant_id, step_id)
    siblings = (await db.execute(_ordered_steps(container.id))).scalars().all()
    index = next(i for i, s in enumerate(siblings) if s.id == step.id)
    snapshot = {
        "type": container.type,
        "title": container.title,
        "description": container.description,
        "goal": container.goal,
    }
    listing = [{"title": s.title, "description": s.description} for s in siblings]
    primitives = (
        (
            await db.execute(
                select(Primitive)
                .where(Primitive.retired_in.is_(None))
                .order_by(Primitive.sort_index, Primitive.code)
            )
        )
        .scalars()
        .all()
    )
    tenant_settings = await ai_settings_service.get_or_default(db, tenant_id)
    model = await ai_settings_service.get_effective_model_async(db, tenant_settings)
    credentials = await ai_providers.resolve_generation_target(db, tenant_id, model)
    # Release the connection for the duration of the call.
    await db.commit()
    try:
        [result] = await tasks.classify_steps(
            snapshot,
            listing,
            primitives=primitives,
            tenant_settings=tenant_settings,
            credentials=credentials,
            model=model,
            # One retry: a malformed answer is exactly what a second call
            # fixes, and the user is waiting on the request.
            max_attempts=2,
            only=index,
            comment=data.comment,
        )
    except RuntimeError as exc:
        # The provider's message can quote the prompt, the endpoint or a
        # response body from whatever the endpoint really points at: it
        # goes to the log, the caller gets our own code.
        logger.warning(
            "work reclassify failed for step %s: %s",
            step_id,
            exception_summary(exc.__cause__ or exc),
        )
        raise AppError(
            "work_step_reclassify_failed", 502, error=str(exc) or "service_error"
        ) from exc

    step, container = await _writable_step(db, tenant_id, step_id)
    by_code = {p.code: p for p in primitives}
    wanted = [by_code[c] for c in dict.fromkeys(result["primitives"]) if c in by_code]
    evidence = _evidence_of(result)
    await _replace_links(
        db,
        step,
        wanted,
        source="system_suggested",
        # Every kept code is a fresh claim, with or without evidence.
        evidence={p.code: evidence.get(p.code, (None, None)) for p in wanted},
    )
    step.responsibility = result["responsibility"]
    step.output_type = result["output_type"]
    step.state = "tenant_edited"
    _content_changed(container)
    await db.commit()
    await db.refresh(step)
    return await _step_read(db, step)


# --- AI decomposition sessions (HRP-755) --------------------------------------
# Split billing (§4.2): the handler prechecks ``work_decomposition.start``
# before the row exists, the worker consumes in the same commit as
# ``status='ready'``. A failed run is free; a cancelled one is not billed.

BILLING_ACTION_START = "work_decomposition.start"
# What a decomposition's credit hold is filed against (HRP-547), mirroring
# the SKILL.md path: the one-active-run index is per container, so without
# a hold five containers on a 130-credit balance all pass the same precheck
# and five workers then charge 120 each.
DECOMPOSITION_RESERVE_ENTITY = "work_decomposition"


async def release_session_hold(
    db: AsyncSession, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> None:
    """Drop the hold the handler took for this run. Idempotent, so every
    path that ends a run may call it without knowing which got there
    first; the expiry sweep is the backstop for a worker that never ran."""
    await billing_hooks.release_action(
        db,
        tenant_id,
        entity_type=DECOMPOSITION_RESERVE_ENTITY,
        entity_id=session_id,
        action=BILLING_ACTION_START,
    )


async def get_session(
    db: AsyncSession, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> WorkDecompositionSession:
    row = await db.get(WorkDecompositionSession, session_id)
    if row is None or row.tenant_id != tenant_id:
        raise AppError("work_decomposition_not_found", 404)
    return row


async def latest_session(
    db: AsyncSession, tenant_id: uuid.UUID, container_id: uuid.UUID
) -> WorkDecompositionSession | None:
    """The container's newest run, whatever its state — what the editor
    shows after a reload: a banner while it runs, an apply button when it
    is ready, the error when it failed."""
    await get_container(db, tenant_id, container_id)
    rows = await db.execute(
        select(WorkDecompositionSession)
        .where(WorkDecompositionSession.container_id == container_id)
        .order_by(
            WorkDecompositionSession.created_at.desc(), WorkDecompositionSession.id
        )
        .limit(1)
    )
    return rows.scalars().first()


async def create_session(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    container_id: uuid.UUID,
    *,
    cost: float | None = None,
) -> WorkDecompositionSession:
    """Persist a ``pending`` run over a snapshot of the container's text, so
    an edit made while the model works does not change what was generated
    against. One active run per container (partial unique index)."""
    from app.modules.work.prompts import PROMPT_VERSION

    container = await _writable_container(db, tenant_id, container_id)
    if not (container.description or "").strip():
        raise AppError("work_decomposition_no_description", 422)
    params: dict[str, Any] = {"billing_action": BILLING_ACTION_START}
    if cost is not None:
        params["cost"] = cost
    row = WorkDecompositionSession(
        tenant_id=tenant_id,
        user_id=user_id,
        container_id=container.id,
        params=params,
        base_snapshot={
            "container": {
                "type": container.type,
                "title": container.title,
                "description": container.description,
                "goal": container.goal,
            }
        },
        status="pending",
        prompt_version=PROMPT_VERSION,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # A drafted run nobody applied or discarded holds the slot too, and
        # "in progress" would be a lie about it.
        blocker = (
            await db.execute(
                select(WorkDecompositionSession.status).where(
                    WorkDecompositionSession.container_id == container_id,
                    WorkDecompositionSession.status.in_(ACTIVE_STATUSES),
                )
            )
        ).scalar_one_or_none()
        if blocker is None:
            raise  # not the one-active-run index: let it surface as it is
        if blocker == "ready":
            raise AppError("work_decomposition_pending_apply", 409) from exc
        raise AppError("work_decomposition_already_running", 409) from exc
    await db.refresh(row)
    return row


async def cancel_session(
    db: AsyncSession, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> WorkDecompositionSession:
    """Drop a run before apply. The worker checks the status before the LLM
    call and again before billing, so a cancelled run is never charged."""
    row = await get_session(db, tenant_id, session_id)
    if row.status in ("applied", "cancelled"):
        return row
    row.status = "cancelled"
    row.phase = None
    row.finished_at = datetime.now(UTC)
    task_id = row.celery_task_id
    await release_session_hold(db, row.tenant_id, row.id)
    await db.commit()
    await db.refresh(row)
    if task_id:
        try:
            from app.core.celery_app import celery

            # A broker round-trip: off the event loop, or every cancel
            # blocks the whole worker process for its duration.
            await asyncio.to_thread(celery.control.revoke, task_id, terminate=False)
        except Exception:
            logger.exception("work decomposition revoke failed for task %s", task_id)
    return row


async def _discardable_work(db: AsyncSession, container_id: uuid.UUID) -> bool:
    """Whether replacing the container's steps would throw away something
    nobody can regenerate for free: a ``SKILL.md`` the tenant paid for, or
    a step it wrote or corrected itself. Assignments and hours ride on
    those steps, so one flag covers the lot."""
    found = await db.execute(
        select(WorkStep.id)
        .outerjoin(WorkStepSkill, WorkStepSkill.step_id == WorkStep.id)
        .where(
            WorkStep.container_id == container_id,
            or_(WorkStep.state == "tenant_edited", WorkStepSkill.status == "ready"),
        )
        .limit(1)
    )
    return found.first() is not None


async def fail_session(db: AsyncSession, session_id: uuid.UUID, message: str) -> None:
    """The row could not be followed by a run - the credit hold was
    refused, the queue is down: it goes to ``error`` at once rather than
    holding the container's one-active-run slot until the reaper."""
    await db.execute(
        update(WorkDecompositionSession)
        .where(WorkDecompositionSession.id == session_id)
        .values(
            status="error",
            phase=None,
            error_code="service_error",
            error_message=message,
            finished_at=datetime.now(UTC),
        )
    )
    await db.commit()


async def apply_session(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    idempotency_key: str,
    force: bool = False,
) -> dict[str, Any]:
    """Materialise the draft as the container's steps, ``system_suggested``
    with ``system_suggested`` links, replacing whatever steps the container
    had; the container goes back to ``draft`` for a new accept. A code
    retired between ``ready`` and apply is dropped like the worker drops an
    unknown one - the tenant paid for this answer. Idempotent on
    ``idempotency_key``: a repeat with the same key returns the stored
    result and creates nothing.

    Replacing is destructive, so a container holding paid or hand-made
    work is refused until the caller says ``force``; the hire needs of the
    steps that go are pruned with them."""
    # Row lock: two applies at once (double click, retry on timeout) would
    # both read ``ready`` and materialise the steps twice.
    # The tenant belongs in the statement, not in a check on the row it
    # returned: otherwise a stranger's session is locked first and only
    # then refused.
    sess = (
        await db.execute(
            select(WorkDecompositionSession)
            .where(
                WorkDecompositionSession.id == session_id,
                WorkDecompositionSession.tenant_id == tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if sess is None:
        raise AppError("work_decomposition_not_found", 404)
    if sess.status == "applied":
        if sess.applied_idempotency_key == idempotency_key and sess.applied_result:
            return sess.applied_result
        raise AppError("work_decomposition_already_applied_different_key", 409)
    if sess.status != "ready":
        raise AppError("work_decomposition_not_ready", 409, state=sess.status)

    container = await _locked_container(db, tenant_id, sess.container_id)
    if not force and await _discardable_work(db, container.id):
        raise AppError("work_apply_would_discard", 409)
    steps = (sess.payload or {}).get("steps") or []
    active = await db.execute(select(Primitive).where(Primitive.retired_in.is_(None)))
    primitives = {p.code: p for p in active.scalars().all()}
    await db.execute(delete(WorkStep).where(WorkStep.container_id == container.id))
    created: list[uuid.UUID] = []
    for position, step in enumerate(steps, start=1):
        row = WorkStep(
            tenant_id=tenant_id,
            container_id=container.id,
            position=position,
            state="system_suggested",
            **{field: step.get(field) for field in STEP_FIELDS if field in step},
        )
        db.add(row)
        await db.flush()
        evidence = _evidence_of(step)
        db.add_all(
            WorkStepPrimitive(
                tenant_id=tenant_id,
                step_id=row.id,
                primitive_id=primitives[code].id,
                source="system_suggested",
                confidence=evidence.get(code, (None, None))[0],
                quote=evidence.get(code, (None, None))[1],
            )
            for code in dict.fromkeys(step.get("primitives") or [])
            if code in primitives
        )
        created.append(row.id)
    await _prune_hire_needs(db, tenant_id, container.id)
    container.source = "ai"
    container.status = "draft"
    container.catalog_version = CATALOG_VERSION
    sess.status = "applied"
    sess.applied_idempotency_key = idempotency_key
    sess.applied_result = {
        "created_steps": [str(s) for s in created],
        "idempotency_key": idempotency_key,
    }
    await db.commit()
    return sess.applied_result


# --- Hire needs (HRP-759) ----------------------------------------------------

# Competences pre-filled on the draft vacancy: the ones whose capability
# sets overlap the gap most (§6, step 3).
HIRE_NEED_COMPETENCES = 5
VACANCY_TITLE_MAX = 255
# The draft vacancy's description is prose for a person and, later, a
# prompt for Recruitment's model. A container holds up to 500 steps of up
# to 20 000 characters each, so the concatenation is capped here rather
# than on ``VacancyCreate`` - Recruitment's own callers are not the ones
# that can hand it megabytes.
HIRE_NEED_MAX_STEPS = 50
HIRE_NEED_MAX_DESCRIPTION = 20_000
# Language-neutral, like the rest of the text: the draft lands in the
# tenant's language and we add no prose of our own.
HIRE_NEED_TRUNCATED = "[...]"


async def create_hire_need(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    container_id: uuid.UUID,
    data: HireNeedCreate,
    *,
    user_id: uuid.UUID,
) -> WorkHireNeed:
    """Hand the gaps among ``data.step_ids`` to Recruitment as one draft
    vacancy (§6). Delegates to ``recruitment.vacancy_service.create_vacancy``
    - the existing, billed function, called through the module so the EE
    wrapper sees it; this function is therefore BILLING_EXEMPT. Steps of
    the selection that are not gaps are skipped: the screen may be stale.
    ``recruitment`` learns nothing about ``work``: the link lives here."""
    from app.modules.competence.models import Competence
    from app.modules.primitives.models import CompetencePrimitive
    from app.modules.recruitment import vacancy_service
    from app.modules.recruitment.models import VacancyCompetence
    from app.modules.recruitment.schemas import VacancyCreate
    from app.modules.work import coverage

    container = await _writable_container(db, tenant_id, container_id)
    wanted = set(data.step_ids)
    # W6: ``gaps()`` also returns the steps an agent could take that nobody
    # has automated yet, and one does not hire for those. The filter is
    # here rather than in the checkboxes - the screen may be stale, and a
    # missing guard would open a vacancy for work an agent is about to do.
    gaps = [
        g
        for g in await coverage.gaps(db, tenant_id, container_id, user_id=user_id)
        if g["step_id"] in wanted and g["kind"] == "no_owner"
    ]
    if not gaps:
        raise AppError("work_hire_need_no_gaps", 422)
    # A double click (or a retry on a slow create) would otherwise open a
    # second draft vacancy for the same gap, and the screen only ever
    # shows the newest - the older one is then a stray nobody closes.
    # ``gaps`` already carries the need each step was handed to.
    if any(g["hire_need"] for g in gaps):
        raise AppError("work_hire_need_exists", 409)
    # Cognitive codes only (§6): one does not hire for a boundary code by
    # the description of a capability.
    codes = list(dict.fromkeys(c for g in gaps for c in g["required_codes"]))
    steps = {
        s.id: s
        for s in (
            await db.execute(
                select(WorkStep).where(WorkStep.id.in_([g["step_id"] for g in gaps]))
            )
        )
        .scalars()
        .all()
    }
    # No prose of our own around the steps: the draft lands in the tenant's
    # language, which the step titles already are.
    description = "\n\n".join(
        f"{steps[g['step_id']].title}\n{steps[g['step_id']].description}"
        if steps[g["step_id"]].description
        else steps[g["step_id"]].title
        for g in gaps[:HIRE_NEED_MAX_STEPS]
    )
    cut = len(gaps) > HIRE_NEED_MAX_STEPS
    if len(description) > HIRE_NEED_MAX_DESCRIPTION:
        description, cut = description[:HIRE_NEED_MAX_DESCRIPTION].rstrip(), True
    if cut:
        description = f"{description}\n\n{HIRE_NEED_TRUNCATED}"
    hiring_manager_id = None
    if container.owner_id and await vacancy_service._is_hiring_manager_eligible(
        db, tenant_id, container.owner_id
    ):
        hiring_manager_id = container.owner_id
    # ponytail: create_vacancy commits on its own, so a failure below
    # leaves a draft vacancy without its hire need; the draft is visible
    # in Recruitment and harmless. Fold both into one transaction if it
    # ever shows up.
    vacancy = await vacancy_service.create_vacancy(
        db,
        tenant_id,
        user_id,
        VacancyCreate(
            title=(data.title or container.title)[:VACANCY_TITLE_MAX],
            description=description,
            division_id=data.division_id,
            hiring_manager_id=hiring_manager_id,
            internal_search_allowed=data.internal_search_allowed,
        ),
    )

    # Reverse mapping primitive → competence: the competences the tenant
    # reads (its own and the shared library's) that overlap the gap, largest
    # overlap first. None is a valid answer on a cold tenant - the vacancy
    # still carries the text.
    overlap: dict[uuid.UUID, tuple[int, str]] = {}
    if codes:
        rows = await db.execute(
            select(CompetencePrimitive.competence_id, Competence.title)
            .join(Competence, Competence.id == CompetencePrimitive.competence_id)
            .join(Primitive, Primitive.id == CompetencePrimitive.primitive_id)
            .where(
                CompetencePrimitive.visible_to(tenant_id),
                Competence.is_active.is_(True),
                Competence.applicable_to != "agent",
                Primitive.code.in_(codes),
            )
        )
        for competence_id, title in rows.all():
            count, _ = overlap.get(competence_id, (0, title))
            overlap[competence_id] = (count + 1, title)
    top = sorted(overlap, key=lambda cid: (-overlap[cid][0], overlap[cid][1], cid))
    db.add_all(
        VacancyCompetence(
            tenant_id=tenant_id,
            vacancy_id=vacancy["id"],
            competence_id=cid,
            source="ai",
        )
        for cid in top[:HIRE_NEED_COMPETENCES]
    )
    need = WorkHireNeed(
        tenant_id=tenant_id,
        container_id=container.id,
        vacancy_id=vacancy["id"],
        step_ids=[str(g["step_id"]) for g in gaps],
        label=data.label,
        created_by_id=user_id,
    )
    db.add(need)
    await db.commit()
    await db.refresh(need)
    return need


# --- Step skills (HRP-760) ---------------------------------------------------

# A row left in ``generating`` by a dead worker stops blocking after this,
# both here and in the coverage read; a healthy call is under a minute.
# It has to outlast the call it guards: ``llm_client`` waits up to 600 s and
# the task may queue behind others first - a shorter cutoff would flip the
# row to ``failed`` under a live worker, whose answer is then dropped as
# superseded after the tenant has paid the provider for it.
SKILL_GENERATING_TIMEOUT = timedelta(minutes=15)

# Split billing, like the decomposition (§9): the handler prechecks, the
# work.generate_step_skill task consumes in the same commit as ``ready``.
BILLING_ACTION_SKILL = "work_skill.generate"


def effective_skill_status(status: str, updated_at: datetime, now: datetime) -> str:
    """A row abandoned in ``generating`` (cancelled request, dead worker)
    reads as ``failed`` past the timeout - the one rule for every reader,
    so the button, the dialog and the coverage row agree."""
    if status == "generating" and updated_at < now - SKILL_GENERATING_TIMEOUT:
        return "failed"
    return status


async def get_step_skill(
    db: AsyncSession, tenant_id: uuid.UUID, step_id: uuid.UUID
) -> WorkStepSkill:
    await _get_step(db, tenant_id, step_id)
    row = (
        await db.execute(select(WorkStepSkill).where(WorkStepSkill.step_id == step_id))
    ).scalar_one_or_none()
    if row is None:
        raise AppError("work_skill_not_found", 404)
    effective = effective_skill_status(row.status, row.updated_at, datetime.now(UTC))
    if effective != row.status:
        # Reported, not written: a GET must not mutate, and the row needs
        # no help - the coverage tab reads the same rule and a start
        # re-claims a stale row anyway. Detached first, so the session
        # cannot flush a status the worker still owns.
        db.expunge(row)
        row.status = effective
        row.error_message = "The generation did not finish"
    return row


async def fail_step_skill(
    db: AsyncSession, skill_id: uuid.UUID, message: str
) -> WorkStepSkill | None:
    """The claim could not be followed by a run - the credit hold was
    refused, the queue is down: the row goes to ``failed`` at once rather
    than blocking the button until it goes stale."""
    row = await db.get(WorkStepSkill, skill_id, populate_existing=True)
    if row is not None:
        row.status = "failed"
        row.error_message = message
        await db.commit()
    return row


async def start_step_skill(
    db: AsyncSession, tenant_id: uuid.UUID, step_id: uuid.UUID, *, user_id: uuid.UUID
) -> WorkStepSkill:
    """Claim the step's skill row and leave the LLM call to Celery (W6,
    §5.12). The row flips to ``generating`` and is committed before the
    task is queued, so a returning user sees it and the screen polls;
    ``generated_by_id`` is set now because the task charges on its behalf.

    Refused before anything is enqueued for a step the catalog says no
    agent performs (``blocked_*``) and for a step with no capability at
    all. The claim is under a row lock: a double click must not pay twice.
    """
    from app.modules.ai_workforce import service as agents_service
    from app.modules.work import coverage, skills

    step, _container = await _writable_step(db, tenant_id, step_id)
    primitives = (
        (
            await db.execute(
                select(Primitive)
                .join(WorkStepPrimitive, WorkStepPrimitive.primitive_id == Primitive.id)
                .where(WorkStepPrimitive.step_id == step.id)
                .order_by(Primitive.sort_index, Primitive.code)
            )
        )
        .scalars()
        .all()
    )
    mode = coverage.automation_mode(
        primitives, responsibility=step.responsibility, output_type=step.output_type
    )
    if mode is None or mode.startswith("blocked_"):
        raise AppError("work_skill_not_applicable", 422, mode=mode or "no capability")
    packs = await agents_service.list_packs(db, tenant_id)
    pack = skills.pack_for_step({p.code for p in primitives}, packs)
    if pack is None:
        fallback = skills.fallback_pack_code(primitives)
        pack = next((p for p in packs if p["code"] == fallback), None)
    if pack is None:  # the built-in pack was deactivated for this tenant
        raise AppError("work_skill_not_applicable", 422, mode=mode)

    row = (
        await db.execute(
            select(WorkStepSkill)
            .where(WorkStepSkill.step_id == step.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if (
        row is not None
        and row.status == "generating"
        and row.updated_at > now - SKILL_GENERATING_TIMEOUT
    ):
        raise AppError("work_skill_generating", 409)
    if row is None:
        row = WorkStepSkill(
            tenant_id=tenant_id, step_id=step.id, catalog_version=CATALOG_VERSION
        )
        db.add(row)
    row.status = "generating"
    row.error_message = None
    row.pack_id = pack["id"]
    row.prompt_version = skills.PROMPT_VERSION
    row.catalog_version = CATALOG_VERSION
    row.generated_by_id = user_id
    row.updated_at = now
    try:
        await db.commit()
    except IntegrityError as exc:
        # Two first-time generations at once: the lock above only covers
        # a row that exists, the unique index covers the insert race. Any
        # other violation (the step deleted under us) keeps its own cause.
        await db.rollback()
        if "uq_work_step_skills_step" not in str(exc.orig):
            raise
        raise AppError("work_skill_generating", 409) from exc
    # The stamp the worker checks before it writes: a run restarted after
    # this one went stale moves it, and the older answer is then dropped
    # unbilled rather than overwriting the newer file.
    await db.refresh(row)
    return row
