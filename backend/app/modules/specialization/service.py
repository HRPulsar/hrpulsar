"""Specialization service — proxy on `DictionaryItem(type='specialization')`.

The Specialization domain has its own contract — list / detail / grades /
positions / matrix — but is still backed by the unified `DictionaryItem`
table so existing FKs from `Position` and `GradeSpecialization` keep
working without a data migration. CRUD on the dictionary entry itself
remains in the dictionary module.
"""

from __future__ import annotations

import uuid

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.modules.competence.models import Competence, Indicator, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.dictionary.service import origin_active_overrides
from app.modules.employee.models import Employee
from app.modules.grade_system.models import GradeCompetenceLink, GradeSpecialization
from app.modules.position.models import Position

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_PASSING_SCORE = 75

# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


async def _get_specialization(
    db: AsyncSession, tenant_id: uuid.UUID, spec_id: uuid.UUID
) -> DictionaryItem:
    item = await db.get(DictionaryItem, spec_id)
    if (
        item is None
        or item.type != "specialization"
        or (item.tenant_id is not None and item.tenant_id != tenant_id)
    ):
        raise AppError("specialization_not_found", status.HTTP_404_NOT_FOUND)
    return item


async def _get_grade_spec_pair(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    spec_id: uuid.UUID,
    grade_id: uuid.UUID,
) -> GradeSpecialization:
    result = await db.execute(
        select(GradeSpecialization).where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == spec_id,
            GradeSpecialization.grade_id == grade_id,
        )
    )
    pair = result.scalar_one_or_none()
    if pair is None:
        raise AppError("spec_grade_pair_not_found", status.HTTP_404_NOT_FOUND)
    return pair


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


async def list_specializations(db: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    """Tenant-visible specializations + headcount/occupancy roll-ups."""
    items_q = await db.execute(
        select(DictionaryItem)
        .where(
            DictionaryItem.type == "specialization",
            (DictionaryItem.tenant_id == tenant_id)
            | (DictionaryItem.tenant_id.is_(None)),
        )
        .order_by(DictionaryItem.sort_index, DictionaryItem.title)
    )
    items = items_q.scalars().all()
    if not items:
        return []
    spec_ids = [i.id for i in items]

    grade_counts_q = await db.execute(
        select(
            GradeSpecialization.specialization_id, func.count(GradeSpecialization.id)
        )
        .where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id.in_(spec_ids),
        )
        .group_by(GradeSpecialization.specialization_id)
    )
    grade_counts = {row[0]: row[1] for row in grade_counts_q.all()}

    pos_q = await db.execute(
        select(
            Position.specialization_id,
            func.count(Position.id),
            func.coalesce(func.sum(Position.headcount), 0),
        )
        .where(
            Position.tenant_id == tenant_id,
            Position.specialization_id.in_(spec_ids),
        )
        .group_by(Position.specialization_id)
    )
    pos_stats = {
        row[0]: {"position_count": row[1], "headcount_total": int(row[2] or 0)}
        for row in pos_q.all()
    }

    assigned_q = await db.execute(
        select(Position.specialization_id, func.count(Employee.id))
        .join(Employee, Employee.position_id == Position.id)
        .where(
            Position.tenant_id == tenant_id,
            Position.specialization_id.in_(spec_ids),
            Employee.tenant_id == tenant_id,
            Employee.status == "active",
        )
        .group_by(Position.specialization_id)
    )
    assigned_stats = {row[0]: row[1] for row in assigned_q.all()}

    # HRP-337: surface the tenant-effective flag for System items so the
    # Specializations page agrees with Dictionaries about what's Inactive.
    active_overrides = await origin_active_overrides(
        db, tenant_id, [i.id for i in items if i.tenant_id is None]
    )

    result: list[dict] = []
    for item in items:
        ps = pos_stats.get(item.id, {"position_count": 0, "headcount_total": 0})
        result.append(
            {
                "id": item.id,
                "title": item.title,
                "description": item.description,
                "is_active": active_overrides.get(item.id, item.is_active),
                "grade_count": grade_counts.get(item.id, 0),
                "position_count": ps["position_count"],
                "assigned_count": assigned_stats.get(item.id, 0),
                "headcount_total": ps["headcount_total"],
                "created_at": item.created_at,
            }
        )
    return result


