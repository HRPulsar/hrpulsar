import uuid

from fastapi import status
from pydantic_core import to_jsonable_python
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.competence.cascade import (
    cascade_activate_group,
    cascade_activate_parents,
    cascade_deactivate_group,
    ensure_competence_can_deactivate,
    ensure_competence_can_delete,
    ensure_competence_can_unpublish,
    ensure_indicator_can_mutate,
    ensure_material_can_mutate,
    validate_no_cycles,
)
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    CompetenceTreeAuditLog,
    Indicator,
    Material,
    SkillLevel,
)
from app.modules.competence.schemas import (
    CompetenceBulkCreate,
    CompetenceCreate,
    CompetenceGroupCreate,
    CompetenceGroupTree,
    CompetenceGroupUpdate,
    CompetenceRead,
    CompetenceUpdate,
    IndicatorCreate,
    IndicatorUpdate,
    MaterialCreate,
    MaterialUpdate,
)
from app.modules.competence.usage import (
    check_competence_usage,
    check_skill_level_usage,
)

# --- Audit log helper ---


async def _audit(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    action: str,
    element_type: str | None = None,
    element_id: uuid.UUID | None = None,
    payload: dict | None = None,
) -> None:
    # JSONB column: coerce UUID/datetime/Decimal/Enum to JSON-safe primitives
    # so callers can pass `data.model_dump()` directly without per-field stringification.
    safe_payload = to_jsonable_python(payload) if payload is not None else None
    db.add(
        CompetenceTreeAuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            element_type=element_type,
            element_id=element_id,
            payload=safe_payload,
        )
    )


# --- Tenant filters ---


def _tenant_filter(tenant_id: uuid.UUID):
    return or_(
        CompetenceGroup.tenant_id == tenant_id,
        CompetenceGroup.tenant_id.is_(None),
    )


# --- Tree enrichment helpers ---


