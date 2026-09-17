"""AI workforce registry service (HRP-752 / HRP-753): packs, agents, usage
assignments, workflows and the audit trail (AR2).

Every mutation writes one ``AIWorkforceAuditLog`` row in the same
transaction as the change, so the log can never disagree with the data;
``created_at`` is ``clock_timestamp()`` there, so rows written by one
transaction (deactivate an agent, revoke its assignments) keep their order.
Validation happens before the first write: a foreign id, an unknown
primitive code or a closed assignment fails the call with nothing pending
in the session.

The effective capability set of a registered agent is ``pack ∪ add −
remove`` over ``AIAgentPrimitive`` (REFACTOR_PLAN §5.1); Coverage reads it
through ``effective_primitive_codes``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic_core import to_jsonable_python
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.ai_workforce import pack_data
from app.modules.ai_workforce.models import (
    AgentWorkflow,
    AIAgent,
    AIAgentPack,
    AIAgentPackPrimitive,
    AIAgentPrimitive,
    AIUsageAssignment,
    AIWorkforceAuditLog,
    ai_usage_assignment_competences,
)
from app.modules.ai_workforce.schemas import (
    AgentCreate,
    AgentUpdate,
    AssignmentApprove,
    AssignmentCreate,
    AssignmentRequest,
    AssignmentUpdate,
    PrimitiveOverride,
    WorkflowCreate,
    WorkflowStep,
    WorkflowUpdate,
)
from app.modules.competence.models import Competence
from app.modules.employee.models import Employee
from app.modules.primitives.models import Primitive

EXPIRY_WINDOW_DAYS = 30
USER_AGENT_MAX = 300
IP_ADDRESS_MAX = 45
OPEN_ASSIGNMENT_STATUSES = ("pending", "active")


# --- Audit ------------------------------------------------------------------


def _audit(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    db.add(
        AIWorkforceAuditLog(
            tenant_id=tenant_id,
            actor_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload=to_jsonable_python(payload) if payload is not None else None,
            # Both are column-width truncated: client_ip returns an
            # arbitrary X-Forwarded-For token, not a validated address.
            ip_address=ip_address[:IP_ADDRESS_MAX] if ip_address else None,
            user_agent=user_agent[:USER_AGENT_MAX] if user_agent else None,
        )
    )


def _diff(row: Any, changes: dict[str, Any]) -> tuple[dict, dict]:
    before = {k: getattr(row, k) for k in changes}
    after = {k: v for k, v in changes.items() if before[k] != v}
    return {k: before[k] for k in after}, after


# --- Packs ------------------------------------------------------------------


async def seed_packs(db: AsyncSession) -> None:
    """Insert the built-in packs that are missing; never rewrites a row."""
    # The pack-primitive insert resolves codes by ``IN``, so a code the
    # catalog does not have simply inserts one row fewer - the pack ends up
    # covering less than it declares and coverage answers ``gap`` where it
    # should answer ``agent``. Refuse instead: the catalog is seeded by
    # migration v2prim01 before any of this runs.
    wanted = {code for pack in pack_data.PACKS for code in pack["primitives"]}
    have = set(
        (
            await db.execute(select(Primitive.code).where(Primitive.code.in_(wanted)))
        ).scalars()
    )
    if missing := sorted(wanted - have):
        raise RuntimeError(
            "agent pack seed: primitive codes missing from the catalog: "
            + ", ".join(missing)
        )
    for stmt in pack_data.seed_statements():
        await db.execute(stmt)
    await db.commit()


def _visible_packs(tenant_id: uuid.UUID):
    return select(AIAgentPack).where(
        AIAgentPack.is_active.is_(True),
        or_(AIAgentPack.tenant_id.is_(None), AIAgentPack.tenant_id == tenant_id),
    )


async def _pack_codes(
    db: AsyncSession, pack_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    wanted = list({p for p in pack_ids if p})
    out: dict[uuid.UUID, list[str]] = {p: [] for p in wanted}
    if wanted:
        rows = await db.execute(
            select(AIAgentPackPrimitive.pack_id, Primitive.code)
            .join(Primitive, Primitive.id == AIAgentPackPrimitive.primitive_id)
            .where(AIAgentPackPrimitive.pack_id.in_(wanted))
            .order_by(Primitive.sort_index)
        )
        for pack_id, code in rows.all():
            out[pack_id].append(code)
    return out


async def list_packs(db: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    """Active packs visible to the tenant — built-ins plus its own — with
    their primitive codes in catalog order."""
    packs = (
        (
            await db.execute(
                _visible_packs(tenant_id).order_by(
                    AIAgentPack.tenant_id.is_not(None),
                    AIAgentPack.sort_index,
                    AIAgentPack.code,
                )
            )
        )
        .scalars()
        .all()
    )
    codes = await _pack_codes(db, (p.id for p in packs))
    return [
        {
            "id": p.id,
            "code": p.code,
            "title_en": p.title_en,
            "description_en": p.description_en,
            "i18n_key": p.i18n_key,
            "sort_index": p.sort_index,
            "is_active": p.is_active,
            "tenant_id": p.tenant_id,
            "primitive_codes": codes[p.id],
        }
        for p in packs
    ]


async def _visible_pack(
    db: AsyncSession, tenant_id: uuid.UUID, pack_id: uuid.UUID
) -> AIAgentPack:
    pack = (
        await db.execute(_visible_packs(tenant_id).where(AIAgentPack.id == pack_id))
    ).scalar_one_or_none()
    if pack is None:
        raise AppError("ai_agent_pack_not_found", 404)
    return pack


# --- Agents -----------------------------------------------------------------


async def _active_primitives(db: AsyncSession) -> dict[str, Primitive]:
    rows = await db.execute(select(Primitive).where(Primitive.retired_in.is_(None)))
    return {p.code: p for p in rows.scalars().all()}


def _validated_overrides(
    items: Sequence[PrimitiveOverride], catalog: dict[str, Primitive]
) -> list[tuple[str, str]]:
    """Deduplicate, reject unknown / retired codes and add+remove conflicts."""
    modes: dict[str, set[str]] = {}
    for item in items:
        modes.setdefault(item.code, set()).add(item.mode)
    unknown = [code for code in modes if code not in catalog]
    if unknown:
        raise AppError("primitive_not_found", 404, codes=", ".join(sorted(unknown)))
    conflicts = [code for code, ms in modes.items() if len(ms) > 1]
    if conflicts:
        raise AppError(
            "ai_agent_primitive_mode_conflict", 400, codes=", ".join(sorted(conflicts))
        )
    return [(code, next(iter(ms))) for code, ms in modes.items()]


def _effective(
    pack_codes: Iterable[str],
    overrides: Iterable[tuple[str, str]],
    order: dict[str, int],
) -> list[str]:
    codes = set(pack_codes)
    for code, mode in overrides:
        if mode == "add":
            codes.add(code)
        else:
            codes.discard(code)
    # A code retired after it was linked sorts last rather than failing.
    return sorted(codes, key=lambda c: order.get(c, 10**6))


async def _agent_reads(db: AsyncSession, agents: Sequence[AIAgent]) -> list[dict]:
    if not agents:
        return []
    pack_ids = [a.pack_id for a in agents if a.pack_id]
    pack_codes = await _pack_codes(db, pack_ids)
    pack_names: dict[uuid.UUID, str] = {}
    if pack_ids:
        pack_rows = await db.execute(
            select(AIAgentPack.id, AIAgentPack.code).where(AIAgentPack.id.in_(pack_ids))
        )
        pack_names = dict(pack_rows.tuples().all())
    overrides: dict[uuid.UUID, list[tuple[str, str]]] = {a.id: [] for a in agents}
    rows = await db.execute(
        select(AIAgentPrimitive.agent_id, Primitive.code, AIAgentPrimitive.mode)
        .join(Primitive, Primitive.id == AIAgentPrimitive.primitive_id)
        .where(AIAgentPrimitive.agent_id.in_(list(overrides)))
        .order_by(Primitive.sort_index)
    )
    for agent_id, code, mode in rows.all():
        overrides[agent_id].append((code, mode))
    order = {code: p.sort_index for code, p in (await _active_primitives(db)).items()}
    return [
        {
            "id": a.id,
            "tenant_id": a.tenant_id,
            "name": a.name,
            "vendor": a.vendor,
            "category": a.category,
            "description": a.description,
            "homepage_url": a.homepage_url,
            "pack_id": a.pack_id,
            "pack_code": pack_names.get(a.pack_id) if a.pack_id else None,
            "seats_count": a.seats_count,
            "monthly_cost": a.monthly_cost,
            "cost_currency": a.cost_currency,
            "contract_renewal_date": a.contract_renewal_date,
            "data_classification": a.data_classification,
            "security_review_status": a.security_review_status,
            "security_review_date": a.security_review_date,
            "security_review_notes": a.security_review_notes,
            "eu_ai_act_risk_level": a.eu_ai_act_risk_level,
            "is_active": a.is_active,
            "deactivated_at": a.deactivated_at,
            "primitive_overrides": [
                {"code": code, "mode": mode} for code, mode in overrides[a.id]
            ],
            "effective_primitive_codes": _effective(
                pack_codes.get(a.pack_id, []) if a.pack_id else [],
                overrides[a.id],
                order,
            ),
            "created_at": a.created_at,
            "updated_at": a.updated_at,
        }
        for a in agents
    ]


def _violates(exc: IntegrityError, constraint: str) -> bool:
    """Map an IntegrityError onto a domain 409 only when it really is that
    constraint. Anything else keeps its own cause: a 409 naming the wrong
    column sends the caller looking for a collision that never happened."""
    return constraint in str(exc.orig)


async def _agent_row(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> AIAgent:
    stmt = select(AIAgent).where(AIAgent.id == agent_id, AIAgent.tenant_id == tenant_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise AppError("ai_agent_not_found", 404)
    return row


async def _ensure_name_free(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    name: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    stmt = select(AIAgent.id).where(
        AIAgent.tenant_id == tenant_id, func.lower(AIAgent.name) == name.lower()
    )
    if exclude_id is not None:
        stmt = stmt.where(AIAgent.id != exclude_id)
    if (await db.execute(stmt)).first() is not None:
        raise AppError("ai_agent_name_taken", 409)


async def list_agents(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    is_active: bool | None = None,
    category: str | None = None,
    pack_id: uuid.UUID | None = None,
    search: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    stmt = select(AIAgent).where(AIAgent.tenant_id == tenant_id)
    if is_active is not None:
        stmt = stmt.where(AIAgent.is_active.is_(is_active))
    if category:
        stmt = stmt.where(AIAgent.category == category)
    if pack_id:
        stmt = stmt.where(AIAgent.pack_id == pack_id)
    if search:
        stmt = stmt.where(AIAgent.name.ilike(f"%{search}%"))
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = await db.execute(stmt.order_by(AIAgent.name).offset(skip).limit(limit))
    return await _agent_reads(db, rows.scalars().all()), total


async def get_agent(
    db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID
) -> dict:
    return (await _agent_reads(db, [await _agent_row(db, tenant_id, agent_id)]))[0]


async def create_agent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: AgentCreate,
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    if data.pack_id is not None:
        await _visible_pack(db, tenant_id, data.pack_id)
    await _ensure_name_free(db, tenant_id, data.name)
    catalog = await _active_primitives(db)
    overrides = _validated_overrides(data.primitives, catalog)

    agent = AIAgent(tenant_id=tenant_id, **data.model_dump(exclude={"primitives"}))
    db.add(agent)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Two concurrent creates with one name: the unique index decides.
        await db.rollback()
        if not _violates(exc, "uq_ai_agents_tenant_name_lower"):
            raise
        raise AppError("ai_agent_name_taken", 409) from None
    db.add_all(
        AIAgentPrimitive(agent_id=agent.id, primitive_id=catalog[code].id, mode=mode)
        for code, mode in overrides
    )
    _audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="agent.created",
        target_type="ai_agent",
        target_id=agent.id,
        payload={"name": agent.name, "pack_id": agent.pack_id},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return await get_agent(db, tenant_id, agent.id)


async def update_agent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    data: AgentUpdate,
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    # Deactivation is final - there is no reactivate route and no
    # ``is_active`` in ``AgentUpdate`` - so editing a deactivated agent can
    # only put contract and compliance data on a tool nobody may use.
    agent = await _active_agent(db, tenant_id, agent_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("pack_id") is not None and changes["pack_id"] != agent.pack_id:
        await _visible_pack(db, tenant_id, changes["pack_id"])
    if "name" in changes and changes["name"] != agent.name:
        await _ensure_name_free(db, tenant_id, changes["name"], exclude_id=agent.id)
    before, after = _diff(agent, changes)
    if after:
        for key, value in after.items():
            setattr(agent, key, value)
        _audit(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="agent.updated",
            target_type="ai_agent",
            target_id=agent.id,
            payload={"before": before, "after": after},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            if not _violates(exc, "uq_ai_agents_tenant_name_lower"):
                raise
            raise AppError("ai_agent_name_taken", 409) from None
    return await get_agent(db, tenant_id, agent.id)


async def set_agent_primitives(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    items: Sequence[PrimitiveOverride],
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """Replace the agent's add/remove delta against its pack."""
    # Same rule as ``update_agent``: a deactivated agent is not edited.
    agent = await _active_agent(db, tenant_id, agent_id)
    catalog = await _active_primitives(db)
    overrides = _validated_overrides(items, catalog)
    await db.execute(
        delete(AIAgentPrimitive).where(AIAgentPrimitive.agent_id == agent.id)
    )
    db.add_all(
        AIAgentPrimitive(agent_id=agent.id, primitive_id=catalog[code].id, mode=mode)
        for code, mode in overrides
    )
    _audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="agent.primitives_set",
        target_type="ai_agent",
        target_id=agent.id,
        payload={"primitives": [{"code": c, "mode": m} for c, m in overrides]},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return await get_agent(db, tenant_id, agent.id)