async def get_specialization_detail(
    db: AsyncSession, tenant_id: uuid.UUID, spec_id: uuid.UUID
) -> dict:
    spec = await _get_specialization(db, tenant_id, spec_id)
    grades = await get_grades_with_attrs(db, tenant_id, spec_id)
    pos_q = await db.execute(
        select(
            func.count(Position.id),
            func.coalesce(func.sum(Position.headcount), 0),
        ).where(
            Position.tenant_id == tenant_id,
            Position.specialization_id == spec_id,
        )
    )
    pos_count, headcount_total = pos_q.one()
    assigned_q = await db.execute(
        select(func.count(Employee.id))
        .join(Position, Employee.position_id == Position.id)
        .where(
            Position.tenant_id == tenant_id,
            Position.specialization_id == spec_id,
            Employee.tenant_id == tenant_id,
            Employee.status == "active",
        )
    )
    assigned = assigned_q.scalar() or 0
    # HRP-337: same tenant-effective flag as the list view.
    detail_overrides = (
        await origin_active_overrides(db, tenant_id, [spec.id])
        if spec.tenant_id is None
        else {}
    )
    return {
        "id": spec.id,
        "title": spec.title,
        "description": spec.description,
        "is_active": detail_overrides.get(spec.id, spec.is_active),
        "grade_count": len(grades),
        "position_count": int(pos_count or 0),
        "assigned_count": assigned,
        "headcount_total": int(headcount_total or 0),
        "created_at": spec.created_at,
        "grades": grades,
    }


async def get_grades_with_attrs(
    db: AsyncSession, tenant_id: uuid.UUID, spec_id: uuid.UUID
) -> list[dict]:
    await _get_specialization(db, tenant_id, spec_id)
    q = await db.execute(
        select(GradeSpecialization)
        .options(selectinload(GradeSpecialization.competence_links))
        .where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == spec_id,
        )
        .order_by(GradeSpecialization.sort_index)
    )
    rows = q.scalars().all()

    # HRP-288: resolve the effective ``is_active`` per grade so the spec
    # detail page can render the Inactive chip. For tenants this is the
    # custom row's own flag or the origin row overridden by
    # ``dictionary_item_tenant_overrides`` (HRP-285).
    grade_ids = [gs.grade_id for gs in rows if gs.grade_id is not None]
    overrides = await origin_active_overrides(db, tenant_id, grade_ids)

    def _effective_active(gs: GradeSpecialization) -> bool:
        if gs.grade is None:
            return True
        if gs.grade.tenant_id is None and gs.grade_id in overrides:
            return overrides[gs.grade_id]
        return gs.grade.is_active

    return [
        {
            "id": gs.id,
            "grade_id": gs.grade_id,
            "grade_title": gs.grade.title if gs.grade else "",
            # HRP-479: origin grades localize via reference.dictionary.grade.*.
            "grade_i18n_key": gs.grade.i18n_key if gs.grade else None,
            "description": gs.description,
            "requirements": gs.requirements,
            "salary_min": gs.salary_min,
            "salary_max": gs.salary_max,
            "salary_currency": gs.salary_currency,
            "passing_score": gs.passing_score,
            "sort_index": gs.sort_index,
            "matrix_status": "configured" if gs.competence_links else "empty",
            "competence_count": len(gs.competence_links),
            "grade_is_active": _effective_active(gs),
        }
        for gs in rows
    ]