async def _used_competence_ids(
    db: AsyncSession, ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Bulk usage check across all consumer tables. Returns the subset of
    input ids that have at least one inbound reference."""
    if not ids:
        return set()
    from app.modules.assessment.models import (
        AssessmentCompetence,
        AssessmentResult,
        PDPItem,
    )
    from app.modules.employee.models import (
        CourseCompetence,
        WorkExperienceCompetence,
    )
    from app.modules.grade_system.models import GradeCompetenceLink
    from app.modules.talent_market.models import TalentCardCompetence

    used: set[uuid.UUID] = set()
    for q in (
        select(GradeCompetenceLink.competence_id).where(
            GradeCompetenceLink.competence_id.in_(ids)
        ),
        select(WorkExperienceCompetence.competence_id).where(
            WorkExperienceCompetence.competence_id.in_(ids)
        ),
        select(CourseCompetence.competence_id).where(
            CourseCompetence.competence_id.in_(ids)
        ),
        select(AssessmentCompetence.competence_id).where(
            AssessmentCompetence.competence_id.in_(ids)
        ),
        select(AssessmentResult.competence_id).where(
            AssessmentResult.competence_id.in_(ids)
        ),
        select(PDPItem.competence_id).where(PDPItem.competence_id.in_(ids)),
        select(TalentCardCompetence.competence_id).where(
            TalentCardCompetence.competence_id.in_(ids)
        ),
    ):
        rows = await db.execute(q)
        for cid in rows.scalars().all():
            if cid is not None:
                used.add(cid)
    return used


async def _levels_completion_map(
    db: AsyncSession,
    competence_ids: list[uuid.UUID],
    expected_level_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict]:
    """Returns {competence_id: {has_uncovered_indicators, has_uncovered_materials}}.
    A level is "covered" when ≥1 active indicator (or material) is attached."""
    if not competence_ids or not expected_level_ids:
        return {}

    ind_q = await db.execute(
        select(Indicator.competence_id, Indicator.skill_level_id)
        .where(
            Indicator.competence_id.in_(competence_ids),
            Indicator.skill_level_id.in_(expected_level_ids),
            Indicator.is_active.is_(True),
        )
        .distinct()
    )
    ind_pairs: set[tuple[uuid.UUID, uuid.UUID]] = {
        (cid, lid) for cid, lid in ind_q.all()
    }

    mat_q = await db.execute(
        select(Material.competence_id, Material.skill_level_id)
        .where(
            Material.competence_id.in_(competence_ids),
            Material.skill_level_id.in_(expected_level_ids),
            Material.is_active.is_(True),
        )
        .distinct()
    )
    mat_pairs: set[tuple[uuid.UUID, uuid.UUID]] = {
        (cid, lid) for cid, lid in mat_q.all()
    }

    out: dict[uuid.UUID, dict] = {}
    for cid in competence_ids:
        missing_ind = any((cid, lid) not in ind_pairs for lid in expected_level_ids)
        missing_mat = any((cid, lid) not in mat_pairs for lid in expected_level_ids)
        out[cid] = {
            "has_uncovered_indicators": missing_ind,
            "has_uncovered_materials": missing_mat,
        }
    return out


# --- CompetenceGroup ---


async def get_competence_tree(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[CompetenceGroupTree]:
    """Returns origin + tenant tree, alphabetically sorted, with usage and
    levels-completion enrichment."""
    groups_q = await db.execute(
        select(CompetenceGroup)
        .where(_tenant_filter(tenant_id))
        .order_by(func.lower(CompetenceGroup.title))
    )
    groups = list(groups_q.scalars().all())

    comps_q = await db.execute(
        select(Competence)
        .where(
            or_(
                Competence.tenant_id == tenant_id,
                Competence.tenant_id.is_(None),
            )
        )
        .order_by(func.lower(Competence.title))
    )
    competences = list(comps_q.scalars().all())

    levels_q = await db.execute(
        select(SkillLevel).where(
            or_(
                SkillLevel.tenant_id == tenant_id,
                SkillLevel.tenant_id.is_(None),
            ),
            SkillLevel.is_active.is_(True),
        )
    )
    expected_level_ids = [lvl.id for lvl in levels_q.scalars().all()]

    competence_ids = [c.id for c in competences]
    used_ids = await _used_competence_ids(db, competence_ids)
    client_competence_ids = [c.id for c in competences if c.tenant_id is not None]
    completion = await _levels_completion_map(
        db, client_competence_ids, expected_level_ids
    )

    comp_by_group: dict[uuid.UUID, list[CompetenceRead]] = {}
    for c in competences:
        read = CompetenceRead(
            id=c.id,
            title=c.title,
            description=c.description,
            group_id=c.group_id,
            competence_type_id=c.competence_type_id,
            tenant_id=c.tenant_id,
            is_active=c.is_active,
            is_published=c.is_published,
            created_at=c.created_at,
            is_origin=(c.tenant_id is None),
            is_used=(c.id in used_ids),
            levels_completion=completion.get(c.id),
        )
        comp_by_group.setdefault(c.group_id, []).append(read)

    nodes: dict[uuid.UUID, CompetenceGroupTree] = {}
    direct_count: dict[uuid.UUID, int] = {}
    for g in groups:
        direct_count[g.id] = len(comp_by_group.get(g.id, []))

    for g in groups:
        nodes[g.id] = CompetenceGroupTree(
            id=g.id,
            title=g.title,
            description=g.description,
            parent_id=g.parent_id,
            tenant_id=g.tenant_id,
            sort_index=g.sort_index,
            is_active=g.is_active,
            can_deactivate=g.can_deactivate,
            is_root_origin=(g.parent_id is None and g.tenant_id is None),
            created_at=g.created_at,
            children=[],
            competences=comp_by_group.get(g.id, []),
        )

    roots: list[CompetenceGroupTree] = []
    for node in nodes.values():
        if node.parent_id and node.parent_id in nodes:
            nodes[node.parent_id].children.append(node)
        else:
            roots.append(node)

    # HRP-118: precompute is_used per group by walking the subtree once and
    # checking whether any descendant competence is in `used_ids`.
    direct_used: dict[uuid.UUID, bool] = {
        gid: any(c.id in used_ids for c in comps)
        for gid, comps in comp_by_group.items()
    }

    # recursive rollup of competences_count + is_used
    def rollup(node: CompetenceGroupTree) -> tuple[int, bool]:
        total = direct_count.get(node.id, 0)
        used = direct_used.get(node.id, False)
        for child in node.children:
            child_total, child_used = rollup(child)
            total += child_total
            used = used or child_used
        node.competences_count = total
        node.is_used = used
        return total, used

    for r in roots:
        rollup(r)

    return roots


async def create_group(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: CompetenceGroupCreate,
    *,
    actor_id: uuid.UUID | None = None,
) -> CompetenceGroup:
    parent: CompetenceGroup | None = None
    if data.parent_id:
        parent = await db.get(CompetenceGroup, data.parent_id)
        if not parent:
            raise AppError(
                "competence_invalid_parent_group", status.HTTP_400_BAD_REQUEST
            )

    group = CompetenceGroup(tenant_id=tenant_id, **data.model_dump())
    # Client groups can always be hidden by tenant admins (PM spec).
    group.can_deactivate = True
    # HRP-118: a child added under an inactive parent defaults to inactive so
    # we don't silently surface it to users — admins explicitly activate later.
    if parent is not None and not parent.is_active and group.is_active:
        group.is_active = False
    db.add(group)
    await db.flush()

    # If parent is inactive but new group is explicitly active → light up ancestors.
    if group.is_active and group.parent_id is not None and parent is not None and not parent.is_active:
        await cascade_activate_parents(db, parent, tenant_id)

    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence_group.create",
        element_type="group",
        element_id=group.id,
        payload={
            "title": group.title,
            "parent_id": str(group.parent_id) if group.parent_id else None,
        },
    )
    await db.commit()
    await db.refresh(group)
    return group


async def update_group(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    data: CompetenceGroupUpdate,
    *,
    actor_id: uuid.UUID | None = None,
) -> CompetenceGroup:
    group = await db.get(CompetenceGroup, group_id)
    if not group:
        raise AppError("competence_group_not_found", status.HTTP_404_NOT_FOUND)
    if group.tenant_id is None:
        raise AppError("origin_group_read_only", status.HTTP_403_FORBIDDEN)
    if group.tenant_id != tenant_id:
        raise AppError("competence_group_not_found", status.HTTP_404_NOT_FOUND)

    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(group, field, value)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence_group.update",
        element_type="group",
        element_id=group.id,
        payload=payload,
    )
    await db.commit()
    await db.refresh(group)
    return group


async def delete_group(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> None:
    group = await db.get(CompetenceGroup, group_id)
    if not group:
        raise AppError("competence_group_not_found", status.HTTP_404_NOT_FOUND)
    if group.tenant_id is None:
        raise AppError("origin_group_delete_forbidden", status.HTTP_403_FORBIDDEN)
    if group.tenant_id != tenant_id:
        raise AppError("competence_group_not_found", status.HTTP_404_NOT_FOUND)
    from app.modules.competence.usage import check_group_usage

    usage = await check_group_usage(db, group.id)
    if usage.is_used:
        raise AppError("competence_group_in_use", status.HTTP_409_CONFLICT)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence_group.delete",
        element_type="group",
        element_id=group.id,
        payload={"title": group.title},
    )
    await db.delete(group)
    await db.commit()


async def activate_group(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> CompetenceGroup:
    group = await _load_group_in_tenant(db, tenant_id, group_id)
    # HRP-118: activating a group cascades up to ancestors *and* down to every
    # descendant group so the whole branch becomes visible in one click.
    activated = await cascade_activate_group(db, group, tenant_id)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence_group.activate",
        element_type="group",
        element_id=group.id,
        payload={"activated_ids": [str(g.id) for g in activated]},
    )
    await db.commit()
    await db.refresh(group)
    return group


async def deactivate_group(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> CompetenceGroup:
    group = await _load_group_in_tenant(db, tenant_id, group_id)
    if group.tenant_id is None and not group.can_deactivate:
        raise AppError(
            "origin_group_not_deactivatable", status.HTTP_403_FORBIDDEN
        )
    deactivated = await cascade_deactivate_group(db, group, tenant_id)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence_group.deactivate",
        element_type="group",
        element_id=group.id,
        payload={"deactivated_ids": [str(g.id) for g in deactivated]},
    )
    await db.commit()
    await db.refresh(group)
    return group


async def move_group(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    new_parent_id: uuid.UUID | None,
    new_sort_index: int = 0,
    *,
    actor_id: uuid.UUID | None = None,
) -> CompetenceGroup:
    group = await _load_group_in_tenant(db, tenant_id, group_id)
    if group.tenant_id is None:
        raise AppError("origin_group_move_forbidden", status.HTTP_403_FORBIDDEN)
    if new_parent_id is not None:
        parent = await db.get(CompetenceGroup, new_parent_id)
        if parent is None:
            raise AppError(
                "competence_invalid_target_parent", status.HTTP_400_BAD_REQUEST
            )
        if parent.tenant_id is not None and parent.tenant_id != tenant_id:
            raise AppError(
                "competence_target_parent_not_found", status.HTTP_404_NOT_FOUND
            )

    await validate_no_cycles(db, group_id, new_parent_id)

    old_parent_id = group.parent_id
    group.parent_id = new_parent_id
    group.sort_index = new_sort_index
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence_group.move",
        element_type="group",
        element_id=group.id,
        payload={
            "old_parent_id": str(old_parent_id) if old_parent_id else None,
            "new_parent_id": str(new_parent_id) if new_parent_id else None,
            "sort_index": new_sort_index,
        },
    )
    await db.commit()
    await db.refresh(group)
    return group


async def set_group_can_deactivate(
    db: AsyncSession,
    group_id: uuid.UUID,
    can_deactivate: bool,
    *,
    actor_id: uuid.UUID | None = None,
) -> list[CompetenceGroup]:
    """Platform-admin only. Locking propagates upward (ancestors lock too);
    unlocking propagates downward (descendants unlock too). Returns the
    affected groups."""
    group = await db.get(CompetenceGroup, group_id)
    if not group:
        raise AppError("competence_group_not_found", status.HTTP_404_NOT_FOUND)
    if group.tenant_id is not None:
        raise AppError(
            "competence_group_lock_origin_only", status.HTTP_400_BAD_REQUEST
        )

    affected: list[CompetenceGroup] = []
    if can_deactivate is False:
        # Lock the group + walk up, locking ancestors.
        cur: CompetenceGroup | None = group
        while cur is not None:
            if cur.can_deactivate:
                cur.can_deactivate = False
                affected.append(cur)
            if cur.parent_id is None:
                break
            cur = await db.get(CompetenceGroup, cur.parent_id)
    else:
        # Unlock: this group + propagate down to descendants.
        stack: list[CompetenceGroup] = [group]
        visited: set[uuid.UUID] = set()
        while stack:
            node = stack.pop()
            if node.id in visited:
                continue
            visited.add(node.id)
            if not node.can_deactivate:
                node.can_deactivate = True
                affected.append(node)
            children_q = await db.execute(
                select(CompetenceGroup).where(
                    CompetenceGroup.parent_id == node.id,
                    CompetenceGroup.tenant_id.is_(None),
                )
            )
            for child in children_q.scalars().all():
                stack.append(child)

    await _audit(
        db,
        tenant_id=None,
        actor_id=actor_id,
        action="competence_group.set_can_deactivate",
        element_type="group",
        element_id=group.id,
        payload={
            "can_deactivate": can_deactivate,
            "affected_ids": [str(g.id) for g in affected],
        },
    )
    await db.commit()
    return affected


async def _load_group_in_tenant(
    db: AsyncSession, tenant_id: uuid.UUID, group_id: uuid.UUID
) -> CompetenceGroup:
    group = await db.get(CompetenceGroup, group_id)
    if not group:
        raise AppError("competence_group_not_found", status.HTTP_404_NOT_FOUND)
    if group.tenant_id is not None and group.tenant_id != tenant_id:
        raise AppError("competence_group_not_found", status.HTTP_404_NOT_FOUND)
    return group


# --- Competence ---


async def create_competence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: CompetenceCreate,
    *,
    actor_id: uuid.UUID | None = None,
) -> Competence:
    group = await db.get(CompetenceGroup, data.group_id)
    if not group:
        raise AppError("competence_invalid_group", status.HTTP_400_BAD_REQUEST)

    comp = Competence(tenant_id=tenant_id, **data.model_dump())
    # HRP-118: a competence added under an inactive group inherits that state
    # so it stays hidden until the admin explicitly publishes it.
    if not group.is_active:
        comp.is_active = False
    db.add(comp)
    await db.flush()
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence.create",
        element_type="competence",
        element_id=comp.id,
        payload={"title": comp.title, "group_id": str(comp.group_id)},
    )
    await db.commit()
    await db.refresh(comp)
    return comp


async def bulk_create_competences(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    data: CompetenceBulkCreate,
    *,
    actor_id: uuid.UUID | None = None,
) -> list[Competence]:
    """Create several competences inside a single group in one transaction.

    Used by the bulk-add UI on the competence tree (HRP-108): the user types
    a list of names once and we persist them all atomically — either every
    competence lands or none do.
    """
    group = await db.get(CompetenceGroup, group_id)
    if not group:
        raise AppError("competence_invalid_group", status.HTTP_400_BAD_REQUEST)
    if group.tenant_id is not None and group.tenant_id != tenant_id:
        raise AppError("competence_group_not_found", status.HTTP_404_NOT_FOUND)

    created: list[Competence] = []
    for item in data.items:
        comp = Competence(
            tenant_id=tenant_id,
            group_id=group_id,
            title=item.title,
            description=item.description,
            competence_type_id=item.competence_type_id,
        )
        # HRP-118: inherit the parent's hidden state — bulk-added rows in a
        # hidden group stay hidden until an admin publishes them.
        if not group.is_active:
            comp.is_active = False
        db.add(comp)
        created.append(comp)
    await db.flush()
    for comp in created:
        await _audit(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="competence.bulk_create",
            element_type="competence",
            element_id=comp.id,
            payload={"title": comp.title, "group_id": str(comp.group_id)},
        )
    # HRP-108: summary row on the group makes "12 competences bulk-added"
    # readable in the audit log without scanning 12 per-item entries.
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence.bulk_create",
        element_type="group",
        element_id=group_id,
        payload={"count": len(created)},
    )
    await db.commit()
    for comp in created:
        await db.refresh(comp)
    return created


async def get_competence_detail(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    *,
    skill_level_id: uuid.UUID | None = None,
) -> dict:
    """Return a competence with its indicators / materials.

    HRP-43: when ``skill_level_id`` is provided, indicators and materials are
    filtered to that level **and every level below it** (by ``sort_index``),
    matching the questionnaire rule "Basic-only assessment shows Basic
    indicators, Intermediate shows Basic + Intermediate, Advanced shows all".
    """
    comp = await db.get(Competence, competence_id)
    if not comp:
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)
    if comp.tenant_id is not None and comp.tenant_id != tenant_id:
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)

    allowed_level_ids: set[uuid.UUID] | None = None
    if skill_level_id is not None:
        target = await db.get(SkillLevel, skill_level_id)
        if target is None:
            raise AppError("skill_level_not_found", status.HTTP_404_NOT_FOUND)
        # Tenant-custom skill levels live alongside origin (tenant_id IS NULL);
        # both contribute to the cap so an Advanced custom level still includes
        # the Basic origin one.
        levels_q = await db.execute(
            select(SkillLevel.id).where(
                SkillLevel.is_active == True,  # noqa: E712
                or_(
                    SkillLevel.tenant_id == tenant_id,
                    SkillLevel.tenant_id.is_(None),
                ),
                SkillLevel.sort_index <= target.sort_index,
            )
        )
        allowed_level_ids = set(levels_q.scalars().all())

    ind_query = (
        select(Indicator)
        .where(Indicator.competence_id == competence_id)
        .order_by(Indicator.sort_index)
    )
    mat_query = (
        select(Material)
        .where(Material.competence_id == competence_id)
        .order_by(Material.sort_index)
    )
    if allowed_level_ids is not None:
        ind_query = ind_query.where(Indicator.skill_level_id.in_(allowed_level_ids))
        mat_query = mat_query.where(Material.skill_level_id.in_(allowed_level_ids))

    ind_result = await db.execute(ind_query)
    mat_result = await db.execute(mat_query)
    indicators = ind_result.scalars().all()
    materials = mat_result.scalars().all()

    usage = await check_competence_usage(db, comp.id)

    return {
        "id": comp.id,
        "title": comp.title,
        "description": comp.description,
        "group_id": comp.group_id,
        "competence_type_id": comp.competence_type_id,
        "tenant_id": comp.tenant_id,
        "is_active": comp.is_active,
        "is_published": comp.is_published,
        "is_used": usage.is_used,
        "usage": {
            "matrix": usage.matrix,
            "employee_card": usage.employee_card,
            "assessment": usage.assessment,
            "idp": usage.idp,
            "talent_market": usage.talent_market,
        },
        "created_at": comp.created_at,
        "indicators": [
            {
                "id": i.id,
                "title": i.title,
                "weight": i.weight,
                "sort_index": i.sort_index,
                "skill_level_id": i.skill_level_id,
                "skill_level_title": i.skill_level.title if i.skill_level else None,
                "competence_id": i.competence_id,
                "is_active": i.is_active,
                "tenant_id": i.tenant_id,
                "created_at": i.created_at,
            }
            for i in indicators
        ],
        "materials": [
            {
                "id": m.id,
                "title": m.title,
                "format": m.format,
                "link": m.link,
                "study_time": m.study_time,
                "comment": m.comment,
                "material_type": m.material_type,
                "sort_index": m.sort_index,
                "skill_level_id": m.skill_level_id,
                "skill_level_title": m.skill_level.title if m.skill_level else None,
                "competence_id": m.competence_id,
                "is_active": m.is_active,
                "tenant_id": m.tenant_id,
                "created_at": m.created_at,
            }
            for m in materials
        ],
    }


async def update_competence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    data: CompetenceUpdate,
    *,
    actor_id: uuid.UUID | None = None,
) -> Competence:
    comp = await _load_competence_for_edit(db, tenant_id, competence_id)
    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(comp, field, value)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence.update",
        element_type="competence",
        element_id=comp.id,
        payload=payload,
    )
    await db.commit()
    await db.refresh(comp)
    return comp


async def delete_competence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> None:
    comp = await _load_competence_for_edit(db, tenant_id, competence_id)
    await ensure_competence_can_delete(db, comp)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence.delete",
        element_type="competence",
        element_id=comp.id,
        payload={"title": comp.title},
    )
    await db.delete(comp)
    await db.commit()


async def activate_competence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> Competence:
    comp = await _load_competence_in_tenant(db, tenant_id, competence_id)
    if not comp.is_active:
        comp.is_active = True
    if comp.group_id is not None:
        parent = await db.get(CompetenceGroup, comp.group_id)
        if parent is not None and not parent.is_active:
            await cascade_activate_parents(db, parent, tenant_id)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence.activate",
        element_type="competence",
        element_id=comp.id,
        payload=None,
    )
    await db.commit()
    await db.refresh(comp)
    return comp


async def deactivate_competence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> Competence:
    comp = await _load_competence_in_tenant(db, tenant_id, competence_id)
    await ensure_competence_can_deactivate(db, comp)
    comp.is_active = False
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence.deactivate",
        element_type="competence",
        element_id=comp.id,
        payload=None,
    )
    await db.commit()
    await db.refresh(comp)
    return comp


async def publish_competence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> Competence:
    """Mark a client competence as published. Per PDF, also activates it
    and walks up activating ancestor groups; origin competences cannot be
    published (they don't have a publish state)."""
    comp = await _load_competence_for_edit(db, tenant_id, competence_id)
    comp.is_published = True
    if not comp.is_active:
        comp.is_active = True
    parent = await db.get(CompetenceGroup, comp.group_id)
    if parent is not None and not parent.is_active:
        await cascade_activate_parents(db, parent, tenant_id)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence.publish",
        element_type="competence",
        element_id=comp.id,
        payload=None,
    )
    await db.commit()
    await db.refresh(comp)
    return comp


async def unpublish_competence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> Competence:
    comp = await _load_competence_for_edit(db, tenant_id, competence_id)
    if not comp.is_published:
        return comp
    await ensure_competence_can_unpublish(db, comp)
    comp.is_published = False
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence.unpublish",
        element_type="competence",
        element_id=comp.id,
        payload=None,
    )
    await db.commit()
    await db.refresh(comp)
    return comp