async def delete_agent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """Soft delete: deactivates the agent and revokes its open assignments
    (AR2 cascade). A second call is a no-op.

    Refused while an active workflow still names the agent in a step: the
    step validation only checks that the agent exists, so the process would
    keep pointing at an agent nobody may use any more. Edit the workflow (or
    deactivate it) first."""
    agent = await _agent_row(db, tenant_id, agent_id)
    if agent.is_active:
        used_by = await db.execute(
            select(AgentWorkflow.id).where(
                AgentWorkflow.tenant_id == tenant_id,
                AgentWorkflow.is_active.is_(True),
                AgentWorkflow.steps.contains([{"agent_id": str(agent.id)}]),
            )
        )
        if used_by.first() is not None:
            raise AppError("ai_agent_in_workflow", 409)
        agent.is_active = False
        agent.deactivated_at = datetime.now(UTC)
        open_rows = (
            (
                await db.execute(
                    select(AIUsageAssignment)
                    .where(
                        # The agent is this tenant's, so its assignments can
                        # only be too - but the cascade writes a revoke and an
                        # audit row under ``tenant_id``, and those must never
                        # be written for a row that is not in it.
                        AIUsageAssignment.tenant_id == tenant_id,
                        AIUsageAssignment.agent_id == agent.id,
                        AIUsageAssignment.status.in_(OPEN_ASSIGNMENT_STATUSES),
                    )
                    .order_by(AIUsageAssignment.created_at, AIUsageAssignment.id)
                    # Locked against a concurrent approve; a concurrent
                    # create serialises on the agent row in _active_agent.
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for row in open_rows:
            row.status = "revoked"
            _audit(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                action="assignment.revoked",
                target_type="ai_usage_assignment",
                target_id=row.id,
                payload={"reason": "agent_deactivated", "agent_id": agent.id},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        _audit(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="agent.deactivated",
            target_type="ai_agent",
            target_id=agent.id,
            payload={"revoked_assignments": [r.id for r in open_rows]},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await db.commit()
    return await get_agent(db, tenant_id, agent.id)


# --- Usage assignments ------------------------------------------------------


async def _employee_in_tenant(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> Employee:
    row = (
        await db.execute(
            select(Employee).where(
                Employee.id == employee_id, Employee.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError("employee_not_found", 404)
    return row


async def _competences_in_tenant(
    db: AsyncSession, tenant_id: uuid.UUID, ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return []
    rows = await db.execute(
        select(Competence.id).where(
            Competence.id.in_(wanted),
            or_(Competence.tenant_id == tenant_id, Competence.tenant_id.is_(None)),
        )
    )
    found = set(rows.scalars().all())
    if len(found) != len(wanted):
        raise AppError("competence_not_found", 404)
    return wanted


async def _active_agent(
    db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID
) -> AIAgent:
    # FOR UPDATE: delete_agent's cascade can only revoke assignments that
    # exist when it runs, so a create racing it must serialise on the agent
    # row - otherwise it attaches an active assignment to an agent that is
    # already deactivated, the exact state AR2 exists to prevent.
    agent = await _agent_row(db, tenant_id, agent_id, for_update=True)
    if not agent.is_active:
        raise AppError("ai_agent_inactive", 409)
    return agent


def _active_grant():
    """What counts as an assignment actually in force.

    ``accountability_owner_id`` is ON DELETE SET NULL, so deleting the owner
    employee leaves a row that still says ``active`` with nobody answering
    for the agent's use - which AR2 does not recognise as a grant. The row
    keeps its status (an unfiltered listing shows it, so it can be repaired)
    and counts as active nowhere.
    """
    return (
        AIUsageAssignment.status == "active",
        AIUsageAssignment.accountability_owner_id.is_not(None),
    )


async def _ensure_no_active_grant(
    db: AsyncSession, employee_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
    """One active grant per (employee, agent): a second says nothing the
    first does not, and the two disagree on the use cases and the
    supervision level the register is supposed to answer for.

    On the raw status, not ``_active_grant``: a row that lost its owner is
    repaired (or revoked), never stacked under a second one."""
    open_row = await db.execute(
        select(AIUsageAssignment.id).where(
            AIUsageAssignment.employee_id == employee_id,
            AIUsageAssignment.agent_id == agent_id,
            AIUsageAssignment.status == "active",
        )
    )
    if open_row.first() is not None:
        raise AppError("ai_assignment_already_active", 409)


def _check_period(valid_from: date, valid_until: date | None) -> None:
    if valid_until is not None and valid_until < valid_from:
        raise AppError("ai_assignment_invalid_period", 400)


async def _assignment_row(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> AIUsageAssignment:
    stmt = select(AIUsageAssignment).where(
        AIUsageAssignment.id == assignment_id,
        AIUsageAssignment.tenant_id == tenant_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise AppError("ai_assignment_not_found", 404)
    return row


async def _set_competence_scope(
    db: AsyncSession, assignment_id: uuid.UUID, competence_ids: Sequence[uuid.UUID]
) -> None:
    await db.execute(
        delete(ai_usage_assignment_competences).where(
            ai_usage_assignment_competences.c.assignment_id == assignment_id
        )
    )
    if competence_ids:
        await db.execute(
            ai_usage_assignment_competences.insert(),
            [
                {"assignment_id": assignment_id, "competence_id": c}
                for c in competence_ids
            ],
        )


async def _assignment_reads(
    db: AsyncSession, rows: Sequence[AIUsageAssignment]
) -> list[dict]:
    if not rows:
        return []
    ids = [r.id for r in rows]
    scope: dict[uuid.UUID, list[uuid.UUID]] = {i: [] for i in ids}
    links = await db.execute(
        select(
            ai_usage_assignment_competences.c.assignment_id,
            ai_usage_assignment_competences.c.competence_id,
        ).where(ai_usage_assignment_competences.c.assignment_id.in_(ids))
    )
    for assignment_id, competence_id in links.all():
        scope[assignment_id].append(competence_id)
    agent_rows = await db.execute(
        select(AIAgent.id, AIAgent.name).where(
            AIAgent.id.in_({r.agent_id for r in rows})
        )
    )
    names: dict[uuid.UUID, str] = dict(agent_rows.tuples().all())
    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "employee_id": r.employee_id,
            "agent_id": r.agent_id,
            "agent_name": names.get(r.agent_id, ""),
            "allowed_use_cases": r.allowed_use_cases,
            "supervision_level": r.supervision_level,
            "accountability_owner_id": r.accountability_owner_id,
            "valid_from": r.valid_from,
            "valid_until": r.valid_until,
            "status": r.status,
            "requested_at": r.requested_at,
            "approved_at": r.approved_at,
            "approved_by_id": r.approved_by_id,
            "competence_ids": scope[r.id],
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


async def list_assignments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    employee_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    stmt = select(AIUsageAssignment).where(AIUsageAssignment.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(AIUsageAssignment.employee_id == employee_id)
    if agent_id:
        stmt = stmt.where(AIUsageAssignment.agent_id == agent_id)
    if owner_id:
        stmt = stmt.where(AIUsageAssignment.accountability_owner_id == owner_id)
    if status == "active":
        stmt = stmt.where(*_active_grant())
    elif status:
        stmt = stmt.where(AIUsageAssignment.status == status)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = await db.execute(
        stmt.order_by(AIUsageAssignment.created_at.desc()).offset(skip).limit(limit)
    )
    return await _assignment_reads(db, rows.scalars().all()), total


async def get_assignment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    requester_user_id: uuid.UUID | None = None,
) -> dict:
    """With ``requester_user_id`` the row is returned only when it belongs
    to that user's own employee record — a plain employee may read what
    they requested, and nothing else (404, not 403: no probing)."""
    row = await _assignment_row(db, tenant_id, assignment_id)
    if requester_user_id is not None:
        owner = (
            await db.execute(
                select(Employee.user_id).where(Employee.id == row.employee_id)
            )
        ).scalar_one_or_none()
        if owner != requester_user_id:
            raise AppError("ai_assignment_not_found", 404)
    return (await _assignment_reads(db, [row]))[0]


async def create_assignment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: AssignmentCreate,
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """An admin grants the assignment outright: active, approved by the caller."""
    await _employee_in_tenant(db, tenant_id, data.employee_id)
    await _employee_in_tenant(db, tenant_id, data.accountability_owner_id)
    await _active_agent(db, tenant_id, data.agent_id)
    # Under the agent row lock ``_active_agent`` just took, so two creates
    # for one pair serialise here instead of both writing a grant.
    await _ensure_no_active_grant(db, data.employee_id, data.agent_id)
    competence_ids = await _competences_in_tenant(db, tenant_id, data.competence_ids)
    valid_from = data.valid_from or date.today()
    _check_period(valid_from, data.valid_until)

    row = AIUsageAssignment(
        tenant_id=tenant_id,
        employee_id=data.employee_id,
        agent_id=data.agent_id,
        allowed_use_cases=data.allowed_use_cases,
        supervision_level=data.supervision_level,
        accountability_owner_id=data.accountability_owner_id,
        valid_from=valid_from,
        valid_until=data.valid_until,
        status="active",
        approved_at=datetime.now(UTC),
        approved_by_id=user_id,
    )
    db.add(row)
    await db.flush()
    await _set_competence_scope(db, row.id, competence_ids)
    _audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assignment.created",
        target_type="ai_usage_assignment",
        target_id=row.id,
        payload={"employee_id": row.employee_id, "agent_id": row.agent_id},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return await get_assignment(db, tenant_id, row.id)


async def request_assignment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: AssignmentRequest,
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """Self-service: the caller's own employee row asks for an agent; the
    row waits in ``pending`` for ``approve_assignment``."""
    employee = (
        await db.execute(
            select(Employee).where(
                Employee.user_id == user_id, Employee.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if employee is None:
        raise AppError("employee_not_found", 404)
    await _active_agent(db, tenant_id, data.agent_id)
    pending = await db.execute(
        select(AIUsageAssignment.id).where(
            AIUsageAssignment.employee_id == employee.id,
            AIUsageAssignment.agent_id == data.agent_id,
            AIUsageAssignment.status == "pending",
        )
    )
    if pending.first() is not None:
        raise AppError("ai_assignment_already_requested", 409)
    if data.accountability_owner_id is not None:
        await _employee_in_tenant(db, tenant_id, data.accountability_owner_id)
    competence_ids = await _competences_in_tenant(db, tenant_id, data.competence_ids)
    valid_from = date.today()
    _check_period(valid_from, data.valid_until)

    row = AIUsageAssignment(
        tenant_id=tenant_id,
        employee_id=employee.id,
        agent_id=data.agent_id,
        allowed_use_cases=data.allowed_use_cases,
        accountability_owner_id=data.accountability_owner_id,
        valid_from=valid_from,
        valid_until=data.valid_until,
        status="pending",
        requested_at=datetime.now(UTC),
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        # The check above is check-then-insert; a double click loses here
        # on uq_ai_assignments_pending instead of making a second request.
        await db.rollback()
        if not _violates(exc, "uq_ai_assignments_pending"):
            raise
        raise AppError("ai_assignment_already_requested", 409) from None
    await _set_competence_scope(db, row.id, competence_ids)
    _audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assignment.requested",
        target_type="ai_usage_assignment",
        target_id=row.id,
        payload={"employee_id": row.employee_id, "agent_id": row.agent_id},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return await get_assignment(db, tenant_id, row.id)


async def update_assignment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assignment_id: uuid.UUID,
    data: AssignmentUpdate,
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    row = await _assignment_row(db, tenant_id, assignment_id)
    if row.status not in OPEN_ASSIGNMENT_STATUSES:
        raise AppError("ai_assignment_closed", 409)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("accountability_owner_id") is not None:
        await _employee_in_tenant(db, tenant_id, changes["accountability_owner_id"])
    _check_period(
        changes.get("valid_from") or row.valid_from,
        changes.get("valid_until", row.valid_until),
    )
    scope = changes.pop("competence_ids", None)
    if scope is not None:
        scope = await _competences_in_tenant(db, tenant_id, scope)
        current = (await _assignment_reads(db, [row]))[0]["competence_ids"]
        if set(scope) == set(current):
            scope = None
    before, after = _diff(row, changes)
    if after or scope is not None:
        for key, value in after.items():
            setattr(row, key, value)
        if scope is not None:
            await _set_competence_scope(db, row.id, scope)
            before["competence_ids"] = current
            after["competence_ids"] = scope
        _audit(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="assignment.updated",
            target_type="ai_usage_assignment",
            target_id=row.id,
            payload={"before": before, "after": after},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await db.commit()
    return await get_assignment(db, tenant_id, row.id)


async def approve_assignment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assignment_id: uuid.UUID,
    data: AssignmentApprove,
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    # FOR UPDATE: two approvers racing on one request must not both win.
    row = await _assignment_row(db, tenant_id, assignment_id, for_update=True)
    if row.status != "pending":
        raise AppError("ai_assignment_not_pending", 409)
    # Approving is the other way a grant becomes active, so the same rule.
    await _ensure_no_active_grant(db, row.employee_id, row.agent_id)
    owner_id = data.accountability_owner_id or row.accountability_owner_id
    if owner_id is None:
        raise AppError("ai_assignment_owner_required", 400)
    await _employee_in_tenant(db, tenant_id, owner_id)
    valid_until = data.valid_until if data.valid_until is not None else row.valid_until
    _check_period(row.valid_from, valid_until)

    row.accountability_owner_id = owner_id
    row.valid_until = valid_until
    if data.supervision_level is not None:
        row.supervision_level = data.supervision_level
    row.status = "active"
    row.approved_at = datetime.now(UTC)
    row.approved_by_id = user_id
    _audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="approval.granted",
        target_type="ai_usage_assignment",
        target_id=row.id,
        payload={
            "accountability_owner_id": owner_id,
            "supervision_level": row.supervision_level,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return await get_assignment(db, tenant_id, row.id)


async def reject_assignment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    row = await _assignment_row(db, tenant_id, assignment_id, for_update=True)
    if row.status != "pending":
        raise AppError("ai_assignment_not_pending", 409)
    row.status = "rejected"
    _audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assignment.rejected",
        target_type="ai_usage_assignment",
        target_id=row.id,
        payload={"reason": reason},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return await get_assignment(db, tenant_id, row.id)


async def revoke_assignment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    row = await _assignment_row(db, tenant_id, assignment_id, for_update=True)
    if row.status != "active":
        raise AppError("ai_assignment_not_active", 409)
    row.status = "revoked"
    _audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="assignment.revoked",
        target_type="ai_usage_assignment",
        target_id=row.id,
        payload={"reason": reason},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return await get_assignment(db, tenant_id, row.id)


async def change_supervision_level(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assignment_id: uuid.UUID,
    supervision_level: str,
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """Its own function and audit action: a supervision change is the
    compliance event, not an edit."""
    # FOR UPDATE like the other status writers: a supervision change racing
    # a revoke must not land on a row that has just closed.
    row = await _assignment_row(db, tenant_id, assignment_id, for_update=True)
    if row.status not in OPEN_ASSIGNMENT_STATUSES:
        raise AppError("ai_assignment_closed", 409)
    if row.supervision_level != supervision_level:
        before = row.supervision_level
        row.supervision_level = supervision_level
        _audit(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="supervision.changed",
            target_type="ai_usage_assignment",
            target_id=row.id,
            payload={"before": before, "after": supervision_level},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await db.commit()
    return await get_assignment(db, tenant_id, row.id)


async def list_expiring_assignments(
    db: AsyncSession, tenant_id: uuid.UUID, *, days_ahead: int = EXPIRY_WINDOW_DAYS
) -> list[dict]:
    """Active assignments whose ``valid_until`` falls within the window —
    including ones already past it: nothing flips a lapsed row on its own
    (decision 2026-09-09), so it stays here until a person revokes it."""
    rows = await db.execute(
        select(AIUsageAssignment)
        .where(
            AIUsageAssignment.tenant_id == tenant_id,
            *_active_grant(),
            AIUsageAssignment.valid_until.is_not(None),
            AIUsageAssignment.valid_until <= date.today() + timedelta(days=days_ahead),
        )
        .order_by(AIUsageAssignment.valid_until, AIUsageAssignment.created_at)
    )
    return await _assignment_reads(db, rows.scalars().all())


# --- Workflows --------------------------------------------------------------


async def _workflow_row(
    db: AsyncSession, tenant_id: uuid.UUID, workflow_id: uuid.UUID
) -> AgentWorkflow:
    row = (
        await db.execute(
            select(AgentWorkflow).where(
                AgentWorkflow.id == workflow_id, AgentWorkflow.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError("agent_workflow_not_found", 404)
    return row


async def _validated_steps(
    db: AsyncSession, tenant_id: uuid.UUID, steps: Sequence[WorkflowStep]
) -> list[dict]:
    agent_ids = {s.agent_id for s in steps if s.agent_id}
    if agent_ids:
        found = set(
            (
                await db.execute(
                    select(AIAgent.id).where(
                        AIAgent.id.in_(agent_ids), AIAgent.tenant_id == tenant_id
                    )
                )
            )
            .scalars()
            .all()
        )
        if found != agent_ids:
            raise AppError("ai_agent_not_found", 404)
    escalation_ids = {s.escalation_to for s in steps if s.escalation_to}
    if escalation_ids:
        # One query, not one per step: a 100-step workflow is a valid body.
        found = set(
            (
                await db.execute(
                    select(Employee.id).where(
                        Employee.id.in_(escalation_ids),
                        Employee.tenant_id == tenant_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if found != escalation_ids:
            raise AppError("employee_not_found", 404)
    return [s.model_dump(mode="json") for s in steps]


async def list_workflows(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    is_active: bool | None = None,
    owner_id: uuid.UUID | None = None,
    human_role: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[AgentWorkflow], int]:
    stmt = select(AgentWorkflow).where(AgentWorkflow.tenant_id == tenant_id)
    if is_active is not None:
        stmt = stmt.where(AgentWorkflow.is_active.is_(is_active))
    if owner_id:
        stmt = stmt.where(AgentWorkflow.owner_id == owner_id)
    if human_role:
        stmt = stmt.where(AgentWorkflow.human_role == human_role)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = await db.execute(stmt.order_by(AgentWorkflow.name).offset(skip).limit(limit))
    return list(rows.scalars().all()), total


async def get_workflow(
    db: AsyncSession, tenant_id: uuid.UUID, workflow_id: uuid.UUID
) -> AgentWorkflow:
    return await _workflow_row(db, tenant_id, workflow_id)


async def create_workflow(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: WorkflowCreate,
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AgentWorkflow:
    await _employee_in_tenant(db, tenant_id, data.owner_id)
    steps = await _validated_steps(db, tenant_id, data.steps)
    row = AgentWorkflow(
        tenant_id=tenant_id, **data.model_dump(exclude={"steps"}), steps=steps
    )
    db.add(row)
    await db.flush()
    _audit(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="workflow.created",
        target_type="agent_workflow",
        target_id=row.id,
        payload={"name": row.name, "human_role": row.human_role},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(row)
    return row


async def update_workflow(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    data: WorkflowUpdate,
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AgentWorkflow:
    row = await _workflow_row(db, tenant_id, workflow_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("owner_id") is not None:
        await _employee_in_tenant(db, tenant_id, changes["owner_id"])
    if changes.get("steps") is None:
        # NOT NULL column: null in the body means "leave the steps alone".
        changes.pop("steps", None)
    else:
        changes["steps"] = await _validated_steps(db, tenant_id, data.steps or [])
    before, after = _diff(row, changes)
    if after:
        for key, value in after.items():
            setattr(row, key, value)
        _audit(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="workflow.updated",
            target_type="agent_workflow",
            target_id=row.id,
            payload={"before": before, "after": after},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await db.commit()
        await db.refresh(row)
    return row


async def delete_workflow(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AgentWorkflow:
    """Soft delete; a second call is a no-op."""
    row = await _workflow_row(db, tenant_id, workflow_id)
    if row.is_active:
        row.is_active = False
        row.deactivated_at = datetime.now(UTC)
        _audit(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="workflow.deactivated",
            target_type="agent_workflow",
            target_id=row.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await db.commit()
        await db.refresh(row)
    return row


# --- Audit ------------------------------------------------------------------


async def list_audit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[AIWorkforceAuditLog], int]:
    stmt = select(AIWorkforceAuditLog).where(AIWorkforceAuditLog.tenant_id == tenant_id)
    if target_type:
        stmt = stmt.where(AIWorkforceAuditLog.target_type == target_type)
    if target_id:
        stmt = stmt.where(AIWorkforceAuditLog.target_id == target_id)
    if actor_id:
        stmt = stmt.where(AIWorkforceAuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(AIWorkforceAuditLog.action == action)
    if date_from:
        stmt = stmt.where(AIWorkforceAuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AIWorkforceAuditLog.created_at <= date_to)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = await db.execute(
        stmt.order_by(AIWorkforceAuditLog.created_at.desc()).offset(skip).limit(limit)
    )
    return list(rows.scalars().all()), total