async def get_positions_summary(
    db: AsyncSession, tenant_id: uuid.UUID, spec_id: uuid.UUID
) -> list[dict]:
    """Positions for a specialization, grouped by division."""
    await _get_specialization(db, tenant_id, spec_id)
    q = await db.execute(
        select(Position)
        .where(
            Position.tenant_id == tenant_id,
            Position.specialization_id == spec_id,
        )
        .order_by(Position.title)
    )
    positions = q.scalars().all()
    if not positions:
        return []

    counts_q = await db.execute(
        select(Employee.position_id, func.count(Employee.id))
        .where(
            Employee.tenant_id == tenant_id,
            Employee.position_id.in_([p.id for p in positions]),
            Employee.status == "active",
        )
        .group_by(Employee.position_id)
    )
    counts = {row[0]: row[1] for row in counts_q.all()}

    grouped: dict[uuid.UUID | None, dict] = {}
    for pos in positions:
        key = pos.division_id
        if key not in grouped:
            grouped[key] = {
                "division_id": key,
                "division_name": pos.division.name if pos.division else None,
                "positions": [],
            }
        assigned = counts.get(pos.id, 0)
        headcount = pos.headcount or 0
        grouped[key]["positions"].append(
            {
                "id": pos.id,
                "title": pos.title,
                "grade_id": pos.grade_id,
                "grade_title": pos.grade.title if pos.grade else None,
                "headcount": pos.headcount,
                "assigned": assigned,
                "vacant": max(0, headcount - assigned) if pos.headcount else 0,
                "lifecycle_status": pos.lifecycle_status,
            }
        )

    # Stable order: divisions with assigned name first, NULL last.
    return sorted(
        grouped.values(),
        key=lambda b: (
            b["division_name"] is None,
            (b["division_name"] or "").lower(),
        ),
    )


async def list_employees(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    spec_id: uuid.UUID,
    *,
    with_alerts: bool = False,
) -> list[dict]:
    """HRP-57 §3.1: employees in any Position of this specialization.

    Reuses the unified employee row shape (see `PositionEmployeeRead`) so the
    Specialization detail tab can render the same component as the Position
    detail page and the headcount drill-down.
    """
    from app.modules.employee.alerts import (
        ALERT_LABELS,
        AlertCode,
        compute_employee_alerts_bulk,
    )
    from app.modules.employee.service import _resolve_emp_avatars_bulk

    await _get_specialization(db, tenant_id, spec_id)

    rows = (
        (
            await db.execute(
                select(Employee)
                .join(Position, Position.id == Employee.position_id)
                .where(
                    Employee.tenant_id == tenant_id,
                    Position.specialization_id == spec_id,
                )
                .options(
                    selectinload(Employee.user),
                    selectinload(Employee.division),
                    selectinload(Employee.position).options(
                        selectinload(Position.specialization),
                        selectinload(Position.grade),
                    ),
                )
                .order_by(Employee.hire_date.desc())
            )
        )
        .scalars()
        .all()
    )
    employees = list(rows)

    alerts_map: dict[uuid.UUID, AlertCode | None] = {}
    if with_alerts:
        alerts_map = await compute_employee_alerts_bulk(db, tenant_id, employees)

    avatars = await _resolve_emp_avatars_bulk(db, employees)

    items: list[dict] = []
    for emp in employees:
        pos = emp.position
        avatar_url = avatars.get(emp.id)
        alert_code = alerts_map.get(emp.id)
        items.append(
            {
                "id": emp.id,
                "user_id": emp.user_id,
                "user_name": (
                    f"{emp.user.first_name} {emp.user.last_name}" if emp.user else None
                ),
                "user_email": emp.user.email if emp.user else None,
                "position_title": pos.title if pos else emp.position_title,
                "specialization_title": (
                    pos.specialization.title if pos and pos.specialization else None
                ),
                "grade_title": pos.grade.title if pos and pos.grade else None,
                # HRP-175: division_id keeps the Division cell clickable in
                # the unified EmployeeList.
                "division_id": emp.division_id,
                "division_name": emp.division.name if emp.division else None,
                "hire_date": emp.hire_date,
                "status": emp.status,
                "avatar_url": avatar_url,
                "alert": (
                    {"code": alert_code, "label": ALERT_LABELS[alert_code]}
                    if alert_code
                    else None
                ),
            }
        )
    return items


async def get_matrix(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    spec_id: uuid.UUID,
    grade_id: uuid.UUID,
) -> list[dict]:
    pair = await _get_grade_spec_pair(db, tenant_id, spec_id, grade_id)
    q = await db.execute(
        select(GradeCompetenceLink)
        .options(
            selectinload(GradeCompetenceLink.competence),
            selectinload(GradeCompetenceLink.skill_level),
        )
        .where(GradeCompetenceLink.grade_specialization_id == pair.id)
    )
    return [
        {
            "competence_id": link.competence_id,
            "competence_title": link.competence.title if link.competence else None,
            "skill_level_id": link.skill_level_id,
            "skill_level_title": (link.skill_level.title if link.skill_level else None),
        }
        for link in q.scalars().all()
    ]