async def move_competence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    new_group_id: uuid.UUID,
    new_sort_index: int = 0,
    *,
    actor_id: uuid.UUID | None = None,
) -> Competence:
    comp = await _load_competence_for_edit(db, tenant_id, competence_id)
    target_group = await db.get(CompetenceGroup, new_group_id)
    if target_group is None:
        raise AppError("competence_invalid_target_group", status.HTTP_400_BAD_REQUEST)
    if target_group.tenant_id is not None and target_group.tenant_id != tenant_id:
        raise AppError("competence_target_group_not_found", status.HTTP_404_NOT_FOUND)

    old_group_id = comp.group_id
    comp.group_id = new_group_id
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="competence.move",
        element_type="competence",
        element_id=comp.id,
        payload={
            "old_group_id": str(old_group_id),
            "new_group_id": str(new_group_id),
            "sort_index": new_sort_index,
        },
    )
    await db.commit()
    await db.refresh(comp)
    return comp


async def _load_competence_in_tenant(
    db: AsyncSession, tenant_id: uuid.UUID, competence_id: uuid.UUID
) -> Competence:
    comp = await db.get(Competence, competence_id)
    if not comp:
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)
    if comp.tenant_id is not None and comp.tenant_id != tenant_id:
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)
    return comp


async def _load_competence_for_edit(
    db: AsyncSession, tenant_id: uuid.UUID, competence_id: uuid.UUID
) -> Competence:
    comp = await db.get(Competence, competence_id)
    if not comp:
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)
    if comp.tenant_id is None:
        raise AppError("origin_competence_read_only", status.HTTP_403_FORBIDDEN)
    if comp.tenant_id != tenant_id:
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)
    return comp


