"""Cascading activation/deactivation + cycle validation (Phase CR2).

Activation walks up parents (not into siblings, not into client competences).
Deactivation walks down — but only if no published client competence exists
in the subtree, and no link to user services (matrix/employee/assessment/idp/
talent market). Cycle validation runs before reparenting via a recursive CTE.
"""

from __future__ import annotations

import uuid

from fastapi import status
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    Indicator,
    Material,
)
from app.modules.competence.usage import (
    check_competence_usage,
    check_group_usage,
    check_indicator_usage,
    check_material_usage,
    check_published_descendants,
    collect_subtree_competence_ids,
)


class CompetenceCycleError(AppError):
    # ``code`` is keyword-only: the first positional argument used to be
    # the English message, and a stale positional call would silently
    # render "errors.<message>" instead of failing loudly.
    def __init__(self, *, code: str = "competence_group_cycle_detected"):
        super().__init__(code, status.HTTP_400_BAD_REQUEST)


async def validate_no_cycles(
    db: AsyncSession,
    group_id: uuid.UUID,
    new_parent_id: uuid.UUID | None,
) -> None:
    """Raise CompetenceCycleError if reparenting `group_id` under
    `new_parent_id` would create a cycle. Uses Postgres recursive CTE so we
    don't pull the whole hierarchy into memory."""
    if new_parent_id is None:
        return
    if new_parent_id == group_id:
        raise CompetenceCycleError(code="competence_group_self_parent")

    sql = text("""
        WITH RECURSIVE parents AS (
            SELECT id, parent_id FROM competence_groups WHERE id = :start
            UNION ALL
            SELECT g.id, g.parent_id
            FROM competence_groups g
            JOIN parents p ON g.id = p.parent_id
        )
        SELECT 1 FROM parents WHERE id = :forbidden LIMIT 1
        """)
    result = await db.execute(sql, {"start": new_parent_id, "forbidden": group_id})
    if result.scalar() is not None:
        raise CompetenceCycleError()


def _tenant_scope(tenant_id: uuid.UUID):
    """HRP-140: cascade walkers accept origin (NULL tenant) and same-tenant
    nodes only. Used as a where-clause fragment on CompetenceGroup queries."""
    return or_(
        CompetenceGroup.tenant_id == tenant_id,
        CompetenceGroup.tenant_id.is_(None),
    )


def _belongs_to_tenant(
    group: CompetenceGroup | Competence, tenant_id: uuid.UUID
) -> bool:
    return group.tenant_id is None or group.tenant_id == tenant_id


async def cascade_activate_parents(
    db: AsyncSession, group: CompetenceGroup, tenant_id: uuid.UUID
) -> list[CompetenceGroup]:
    """Activate the group and walk up its ancestors, activating any inactive
    one. Sibling branches are not touched. Returns the list of newly-activated
    groups (excluding ones that were already active).

    HRP-140: stops as soon as it hits a node outside the caller's tenant
    (defence-in-depth — caller-side guard validates the entry point, this
    keeps the recursion honest if the tree ever gets a cross-tenant edge)."""
    activated: list[CompetenceGroup] = []
    current: CompetenceGroup | None = group
    while current is not None:
        if not _belongs_to_tenant(current, tenant_id):
            break
        if not current.is_active:
            current.is_active = True
            activated.append(current)
        if current.parent_id is None:
            break
        current = await db.get(CompetenceGroup, current.parent_id)
    return activated


async def cascade_activate_group(
    db: AsyncSession, group: CompetenceGroup, tenant_id: uuid.UUID
) -> list[CompetenceGroup]:
    """HRP-118: activating a group lights up every inactive ancestor *and*
    every inactive descendant group so the whole branch becomes visible in one
    click. Competences keep their own ``is_active`` flag — published client
    competences in particular are managed via ``publish_competence`` and must
    not be silently flipped here.

    HRP-140: child traversal filters by ``tenant_id`` so a stray cross-tenant
    node in the subtree is not silently activated."""
    activated: list[CompetenceGroup] = await cascade_activate_parents(
        db, group, tenant_id
    )
    seen: set[uuid.UUID] = {g.id for g in activated}

    stack: list[CompetenceGroup] = [group]
    while stack:
        node = stack.pop()
        children_q = await db.execute(
            select(CompetenceGroup).where(
                CompetenceGroup.parent_id == node.id,
                _tenant_scope(tenant_id),
            )
        )
        for child in children_q.scalars().all():
            if not child.is_active:
                child.is_active = True
                if child.id not in seen:
                    activated.append(child)
                    seen.add(child.id)
            stack.append(child)
    return activated