# ---------------------------------------------------------------------------
# Bulk read
# ---------------------------------------------------------------------------


async def get_matrix_bulk(
    db: AsyncSession, tenant_id: uuid.UUID, spec_id: uuid.UUID
) -> dict:
    """Full matrix across all grades of one spec, ordered by grade.sort_index."""
    await _get_specialization(db, tenant_id, spec_id)
    pairs_q = await db.execute(
        select(GradeSpecialization)
        .options(
            selectinload(GradeSpecialization.competence_links).options(
                selectinload(GradeCompetenceLink.competence),
                selectinload(GradeCompetenceLink.skill_level),
            )
        )
        .where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == spec_id,
        )
    )
    pairs = list(pairs_q.scalars().all())
    # HRP-57 P3: matrix columns follow the pair's own sort_index, not the
    # DictionaryItem's. The Specialization page exposes drag-and-drop and
    # inline edits that mutate the pair; the dictionary's order is a
    # tenant-global hint used elsewhere (selects, filters) and would
    # override any per-spec reorder if it stayed authoritative here.
    pairs.sort(
        key=lambda p: (
            p.sort_index,
            (p.grade.title if p.grade else "").lower(),
        )
    )
    return {
        "grades": [
            {
                "grade_id": p.grade_id,
                "grade_title": p.grade.title if p.grade else None,
                "grade_sort_index": p.sort_index,
                "links": [
                    {
                        "competence_id": link.competence_id,
                        "competence_title": (
                            link.competence.title if link.competence else None
                        ),
                        "skill_level_id": link.skill_level_id,
                        "skill_level_title": (
                            link.skill_level.title if link.skill_level else None
                        ),
                    }
                    for link in p.competence_links
                ],
            }
            for p in pairs
        ]
    }


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def _validate_visible_competences_levels(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_ids: set[uuid.UUID],
    level_ids: set[uuid.UUID],
) -> None:
    if competence_ids:
        comps_q = await db.execute(
            select(Competence.id).where(
                Competence.id.in_(competence_ids),
                (Competence.tenant_id == tenant_id) | (Competence.tenant_id.is_(None)),
            )
        )
        valid = {row[0] for row in comps_q.all()}
        if len(valid) != len(competence_ids):
            raise AppError(
                "spec_competences_not_visible",
                status.HTTP_400_BAD_REQUEST,
            )
    if level_ids:
        levels_q = await db.execute(
            select(SkillLevel.id).where(
                SkillLevel.id.in_(level_ids),
                (SkillLevel.tenant_id == tenant_id) | (SkillLevel.tenant_id.is_(None)),
            )
        )
        valid = {row[0] for row in levels_q.all()}
        if len(valid) != len(level_ids):
            raise AppError(
                "spec_skill_levels_not_visible",
                status.HTTP_400_BAD_REQUEST,
            )


def _normalize_cascade(
    grade_order: list[uuid.UUID],
    state: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]],
    level_sort: dict[uuid.UUID, int],
) -> dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]]:
    """Normalize matrix so that for every competence, level is monotonically
    non-decreasing along ``grade_order`` (grades sorted ASC by sort_index).

    Strategy: running-max upgrade — if a higher grade has a lower level than
    a lower grade (or no link at all), bump it up. Mirrors the client cascade
    rule "promotion propagates up". Lowering the bar on a higher grade is
    impossible without lowering all lower grades too, which the client does
    explicitly; the server, on a direct API call, stays on the safe side.
    """
    competences: set[uuid.UUID] = set()
    for grade_links in state.values():
        competences.update(grade_links.keys())

    out: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]] = {
        gid: dict(state.get(gid, {})) for gid in grade_order
    }

    for comp_id in competences:
        running_level: uuid.UUID | None = None
        running_sort: int = -1
        for gid in grade_order:
            current_level = out[gid].get(comp_id)
            if current_level is None:
                if running_level is not None:
                    out[gid][comp_id] = running_level
                continue
            current_sort = level_sort.get(current_level, 0)
            if running_level is not None and current_sort < running_sort:
                out[gid][comp_id] = running_level
            else:
                running_level = current_level
                running_sort = current_sort
    return out