# --- SkillLevel ---


async def list_skill_levels(
    db: AsyncSession, tenant_id: uuid.UUID | None = None
) -> list[SkillLevel]:
    if tenant_id is None:
        result = await db.execute(select(SkillLevel).order_by(SkillLevel.sort_index))
    else:
        result = await db.execute(
            select(SkillLevel)
            .where(
                or_(
                    SkillLevel.tenant_id == tenant_id,
                    SkillLevel.tenant_id.is_(None),
                )
            )
            .order_by(SkillLevel.sort_index)
        )
    return list(result.scalars().all())


async def create_skill_level(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    title: str,
    sort_index: int = 0,
    i18n_key: str | None = None,
    *,
    actor_id: uuid.UUID | None = None,
) -> SkillLevel:
    level = SkillLevel(
        title=title,
        sort_index=sort_index,
        i18n_key=i18n_key,
        tenant_id=tenant_id,
    )
    db.add(level)
    await db.flush()
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="skill_level.create",
        element_type="skill_level",
        element_id=level.id,
        payload={"title": title},
    )
    await db.commit()
    await db.refresh(level)
    return level


async def update_skill_level(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    skill_level_id: uuid.UUID,
    *,
    title: str | None = None,
    sort_index: int | None = None,
    i18n_key: str | None = None,
    is_active: bool | None = None,
    actor_id: uuid.UUID | None = None,
) -> SkillLevel:
    level = await db.get(SkillLevel, skill_level_id)
    if not level:
        raise AppError("skill_level_not_found", status.HTTP_404_NOT_FOUND)
    if level.tenant_id is None:
        raise AppError("origin_skill_level_read_only", status.HTTP_403_FORBIDDEN)
    if level.tenant_id != tenant_id:
        raise AppError("skill_level_not_found", status.HTTP_404_NOT_FOUND)

    payload: dict = {}
    if title is not None:
        level.title = title
        payload["title"] = title
    if sort_index is not None:
        level.sort_index = sort_index
        payload["sort_index"] = sort_index
    if i18n_key is not None:
        level.i18n_key = i18n_key
        payload["i18n_key"] = i18n_key
    if is_active is not None:
        level.is_active = is_active
        payload["is_active"] = is_active

    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="skill_level.update",
        element_type="skill_level",
        element_id=level.id,
        payload=payload,
    )
    await db.commit()
    await db.refresh(level)
    return level