async def cascade_deactivate_group(
    db: AsyncSession, group: CompetenceGroup, tenant_id: uuid.UUID
) -> list[CompetenceGroup]:
    """Deactivate the group and all descendant groups + their competences,
    indicators, materials. Raises 409 if any client-published competence
    exists in the subtree, or if any descendant is referenced by user
    services. Returns the newly-deactivated group records.

    HRP-140: subtree queries are scoped to the caller's tenant so a stray
    cross-tenant descendant is never deactivated."""
    if await check_published_descendants(db, group.id):
        raise AppError(
            "competence_group_deactivate_has_published",
            status.HTTP_409_CONFLICT,
        )
    usage = await check_group_usage(db, group.id)
    if usage.is_used:
        raise AppError(
            "competence_group_deactivate_in_use",
            status.HTTP_409_CONFLICT,
        )

    visited: set[uuid.UUID] = set()
    stack: list[CompetenceGroup] = [group]
    deactivated: list[CompetenceGroup] = []
    while stack:
        node = stack.pop()
        if node.id in visited:
            continue
        visited.add(node.id)
        if node.is_active:
            node.is_active = False
            deactivated.append(node)

        # children groups
        children_q = await db.execute(
            select(CompetenceGroup).where(
                CompetenceGroup.parent_id == node.id,
                _tenant_scope(tenant_id),
            )
        )
        for child in children_q.scalars().all():
            stack.append(child)

        # competences inside this group → indicators & materials
        comps_q = await db.execute(
            select(Competence).where(
                Competence.group_id == node.id,
                or_(
                    Competence.tenant_id == tenant_id,
                    Competence.tenant_id.is_(None),
                ),
            )
        )
        for comp in comps_q.scalars().all():
            if comp.is_active:
                comp.is_active = False
            ind_q = await db.execute(
                select(Indicator).where(Indicator.competence_id == comp.id)
            )
            for ind in ind_q.scalars().all():
                if ind.is_active:
                    ind.is_active = False
            mat_q = await db.execute(
                select(Material).where(Material.competence_id == comp.id)
            )
            for mat in mat_q.scalars().all():
                if mat.is_active:
                    mat.is_active = False

    return deactivated


async def ensure_competence_can_deactivate(db: AsyncSession, comp: Competence) -> None:
    """Published client competences cannot be hidden (PM spec: client
    competences have no reverse-deactivation flow). Origin/unpublished
    competences can — only if no link exists to user services."""
    if comp.tenant_id is not None and comp.is_published:
        raise AppError(
            "competence_published_cannot_hide",
            status.HTTP_409_CONFLICT,
        )
    usage = await check_competence_usage(db, comp.id)
    if usage.is_used:
        raise AppError(
            "competence_deactivate_in_use",
            status.HTTP_409_CONFLICT,
        )


async def ensure_competence_can_delete(db: AsyncSession, comp: Competence) -> None:
    """Origin competences cannot be deleted (raised by service.delete_competence
    via tenant guard); client competences can only be deleted when not referenced."""
    usage = await check_competence_usage(db, comp.id)
    if usage.is_used:
        raise AppError(
            "competence_delete_in_use",
            status.HTTP_409_CONFLICT,
        )


async def ensure_competence_can_unpublish(db: AsyncSession, comp: Competence) -> None:
    usage = await check_competence_usage(db, comp.id)
    if usage.is_used:
        raise AppError(
            "competence_unpublish_in_use",
            status.HTTP_409_CONFLICT,
        )


async def ensure_indicator_can_mutate(db: AsyncSession, indicator: Indicator) -> None:
    """Indicator edits/moves/deactivation are blocked when assessment answers
    or PDP items reference its parent competence (per product spec)."""
    usage = await check_indicator_usage(db, indicator)
    if usage.is_used:
        raise AppError(
            "indicator_in_use",
            status.HTTP_409_CONFLICT,
        )


async def ensure_material_can_mutate(db: AsyncSession, material: Material) -> None:
    usage = await check_material_usage(db, material.id)
    if usage.is_used:
        raise AppError(
            "material_in_use",
            status.HTTP_409_CONFLICT,
        )


# Re-export for service imports
__all__ = [
    "CompetenceCycleError",
    "validate_no_cycles",
    "cascade_activate_parents",
    "cascade_activate_group",
    "cascade_deactivate_group",
    "ensure_competence_can_deactivate",
    "ensure_competence_can_delete",
    "ensure_competence_can_unpublish",
    "ensure_indicator_can_mutate",
    "ensure_material_can_mutate",
    "collect_subtree_competence_ids",
]