async def _apply_matrix_state(
    db: AsyncSession,
    pairs_by_grade: dict[uuid.UUID, GradeSpecialization],
    desired: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]],
    current: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]],
) -> None:
    """Diff-and-apply: for each (grade_id, competence_id), insert/update/delete
    so that DB matches ``desired``. Skips no-op pairs to keep audit clean.

    HRP-99: mutate ``pair.competence_links`` directly (append / remove on the
    Python collection) so the back-populated relationship stays in sync after
    each diff. With ``expire_on_commit=False`` on the session, plain
    ``db.add``/``db.delete`` would leave ``pair.competence_links`` holding the
    pre-save snapshot, and the follow-up ``get_matrix_bulk(...)`` reading the
    same identity-mapped pair returned an empty / stale matrix to the client.
    """
    for grade_id, want in desired.items():
        have = current.get(grade_id, {})
        pair = pairs_by_grade[grade_id]
        links_by_comp = {link.competence_id: link for link in pair.competence_links}

        for comp_id, level_id in want.items():
            if have.get(comp_id) == level_id:
                continue
            existing = links_by_comp.get(comp_id)
            if existing is None:
                pair.competence_links.append(
                    GradeCompetenceLink(
                        competence_id=comp_id,
                        skill_level_id=level_id,
                    )
                )
            else:
                existing.skill_level_id = level_id

        for comp_id in have.keys() - want.keys():
            existing = links_by_comp.get(comp_id)
            if existing is not None:
                pair.competence_links.remove(existing)

    await db.flush()


async def _load_pairs_in_order(
    db: AsyncSession, tenant_id: uuid.UUID, spec_id: uuid.UUID
) -> list[GradeSpecialization]:
    pairs_q = await db.execute(
        select(GradeSpecialization)
        .options(
            selectinload(GradeSpecialization.competence_links),
        )
        .where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == spec_id,
        )
    )
    pairs = list(pairs_q.scalars().all())
    # See `get_matrix_bulk`: cascade reads the same order the UI shows,
    # which is the pair's own sort_index after the new drag-and-drop.
    pairs.sort(
        key=lambda p: (
            p.sort_index,
            (p.grade.title if p.grade else "").lower(),
        )
    )
    return pairs


async def upsert_matrix(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    spec_id: uuid.UUID,
    grade_id: uuid.UUID,
    links: list[dict],
) -> list[dict]:
    """Bulk-replace matrix for a single Spec×Grade pair.

    Cascade normalization runs across the whole spec: writing a level on one
    grade may cascade up to higher grades (auto-inherit) per the matrix
    invariant "level on grade N+1 ≥ level on grade N". Deduplication is
    last-write-wins per competence (mirrors the matrix editor).
    """
    await _get_grade_spec_pair(db, tenant_id, spec_id, grade_id)

    # Collapse duplicates: last write wins per competence.
    grade_links: dict[uuid.UUID, uuid.UUID] = {}
    for raw in links:
        grade_links[raw["competence_id"]] = raw["skill_level_id"]

    await _upsert_matrix_pairs(
        db, tenant_id=tenant_id, spec_id=spec_id, payload={grade_id: grade_links}
    )
    return await get_matrix(db, tenant_id, spec_id, grade_id)


async def upsert_matrix_bulk(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    spec_id: uuid.UUID,
    grades_payload: list[dict],
) -> dict:
    """Bulk-replace matrix across multiple grades of one spec, with cascade
    normalization across the whole career ladder."""
    await _get_specialization(db, tenant_id, spec_id)

    payload: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]] = {}
    for entry in grades_payload:
        gid = entry["grade_id"]
        comp_map: dict[uuid.UUID, uuid.UUID] = {}
        for raw in entry.get("links", []):
            comp_map[raw["competence_id"]] = raw["skill_level_id"]
        payload[gid] = comp_map

    return await _upsert_matrix_pairs(
        db, tenant_id=tenant_id, spec_id=spec_id, payload=payload
    )