async def delete_skill_level(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    skill_level_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> None:
    level = await db.get(SkillLevel, skill_level_id)
    if not level:
        raise AppError("skill_level_not_found", status.HTTP_404_NOT_FOUND)
    if level.tenant_id is None:
        raise AppError(
            "origin_skill_level_delete_forbidden", status.HTTP_403_FORBIDDEN
        )
    if level.tenant_id != tenant_id:
        raise AppError("skill_level_not_found", status.HTTP_404_NOT_FOUND)
    if await check_skill_level_usage(db, level.id):
        raise AppError("skill_level_in_use", status.HTTP_409_CONFLICT)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="skill_level.delete",
        element_type="skill_level",
        element_id=level.id,
        payload={"title": level.title},
    )
    await db.delete(level)
    await db.commit()


# --- Indicator ---


async def create_indicator(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    data: IndicatorCreate,
    *,
    actor_id: uuid.UUID | None = None,
) -> Indicator:
    comp = await db.get(Competence, competence_id)
    if not comp:
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)

    ind = Indicator(
        competence_id=competence_id, tenant_id=tenant_id, **data.model_dump()
    )
    db.add(ind)
    await db.flush()
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="indicator.create",
        element_type="indicator",
        element_id=ind.id,
        payload={"competence_id": str(competence_id)},
    )
    await db.commit()
    await db.refresh(ind)
    return ind


async def create_indicators_bulk(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    items: list[IndicatorCreate],
    *,
    actor_id: uuid.UUID | None = None,
) -> list[Indicator]:
    """HRP-49: transactional bulk insert for indicators.

    Validates the competence and every ``skill_level_id`` against the
    caller's tenant in one pass before any INSERT, then commits the
    whole batch in a single transaction. Mirrors the bulk-materials
    safety guarantees added in HRP-51 review.
    """
    if not items:
        return []

    comp = await db.get(Competence, competence_id)
    if comp is None or (
        comp.tenant_id is not None and comp.tenant_id != tenant_id
    ):
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)

    requested_levels = {row.skill_level_id for row in items}
    level_q = await db.execute(
        select(SkillLevel.id, SkillLevel.tenant_id).where(
            SkillLevel.id.in_(requested_levels)
        )
    )
    allowed_levels: set[uuid.UUID] = set()
    for level_id, level_tenant_id in level_q.all():
        if level_tenant_id is None or level_tenant_id == tenant_id:
            allowed_levels.add(level_id)
    if requested_levels - allowed_levels:
        raise AppError("skill_level_not_in_tenant", status.HTTP_404_NOT_FOUND)

    created: list[Indicator] = []
    for data in items:
        ind = Indicator(
            competence_id=competence_id,
            tenant_id=tenant_id,
            **data.model_dump(),
        )
        db.add(ind)
        created.append(ind)
    await db.flush()
    for ind in created:
        await _audit(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="indicator.create",
            element_type="indicator",
            element_id=ind.id,
            payload={"competence_id": str(competence_id), "bulk": True},
        )
    await db.commit()
    for ind in created:
        await db.refresh(ind)
    return created