async def _upsert_matrix_pairs(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    spec_id: uuid.UUID,
    payload: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]],
) -> dict:
    pairs = await _load_pairs_in_order(db, tenant_id, spec_id)
    pairs_by_grade = {p.grade_id: p for p in pairs}
    grade_order = [p.grade_id for p in pairs]

    unknown_grades = set(payload.keys()) - set(pairs_by_grade.keys())
    if unknown_grades:
        raise AppError("spec_grade_pair_not_found", status.HTTP_404_NOT_FOUND)

    competence_ids: set[uuid.UUID] = set()
    level_ids: set[uuid.UUID] = set()
    for comp_map in payload.values():
        competence_ids.update(comp_map.keys())
        level_ids.update(comp_map.values())
    await _validate_visible_competences_levels(db, tenant_id, competence_ids, level_ids)

    current: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]] = {}
    for p in pairs:
        current[p.grade_id] = {
            link.competence_id: link.skill_level_id for link in p.competence_links
        }

    desired: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]] = {
        gid: dict(current.get(gid, {})) for gid in grade_order
    }
    for gid, comp_map in payload.items():
        desired[gid] = dict(comp_map)

    all_level_ids: set[uuid.UUID] = set()
    for comp_map in desired.values():
        all_level_ids.update(comp_map.values())
    if all_level_ids:
        ls_q = await db.execute(
            select(SkillLevel.id, SkillLevel.sort_index).where(
                SkillLevel.id.in_(all_level_ids)
            )
        )
        level_sort = {row[0]: row[1] for row in ls_q.all()}
    else:
        level_sort = {}

    normalized = _normalize_cascade(grade_order, desired, level_sort)
    await _apply_matrix_state(db, pairs_by_grade, normalized, current)
    await db.commit()
    return await get_matrix_bulk(db, tenant_id, spec_id)


# ---------------------------------------------------------------------------
# Grades CRUD (HRP-57 P1)
# ---------------------------------------------------------------------------


async def _get_grade_item(
    db: AsyncSession, tenant_id: uuid.UUID, grade_id: uuid.UUID
) -> DictionaryItem:
    item = await db.get(DictionaryItem, grade_id)
    if (
        item is None
        or item.type != "grade"
        or (item.tenant_id is not None and item.tenant_id != tenant_id)
    ):
        raise AppError("specialization_grade_not_found", status.HTTP_404_NOT_FOUND)
    return item


async def add_grades(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    spec_id: uuid.UUID,
    grade_ids: list[uuid.UUID],
) -> list[dict]:
    """Bulk-add grades to a specialization.

    Each new pair is appended with `sort_index = max(existing) + 1 + offset`.
    Existing pairs (already linked) are skipped silently — the operation is
    idempotent and a second click on the same multi-select returns the same
    set unchanged.
    """
    await _get_specialization(db, tenant_id, spec_id)

    if not grade_ids:
        return await get_grades_with_attrs(db, tenant_id, spec_id)

    # Validate each grade_id belongs to a real grade visible to this tenant.
    for gid in grade_ids:
        await _get_grade_item(db, tenant_id, gid)

    existing_q = await db.execute(
        select(GradeSpecialization.grade_id).where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == spec_id,
        )
    )
    existing = {row[0] for row in existing_q.all()}

    max_q = await db.execute(
        select(func.coalesce(func.max(GradeSpecialization.sort_index), -1)).where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == spec_id,
        )
    )
    next_sort = int(max_q.scalar_one()) + 1

    # Preserve order of `grade_ids` while dropping duplicates from the input.
    seen: set[uuid.UUID] = set()
    to_add: list[uuid.UUID] = []
    for gid in grade_ids:
        if gid in seen or gid in existing:
            continue
        seen.add(gid)
        to_add.append(gid)

    for gid in to_add:
        db.add(
            GradeSpecialization(
                tenant_id=tenant_id,
                specialization_id=spec_id,
                grade_id=gid,
                sort_index=next_sort,
                passing_score=_DEFAULT_PASSING_SCORE,
            )
        )
        next_sort += 1

    if to_add:
        await db.commit()

    return await get_grades_with_attrs(db, tenant_id, spec_id)