async def update_indicator(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    indicator_id: uuid.UUID,
    data: IndicatorUpdate,
    *,
    actor_id: uuid.UUID | None = None,
) -> Indicator:
    ind = await _load_indicator_for_edit(db, tenant_id, indicator_id)
    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(ind, field, value)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="indicator.update",
        element_type="indicator",
        element_id=ind.id,
        payload=payload,
    )
    await db.commit()
    await db.refresh(ind)
    return ind


async def delete_indicator(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    indicator_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> None:
    ind = await _load_indicator_for_edit(db, tenant_id, indicator_id)
    await ensure_indicator_can_mutate(db, ind)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="indicator.delete",
        element_type="indicator",
        element_id=ind.id,
        payload=None,
    )
    await db.delete(ind)
    await db.commit()


async def activate_indicator(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    indicator_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> Indicator:
    ind = await _load_indicator_in_tenant(db, tenant_id, indicator_id)
    await ensure_indicator_can_mutate(db, ind)
    ind.is_active = True
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="indicator.activate",
        element_type="indicator",
        element_id=ind.id,
        payload=None,
    )
    await db.commit()
    await db.refresh(ind)
    return ind


async def deactivate_indicator(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    indicator_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> Indicator:
    ind = await _load_indicator_in_tenant(db, tenant_id, indicator_id)
    await ensure_indicator_can_mutate(db, ind)
    ind.is_active = False
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="indicator.deactivate",
        element_type="indicator",
        element_id=ind.id,
        payload=None,
    )
    await db.commit()
    await db.refresh(ind)
    return ind


async def move_indicator(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    indicator_id: uuid.UUID,
    new_skill_level_id: uuid.UUID,
    new_sort_index: int = 0,
    *,
    actor_id: uuid.UUID | None = None,
) -> Indicator:
    ind = await _load_indicator_in_tenant(db, tenant_id, indicator_id)
    await ensure_indicator_can_mutate(db, ind)
    level = await db.get(SkillLevel, new_skill_level_id)
    if level is None:
        raise AppError("skill_level_invalid", status.HTTP_400_BAD_REQUEST)
    if level.tenant_id is not None and level.tenant_id != tenant_id:
        raise AppError("skill_level_not_found", status.HTTP_404_NOT_FOUND)
    ind.skill_level_id = new_skill_level_id
    ind.sort_index = new_sort_index
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="indicator.move",
        element_type="indicator",
        element_id=ind.id,
        payload={
            "skill_level_id": str(new_skill_level_id),
            "sort_index": new_sort_index,
        },
    )
    await db.commit()
    await db.refresh(ind)
    return ind


async def _load_indicator_in_tenant(
    db: AsyncSession, tenant_id: uuid.UUID, indicator_id: uuid.UUID
) -> Indicator:
    ind = await db.get(Indicator, indicator_id)
    if not ind:
        raise AppError("indicator_not_found", status.HTTP_404_NOT_FOUND)
    if ind.tenant_id is not None and ind.tenant_id != tenant_id:
        raise AppError("indicator_not_found", status.HTTP_404_NOT_FOUND)
    return ind


async def _load_indicator_for_edit(
    db: AsyncSession, tenant_id: uuid.UUID, indicator_id: uuid.UUID
) -> Indicator:
    ind = await db.get(Indicator, indicator_id)
    if not ind:
        raise AppError("indicator_not_found", status.HTTP_404_NOT_FOUND)
    if ind.tenant_id is None:
        raise AppError("origin_indicator_read_only", status.HTTP_403_FORBIDDEN)
    if ind.tenant_id != tenant_id:
        raise AppError("indicator_not_found", status.HTTP_404_NOT_FOUND)
    return ind


# --- Material ---


async def create_material(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    data: MaterialCreate,
    *,
    actor_id: uuid.UUID | None = None,
) -> Material:
    comp = await db.get(Competence, competence_id)
    if not comp:
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)

    mat = Material(
        competence_id=competence_id, tenant_id=tenant_id, **data.model_dump()
    )
    db.add(mat)
    await db.flush()
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="material.create",
        element_type="material",
        element_id=mat.id,
        payload={"competence_id": str(competence_id)},
    )
    await db.commit()
    await db.refresh(mat)
    return mat


async def create_materials_bulk(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    items: list[MaterialCreate],
    *,
    actor_id: uuid.UUID | None = None,
) -> list[Material]:
    """HRP-51: transactional bulk insert with tenant-scoped validation.

    Validates that the competence and every ``skill_level_id`` belong to
    the caller's tenant (or are origin rows shared with the tenant)
    before any INSERT runs, then commits the whole batch in one go so a
    failure halfway through does not leave half-saved materials.
    """
    if not items:
        return []

    comp = await db.get(Competence, competence_id)
    if comp is None or (
        comp.tenant_id is not None and comp.tenant_id != tenant_id
    ):
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)

    requested_levels = {row.skill_level_id for row in items}
    level_q = await db.execute(
        select(SkillLevel.id, SkillLevel.tenant_id).where(
            SkillLevel.id.in_(requested_levels)
        )
    )
    allowed_levels: set[uuid.UUID] = set()
    for level_id, level_tenant_id in level_q.all():
        if level_tenant_id is None or level_tenant_id == tenant_id:
            allowed_levels.add(level_id)
    missing = requested_levels - allowed_levels
    if missing:
        raise AppError("skill_level_not_in_tenant", status.HTTP_404_NOT_FOUND)

    created: list[Material] = []
    for data in items:
        mat = Material(
            competence_id=competence_id,
            tenant_id=tenant_id,
            **data.model_dump(),
        )
        db.add(mat)
        created.append(mat)
    await db.flush()
    for mat in created:
        await _audit(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="material.create",
            element_type="material",
            element_id=mat.id,
            payload={"competence_id": str(competence_id), "bulk": True},
        )
    await db.commit()
    for mat in created:
        await db.refresh(mat)
    return created


async def update_material(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    material_id: uuid.UUID,
    data: MaterialUpdate,
    *,
    actor_id: uuid.UUID | None = None,
) -> Material:
    mat = await _load_material_for_edit(db, tenant_id, material_id)
    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(mat, field, value)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="material.update",
        element_type="material",
        element_id=mat.id,
        payload=payload,
    )
    await db.commit()
    await db.refresh(mat)
    return mat


async def delete_material(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    material_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> None:
    mat = await _load_material_for_edit(db, tenant_id, material_id)
    await ensure_material_can_mutate(db, mat)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="material.delete",
        element_type="material",
        element_id=mat.id,
        payload=None,
    )
    await db.delete(mat)
    await db.commit()


async def activate_material(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    material_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> Material:
    mat = await _load_material_in_tenant(db, tenant_id, material_id)
    await ensure_material_can_mutate(db, mat)
    mat.is_active = True
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="material.activate",
        element_type="material",
        element_id=mat.id,
        payload=None,
    )
    await db.commit()
    await db.refresh(mat)
    return mat


async def deactivate_material(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    material_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> Material:
    mat = await _load_material_in_tenant(db, tenant_id, material_id)
    await ensure_material_can_mutate(db, mat)
    mat.is_active = False
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="material.deactivate",
        element_type="material",
        element_id=mat.id,
        payload=None,
    )
    await db.commit()
    await db.refresh(mat)
    return mat


async def move_material(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    material_id: uuid.UUID,
    new_skill_level_id: uuid.UUID,
    new_sort_index: int = 0,
    *,
    actor_id: uuid.UUID | None = None,
) -> Material:
    mat = await _load_material_in_tenant(db, tenant_id, material_id)
    await ensure_material_can_mutate(db, mat)
    level = await db.get(SkillLevel, new_skill_level_id)
    if level is None:
        raise AppError("skill_level_invalid", status.HTTP_400_BAD_REQUEST)
    if level.tenant_id is not None and level.tenant_id != tenant_id:
        raise AppError("skill_level_not_found", status.HTTP_404_NOT_FOUND)
    mat.skill_level_id = new_skill_level_id
    mat.sort_index = new_sort_index
    await _audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="material.move",
        element_type="material",
        element_id=mat.id,
        payload={
            "skill_level_id": str(new_skill_level_id),
            "sort_index": new_sort_index,
        },
    )
    await db.commit()
    await db.refresh(mat)
    return mat


async def _load_material_in_tenant(
    db: AsyncSession, tenant_id: uuid.UUID, material_id: uuid.UUID
) -> Material:
    mat = await db.get(Material, material_id)
    if not mat:
        raise AppError("material_not_found", status.HTTP_404_NOT_FOUND)
    if mat.tenant_id is not None and mat.tenant_id != tenant_id:
        raise AppError("material_not_found", status.HTTP_404_NOT_FOUND)
    return mat


async def _load_material_for_edit(
    db: AsyncSession, tenant_id: uuid.UUID, material_id: uuid.UUID
) -> Material:
    mat = await db.get(Material, material_id)
    if not mat:
        raise AppError("material_not_found", status.HTTP_404_NOT_FOUND)
    if mat.tenant_id is None:
        raise AppError("origin_material_read_only", status.HTTP_403_FORBIDDEN)
    if mat.tenant_id != tenant_id:
        raise AppError("material_not_found", status.HTTP_404_NOT_FOUND)
    return mat