async def reorder_grades(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    spec_id: uuid.UUID,
    orders: list[dict],
) -> list[dict]:
    """Apply a new `sort_index` per grade in one transaction.

    Validates that every `grade_id` corresponds to an existing pair for this
    spec — unknown grades raise 404. Grades not mentioned keep their index.
    """
    await _get_specialization(db, tenant_id, spec_id)

    pairs_q = await db.execute(
        select(GradeSpecialization).where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == spec_id,
        )
    )
    by_grade = {p.grade_id: p for p in pairs_q.scalars().all()}

    for entry in orders:
        gid = entry["grade_id"]
        pair = by_grade.get(gid)
        if pair is None:
            raise AppError("spec_grade_pair_not_found", status.HTTP_404_NOT_FOUND)
        pair.sort_index = entry["sort_index"]

    if orders:
        await db.commit()

    return await get_grades_with_attrs(db, tenant_id, spec_id)


async def patch_grade(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    spec_id: uuid.UUID,
    grade_id: uuid.UUID,
    updates: dict,
) -> dict:
    """Update editable fields of a Spec×Grade pair (salary, description, …)."""
    pair = await _get_grade_spec_pair(db, tenant_id, spec_id, grade_id)

    new_min = updates.get("salary_min", pair.salary_min)
    new_max = updates.get("salary_max", pair.salary_max)
    if new_min is not None and new_max is not None and new_min > new_max:
        raise AppError("salary_min_greater_than_max", status.HTTP_400_BAD_REQUEST)

    if "salary_currency" in updates and updates["salary_currency"] is None:
        # `salary_currency` is NOT NULL — refuse explicit clears rather
        # than silently keep the previous value (HRP-57 P2 review feedback).
        raise AppError("salary_currency_not_clearable", status.HTTP_400_BAD_REQUEST)
    for field, value in updates.items():
        setattr(pair, field, value)

    await db.commit()

    grades = await get_grades_with_attrs(db, tenant_id, spec_id)
    return next(g for g in grades if g["grade_id"] == grade_id)


async def delete_grade(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    spec_id: uuid.UUID,
    grade_id: uuid.UUID,
) -> None:
    """Remove a Spec×Grade pair. Blocks with 409 if any Position uses it."""
    pair = await _get_grade_spec_pair(db, tenant_id, spec_id, grade_id)

    pos_q = await db.execute(
        select(func.count(Position.id)).where(
            Position.tenant_id == tenant_id,
            Position.specialization_id == spec_id,
            Position.grade_id == grade_id,
        )
    )
    in_use = int(pos_q.scalar_one() or 0)
    if in_use > 0:
        raise AppError(
            "grade_in_use_by_positions",
            status.HTTP_409_CONFLICT,
            count=in_use,
        )

    await db.delete(pair)
    await db.commit()


# ---------------------------------------------------------------------------
# Indicators (for tooltip — union across levels up to selected)
# ---------------------------------------------------------------------------


async def get_competence_indicators_by_level(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
) -> list[dict]:
    """Indicators for one competence, grouped by skill level (origin + tenant).

    Used by the matrix tooltip to show union of indicators up to the selected
    level. Level ``sort_index`` is included so the client can compute the
    union without an extra round-trip.
    """
    comp_q = await db.execute(
        select(Competence).where(
            Competence.id == competence_id,
            (Competence.tenant_id == tenant_id) | (Competence.tenant_id.is_(None)),
        )
    )
    comp = comp_q.scalar_one_or_none()
    if comp is None:
        raise AppError("competence_not_found", status.HTTP_404_NOT_FOUND)

    rows_q = await db.execute(
        select(Indicator, SkillLevel)
        .join(SkillLevel, SkillLevel.id == Indicator.skill_level_id)
        .where(
            Indicator.competence_id == competence_id,
            Indicator.is_active.is_(True),
            (Indicator.tenant_id == tenant_id) | (Indicator.tenant_id.is_(None)),
            (SkillLevel.tenant_id == tenant_id) | (SkillLevel.tenant_id.is_(None)),
            SkillLevel.is_active.is_(True),
        )
        .order_by(SkillLevel.sort_index, Indicator.sort_index)
    )
    return [
        {
            "id": ind.id,
            "title": ind.title,
            "weight": ind.weight,
            "skill_level_id": ind.skill_level_id,
            "skill_level_title": lvl.title,
            # HRP-479: origin levels localize via reference.skillLevel.*.
            "skill_level_i18n_key": lvl.i18n_key,
            "skill_level_sort_index": lvl.sort_index,
        }
        for ind, lvl in rows_q.all()
    ]
