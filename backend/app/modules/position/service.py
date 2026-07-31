import uuid

from fastapi import status
from sqlalchemy import func, select, tuple_
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.modules.employee.alerts import (
    ALERT_LABELS,
    AlertCode,
    compute_employee_alerts_bulk,
)
from app.modules.employee.models import Employee
from app.modules.position.models import LIFECYCLE_STATUSES, Position
from app.modules.position.schemas import (
    PositionBulkAction,
    PositionCreate,
    PositionUpdate,
)

# HRP-57 E8: bag of profile-derived fields stitched onto each PositionRead.
# Empty dict means "no profile inheritance available" (no spec/grade pair, or
# pair has no GradeSpecialization row).
_PositionExtras = dict


def _position_to_read(
    pos: Position,
    employee_count: int = 0,
    extras: _PositionExtras | None = None,
) -> dict:
    extras = extras or {}
    headcount = pos.headcount
    if headcount is None:
        vacancy_count: int | None = None
    else:
        vacancy_count = max(0, headcount - employee_count)
    # HRP-180: expose spec/grade options as small arrays so the vacancy
    # form can populate its multi-selects without a follow-up call. Today
    # this mirrors the single (specialization_id, grade_id) pair; when the
    # Position model later supports many-to-many spec/grade these will
    # widen without a frontend change.
    specializations: list[dict] = []
    if pos.specialization_id is not None:
        specializations.append(
            {
                "id": pos.specialization_id,
                "title": pos.specialization.title if pos.specialization else None,
            }
        )
    grades: list[dict] = []
    if pos.grade_id is not None:
        grades.append(
            {
                "id": pos.grade_id,
                "title": pos.grade.title if pos.grade else None,
            }
        )
    return {
        "id": pos.id,
        "tenant_id": pos.tenant_id,
        "title": pos.title,
        "description": pos.description,
        "specialization_id": pos.specialization_id,
        "specialization_title": (
            pos.specialization.title if pos.specialization else None
        ),
        "grade_id": pos.grade_id,
        "grade_title": pos.grade.title if pos.grade else None,
        "division_id": pos.division_id,
        "division_name": pos.division.name if pos.division else None,
        "headcount": headcount,
        "is_active": pos.is_active,
        "lifecycle_status": pos.lifecycle_status,
        "source": pos.source,
        "employee_count": employee_count,
        "salary_min": extras.get("salary_min"),
        "salary_max": extras.get("salary_max"),
        "salary_currency": extras.get("salary_currency"),
        "vacancy_count": vacancy_count,
        "matrix_configured": bool(extras.get("matrix_configured", False)),
        "specializations": specializations,
        "grades": grades,
        "created_at": pos.created_at,
    }


async def _get_position_profile_extras_bulk(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    positions: list[Position],
) -> dict[uuid.UUID, _PositionExtras]:
    """Resolve salary inheritance and matrix-configured flag in two queries.

    Walks `(specialization_id, grade_id)` pairs once across all positions:
      1. Fetch matching `GradeSpecialization` rows → salary fields + gs_id
      2. Count `GradeCompetenceLink` per gs_id → matrix_configured
    """
    from app.modules.grade_system.models import (
        GradeCompetenceLink,
        GradeSpecialization,
    )

    pairs = {
        (p.specialization_id, p.grade_id)
        for p in positions
        if p.specialization_id and p.grade_id
    }
    if not pairs:
        return {p.id: {} for p in positions}

    gs_rows = (
        (
            await db.execute(
                select(GradeSpecialization).where(
                    GradeSpecialization.tenant_id == tenant_id,
                    tuple_(
                        GradeSpecialization.specialization_id,
                        GradeSpecialization.grade_id,
                    ).in_(list(pairs)),
                )
            )
        )
        .scalars()
        .all()
    )
    gs_by_pair: dict[tuple[uuid.UUID, uuid.UUID], GradeSpecialization] = {
        (gs.specialization_id, gs.grade_id): gs for gs in gs_rows
    }

    gs_ids = [gs.id for gs in gs_rows]
    if gs_ids:
        link_counts_rows = (
            await db.execute(
                select(
                    GradeCompetenceLink.grade_specialization_id,
                    func.count(GradeCompetenceLink.id),
                )
                .where(GradeCompetenceLink.grade_specialization_id.in_(gs_ids))
                .group_by(GradeCompetenceLink.grade_specialization_id)
            )
        ).all()
        configured_ids = {row[0] for row in link_counts_rows if row[1] > 0}
    else:
        configured_ids = set()

    out: dict[uuid.UUID, _PositionExtras] = {}
    for p in positions:
        if p.specialization_id is None or p.grade_id is None:
            out[p.id] = {}
            continue
        gs = gs_by_pair.get((p.specialization_id, p.grade_id))
        if gs is None:
            out[p.id] = {}
            continue
        out[p.id] = {
            "salary_min": gs.salary_min,
            "salary_max": gs.salary_max,
            "salary_currency": gs.salary_currency,
            "matrix_configured": gs.id in configured_ids,
        }
    return out


async def _get_position_extras(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pos: Position,
) -> _PositionExtras:
    extras_map = await _get_position_profile_extras_bulk(db, tenant_id, [pos])
    return extras_map.get(pos.id, {})


async def _get_employee_count(
    db: AsyncSession, tenant_id: uuid.UUID, position_id: uuid.UUID
) -> int:
    result = await db.execute(
        select(func.count(Employee.id)).where(
            Employee.position_id == position_id,
            Employee.tenant_id == tenant_id,
        )
    )
    return result.scalar() or 0


async def _get_employee_counts_bulk(
    db: AsyncSession, tenant_id: uuid.UUID, position_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Fetch employee counts for multiple positions in a single query."""
    if not position_ids:
        return {}
    result = await db.execute(
        select(Employee.position_id, func.count(Employee.id))
        .where(
            Employee.position_id.in_(position_ids),
            Employee.tenant_id == tenant_id,
        )
        .group_by(Employee.position_id)
    )
    return {row[0]: row[1] for row in result.all() if row[0] is not None}


async def _validate_fk_refs(db: AsyncSession, tenant_id: uuid.UUID, data: dict) -> None:
    """Validate that specialization_id, grade_id, division_id are correct types and tenant."""
    from app.modules.company.models import Division
    from app.modules.dictionary.models import DictionaryItem

    if data.get("specialization_id"):
        item = await db.get(DictionaryItem, data["specialization_id"])
        if not item or item.type != "specialization":
            raise AppError("invalid_specialization_id", status.HTTP_400_BAD_REQUEST)
        if item.tenant_id is not None and item.tenant_id != tenant_id:
            raise AppError("invalid_specialization_id", status.HTTP_400_BAD_REQUEST)
    if data.get("grade_id"):
        item = await db.get(DictionaryItem, data["grade_id"])
        if not item or item.type != "grade":
            raise AppError("invalid_grade_id", status.HTTP_400_BAD_REQUEST)
        if item.tenant_id is not None and item.tenant_id != tenant_id:
            raise AppError("invalid_grade_id", status.HTTP_400_BAD_REQUEST)
    if data.get("division_id"):
        div = await db.get(Division, data["division_id"])
        if not div or div.tenant_id != tenant_id:
            raise AppError("invalid_division_id", status.HTTP_400_BAD_REQUEST)


async def create_position(
    db: AsyncSession, tenant_id: uuid.UUID, data: PositionCreate
) -> dict:
    # Check uniqueness
    existing = await db.execute(
        select(Position).where(
            Position.tenant_id == tenant_id,
            Position.title == data.title,
        )
    )
    if existing.scalar_one_or_none():
        raise AppError("position_title_exists", status.HTTP_409_CONFLICT)

    await _validate_fk_refs(db, tenant_id, data.model_dump())
    pos = Position(tenant_id=tenant_id, **data.model_dump())
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    extras = await _get_position_extras(db, tenant_id, pos)
    return _position_to_read(pos, 0, extras)


async def list_positions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    search: str | None = None,
    is_active: bool | None = None,
    source: str | None = None,
    specialization_id: uuid.UUID | None = None,
    grade_id: uuid.UUID | None = None,
    division_id: uuid.UUID | None = None,
    *,
    lifecycle_status: str | None = None,
    has_vacancies: bool | None = None,
    matrix_unconfigured: bool | None = None,
) -> tuple[list[dict], int]:
    query = select(Position).where(Position.tenant_id == tenant_id)
    count_query = select(func.count(Position.id)).where(Position.tenant_id == tenant_id)

    if search:
        query = query.where(Position.title.ilike(f"%{search}%"))
        count_query = count_query.where(Position.title.ilike(f"%{search}%"))
    if is_active is not None:
        query = query.where(Position.is_active == is_active)
        count_query = count_query.where(Position.is_active == is_active)
    if source:
        query = query.where(Position.source == source)
        count_query = count_query.where(Position.source == source)
    if specialization_id:
        query = query.where(Position.specialization_id == specialization_id)
        count_query = count_query.where(Position.specialization_id == specialization_id)
    if grade_id:
        query = query.where(Position.grade_id == grade_id)
        count_query = count_query.where(Position.grade_id == grade_id)
    if division_id:
        query = query.where(Position.division_id == division_id)
        count_query = count_query.where(Position.division_id == division_id)

    # HRP-72: lifecycle is the new canonical state column; `is_active` is kept
    # for backwards-compat (= `lifecycle_status == 'active'`).
    if lifecycle_status:
        if lifecycle_status not in LIFECYCLE_STATUSES:
            raise AppError(
                "invalid_lifecycle_status",
                status.HTTP_400_BAD_REQUEST,
                allowed=list(LIFECYCLE_STATUSES),
            )
        query = query.where(Position.lifecycle_status == lifecycle_status)
        count_query = count_query.where(Position.lifecycle_status == lifecycle_status)

    # HRP-72: "has vacancies" means headcount > active employees on this row.
    # Pre-compute the active employee count per position via a correlated
    # subquery so the predicate fits inside the same SQL pass.
    if has_vacancies is not None:
        emp_count_subq = (
            select(func.count(Employee.id))
            .where(Employee.position_id == Position.id)
            .where(Employee.tenant_id == tenant_id)
            .correlate(Position)
            .scalar_subquery()
        )
        if has_vacancies:
            predicate = (Position.headcount.is_not(None)) & (
                Position.headcount > emp_count_subq
            )
        else:
            predicate = (Position.headcount.is_(None)) | (
                Position.headcount <= emp_count_subq
            )
        query = query.where(predicate)
        count_query = count_query.where(predicate)

    # HRP-72: "matrix unconfigured" — Position has no GradeSpecialization with
    # any GradeCompetenceLink for its (spec, grade) pair.
    if matrix_unconfigured is not None:
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )

        configured_pos_subq = (
            select(Position.id)
            .join(
                GradeSpecialization,
                (GradeSpecialization.tenant_id == Position.tenant_id)
                & (GradeSpecialization.specialization_id == Position.specialization_id)
                & (GradeSpecialization.grade_id == Position.grade_id),
            )
            .join(
                GradeCompetenceLink,
                GradeCompetenceLink.grade_specialization_id == GradeSpecialization.id,
            )
            .where(Position.tenant_id == tenant_id)
            .where(Position.specialization_id.is_not(None))
            .where(Position.grade_id.is_not(None))
        ).scalar_subquery()

        if matrix_unconfigured:
            query = query.where(Position.id.not_in(configured_pos_subq))
            count_query = count_query.where(Position.id.not_in(configured_pos_subq))
        else:
            query = query.where(Position.id.in_(configured_pos_subq))
            count_query = count_query.where(Position.id.in_(configured_pos_subq))

    total = (await db.execute(count_query)).scalar() or 0

    result = await db.execute(query.order_by(Position.title).offset(skip).limit(limit))
    positions = result.scalars().all()

    counts = await _get_employee_counts_bulk(db, tenant_id, [p.id for p in positions])
    extras_map = await _get_position_profile_extras_bulk(db, tenant_id, list(positions))
    items = [
        _position_to_read(pos, counts.get(pos.id, 0), extras_map.get(pos.id, {}))
        for pos in positions
    ]
    return items, total


async def get_position(
    db: AsyncSession, tenant_id: uuid.UUID, position_id: uuid.UUID
) -> dict:
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != tenant_id:
        raise AppError("position_not_found", status.HTTP_404_NOT_FOUND)
    count = await _get_employee_count(db, tenant_id, pos.id)
    extras = await _get_position_extras(db, tenant_id, pos)
    return _position_to_read(pos, count, extras)


def _is_lifecycle_only_update(updates: dict) -> bool:
    """True if the update only touches lifecycle_status/is_active."""
    if not updates:
        return False
    lifecycle_keys = {"lifecycle_status", "is_active"}
    return set(updates.keys()).issubset(lifecycle_keys)


async def update_position(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    position_id: uuid.UUID,
    data: PositionUpdate,
) -> dict:
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != tenant_id:
        raise AppError("position_not_found", status.HTTP_404_NOT_FOUND)

    updates = data.model_dump(exclude_unset=True)

    # POS6: Closed positions are read-only; only lifecycle_status/is_active
    # may change (so HR can re-open a closed record).
    if pos.lifecycle_status == "closed" and not _is_lifecycle_only_update(updates):
        raise AppError("position_closed_read_only", status.HTTP_409_CONFLICT)

    await _validate_fk_refs(db, tenant_id, updates)

    # Check title uniqueness if changing
    if "title" in updates and updates["title"] != pos.title:
        existing = await db.execute(
            select(Position).where(
                Position.tenant_id == tenant_id,
                Position.title == updates["title"],
                Position.id != position_id,
            )
        )
        if existing.scalar_one_or_none():
            raise AppError("position_title_exists", status.HTTP_409_CONFLICT)

    title_changed = "title" in updates and updates["title"] != pos.title

    for field, value in updates.items():
        setattr(pos, field, value)

    # Keep is_active and lifecycle_status in sync when only one is provided.
    if "lifecycle_status" in updates and "is_active" not in updates:
        pos.is_active = pos.lifecycle_status == "active"
    elif "is_active" in updates and "lifecycle_status" not in updates:
        pos.lifecycle_status = "active" if pos.is_active else "frozen"

    # HRP-332: employees carry a denormalized ``position_title`` snapshot
    # (written on assignment). A rename must cascade to every assigned
    # employee in the same transaction, otherwise the old title keeps
    # showing across the system (employee lists, EmployeeSummaryLine,
    # position detail, Talent Market candidate rows).
    if title_changed:
        await db.execute(
            sa_update(Employee)
            .where(
                Employee.tenant_id == tenant_id,
                Employee.position_id == pos.id,
            )
            .values(position_title=pos.title)
        )

    await db.commit()
    await db.refresh(pos)
    count = await _get_employee_count(db, tenant_id, pos.id)
    extras = await _get_position_extras(db, tenant_id, pos)
    return _position_to_read(pos, count, extras)


async def delete_position(
    db: AsyncSession, tenant_id: uuid.UUID, position_id: uuid.UUID
) -> None:
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != tenant_id:
        raise AppError("position_not_found", status.HTTP_404_NOT_FOUND)

    count = await _get_employee_count(db, tenant_id, position_id)
    if count > 0:
        raise AppError(
            "position_delete_has_employees",
            status.HTTP_409_CONFLICT,
            count=count,
        )

    await db.delete(pos)
    await db.commit()


async def deactivate_position(
    db: AsyncSession, tenant_id: uuid.UUID, position_id: uuid.UUID
) -> dict:
    """Set lifecycle_status to ``frozen``.

    .. deprecated:: POS6
        Pre-POS6 shortcut for the common "stop hiring on this slot" action.
        Prefer ``set_position_status(..., new_status="frozen")`` (or any of the
        other lifecycle states) — the dedicated lifecycle endpoint covers this
        and reads cleanly in the audit trail. Kept for backwards compatibility
        with any client that still calls ``POST /positions/{id}/deactivate``.
    """
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != tenant_id:
        raise AppError("position_not_found", status.HTTP_404_NOT_FOUND)

    pos.is_active = False
    pos.lifecycle_status = "frozen"
    await db.commit()
    await db.refresh(pos)
    count = await _get_employee_count(db, tenant_id, pos.id)
    extras = await _get_position_extras(db, tenant_id, pos)
    return _position_to_read(pos, count, extras)


# ---------------------------------------------------------------------------
# POS6: Lifecycle status, occupancy, drill-down with alerts
# ---------------------------------------------------------------------------


async def set_position_status(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    position_id: uuid.UUID,
    new_status: str,
) -> dict:
    """Change Position.lifecycle_status with enum validation.

    Transitions are unrestricted (any → any). The companion ``update_position``
    rejects non-lifecycle edits while ``lifecycle_status == 'closed'`` so the UI
    can render the closed state as read-only.
    """
    if new_status not in LIFECYCLE_STATUSES:
        raise AppError(
            "invalid_lifecycle_status",
            status.HTTP_400_BAD_REQUEST,
            allowed=list(LIFECYCLE_STATUSES),
        )

    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != tenant_id:
        raise AppError("position_not_found", status.HTTP_404_NOT_FOUND)

    pos.lifecycle_status = new_status
    pos.is_active = new_status == "active"

    await db.commit()
    await db.refresh(pos)
    count = await _get_employee_count(db, tenant_id, pos.id)
    extras = await _get_position_extras(db, tenant_id, pos)
    return _position_to_read(pos, count, extras)


async def get_position_occupancy(
    db: AsyncSession, tenant_id: uuid.UUID, position_id: uuid.UUID
) -> dict:
    """Return occupancy stats for a position: ``{assigned, headcount, vacant}``."""
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != tenant_id:
        raise AppError("position_not_found", status.HTTP_404_NOT_FOUND)

    assigned = await _get_employee_count(db, tenant_id, pos.id)
    headcount = pos.headcount
    if headcount is None:
        vacant: int | None = None
    else:
        vacant = max(0, headcount - assigned)

    return {
        "position_id": pos.id,
        "assigned": assigned,
        "headcount": headcount,
        "vacant": vacant,
    }


async def get_matrix_status(
    db: AsyncSession, tenant_id: uuid.UUID, position_id: uuid.UUID
) -> dict:
    """Check whether the (specialization, grade) pair has competence links.

    Powers the "Matrix not configured" banner on the Position detail and the
    "Edit profile matrix" deep-link target.
    """
    from app.modules.grade_system.models import (
        GradeCompetenceLink,
        GradeSpecialization,
    )

    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != tenant_id:
        raise AppError("position_not_found", status.HTTP_404_NOT_FOUND)

    if pos.specialization_id is None or pos.grade_id is None:
        return {
            "configured": False,
            "specialization_id": pos.specialization_id,
            "grade_id": pos.grade_id,
            "grade_specialization_id": None,
            "link_count": 0,
        }

    gs_row = await db.execute(
        select(GradeSpecialization).where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == pos.specialization_id,
            GradeSpecialization.grade_id == pos.grade_id,
        )
    )
    gs = gs_row.scalar_one_or_none()
    if gs is None:
        return {
            "configured": False,
            "specialization_id": pos.specialization_id,
            "grade_id": pos.grade_id,
            "grade_specialization_id": None,
            "link_count": 0,
        }

    count_row = await db.execute(
        select(func.count(GradeCompetenceLink.id)).where(
            GradeCompetenceLink.grade_specialization_id == gs.id
        )
    )
    link_count = count_row.scalar() or 0

    return {
        "configured": link_count > 0,
        "specialization_id": pos.specialization_id,
        "grade_id": pos.grade_id,
        "grade_specialization_id": gs.id,
        "link_count": link_count,
    }


def _employee_alert_payload(code: AlertCode | None) -> dict | None:
    if code is None:
        return None
    return {"code": code, "label": ALERT_LABELS[code]}


async def list_position_employees(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    position_id: uuid.UUID,
    *,
    with_alerts: bool = False,
) -> list[dict]:
    """Drill-down: employees assigned to this position.

    POS6 extends the original POS0 list with optional alert codes.
    """
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != tenant_id:
        raise AppError("position_not_found", status.HTTP_404_NOT_FOUND)

    from app.modules.employee.service import _resolve_emp_avatars_bulk

    result = await db.execute(
        select(Employee)
        .where(
            Employee.position_id == position_id,
            Employee.tenant_id == tenant_id,
        )
        .options(
            selectinload(Employee.user),
            selectinload(Employee.division),
        )
        .order_by(Employee.hire_date.desc())
    )
    employees = list(result.scalars().all())

    alerts_map: dict[uuid.UUID, AlertCode | None] = {}
    if with_alerts:
        alerts_map = await compute_employee_alerts_bulk(db, tenant_id, employees)

    avatars = await _resolve_emp_avatars_bulk(db, employees)

    # Position details are uniform for the whole list: assignment is
    # filtered by position_id, so spec/grade/division come from `pos`,
    # not from each employee's own row.
    pos_specialization_title = pos.specialization.title if pos.specialization else None
    pos_grade_title = pos.grade.title if pos.grade else None
    pos_position_title = pos.title

    items: list[dict] = []
    for emp in employees:
        avatar_url = avatars.get(emp.id)
        items.append(
            {
                "id": emp.id,
                "user_id": emp.user_id,
                "user_name": (
                    f"{emp.user.first_name} {emp.user.last_name}" if emp.user else None
                ),
                "user_email": emp.user.email if emp.user else None,
                "position_title": emp.position_title or pos_position_title,
                "specialization_title": pos_specialization_title,
                "grade_title": pos_grade_title,
                # HRP-175: division_id surfaces so the unified
                # EmployeeList can deep-link the Division cell.
                "division_id": emp.division_id,
                "division_name": (emp.division.name if emp.division else None),
                "hire_date": emp.hire_date,
                "status": emp.status,
                "avatar_url": avatar_url,
                "alert": _employee_alert_payload(alerts_map.get(emp.id)),
            }
        )
    return items


async def get_position_competence_matrix(
    db: AsyncSession, tenant_id: uuid.UUID, position_id: uuid.UUID
) -> dict:
    """Return the competence matrix attached to the position's (grade, spec).

    Resolves to the GradeSpecialization chain for the position's
    specialization_id + grade_id, then expands each competence link
    with its indicators filtered to the chain's required skill_level.
    """
    from app.modules.competence.models import Competence, Indicator
    from app.modules.grade_system.models import (
        GradeCompetenceLink,
        GradeSpecialization,
    )

    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != tenant_id:
        raise AppError("position_not_found", status.HTTP_404_NOT_FOUND)

    if pos.specialization_id is None or pos.grade_id is None:
        return {
            "configured": False,
            "specialization_id": pos.specialization_id,
            "grade_id": pos.grade_id,
            "grade_specialization_id": None,
            "competences": [],
        }

    gs_row = await db.execute(
        select(GradeSpecialization).where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == pos.specialization_id,
            GradeSpecialization.grade_id == pos.grade_id,
        )
    )
    gs = gs_row.scalar_one_or_none()
    if gs is None:
        return {
            "configured": False,
            "specialization_id": pos.specialization_id,
            "grade_id": pos.grade_id,
            "grade_specialization_id": None,
            "competences": [],
        }

    links_result = await db.execute(
        select(GradeCompetenceLink)
        .options(
            selectinload(GradeCompetenceLink.competence).selectinload(Competence.group),
            selectinload(GradeCompetenceLink.skill_level),
        )
        .where(GradeCompetenceLink.grade_specialization_id == gs.id)
    )
    links = list(links_result.scalars().all())
    if not links:
        return {
            "configured": False,
            "specialization_id": pos.specialization_id,
            "grade_id": pos.grade_id,
            "grade_specialization_id": gs.id,
            "competences": [],
        }

    competence_ids = list({link.competence_id for link in links})
    skill_level_ids = list({link.skill_level_id for link in links})
    # Origin competences (tenant_id IS NULL) are shared across tenants;
    # constrain Indicator rows to this tenant or origin so a private
    # indicator authored by another tenant on a shared competence
    # doesn't leak into our matrix.
    indicators_result = await db.execute(
        select(Indicator).where(
            Indicator.competence_id.in_(competence_ids),
            Indicator.skill_level_id.in_(skill_level_ids),
            Indicator.is_active.is_(True),
            (Indicator.tenant_id == tenant_id) | (Indicator.tenant_id.is_(None)),
        )
    )
    indicators_by_pair: dict[tuple[uuid.UUID, uuid.UUID], list[Indicator]] = {}
    for ind in indicators_result.scalars().all():
        indicators_by_pair.setdefault(
            (ind.competence_id, ind.skill_level_id), []
        ).append(ind)

    competences: list[dict] = []
    for link in sorted(
        links,
        key=lambda x: (
            x.competence.group.sort_index if x.competence and x.competence.group else 0,
            x.competence.title if x.competence else "",
        ),
    ):
        comp = link.competence
        if comp is None:
            continue
        pair_indicators = indicators_by_pair.get((comp.id, link.skill_level_id), [])
        competences.append(
            {
                "competence_id": comp.id,
                "title": comp.title,
                "description": comp.description,
                "group_id": comp.group_id,
                "group_title": comp.group.title if comp.group else None,
                "skill_level_id": link.skill_level_id,
                "skill_level_title": (
                    link.skill_level.title if link.skill_level else None
                ),
                "skill_level_i18n_key": (
                    link.skill_level.i18n_key if link.skill_level else None
                ),
                "indicators": [
                    {
                        "id": ind.id,
                        "title": ind.title,
                        "weight": ind.weight,
                        "sort_index": ind.sort_index,
                        "skill_level_id": ind.skill_level_id,
                        "skill_level_title": (
                            link.skill_level.title if link.skill_level else None
                        ),
                        "skill_level_i18n_key": (
                            link.skill_level.i18n_key if link.skill_level else None
                        ),
                    }
                    for ind in sorted(pair_indicators, key=lambda i: i.sort_index)
                ],
            }
        )

    return {
        "configured": True,
        "specialization_id": pos.specialization_id,
        "grade_id": pos.grade_id,
        "grade_specialization_id": gs.id,
        "competences": competences,
    }


async def bulk_action_positions(
    db: AsyncSession, tenant_id: uuid.UUID, data: PositionBulkAction
) -> dict:
    result = await db.execute(
        select(Position).where(
            Position.tenant_id == tenant_id,
            Position.id.in_(data.ids),
            Position.source == "ai_draft",
        )
    )
    positions = result.scalars().all()

    if not positions:
        raise AppError("no_ai_draft_positions_found", status.HTTP_404_NOT_FOUND)

    if data.action == "approve":
        for pos in positions:
            pos.source = "ai_approved"
        await db.commit()
        return {"approved": len(positions)}

    # reject = delete (only if no employees assigned)
    deleted = 0
    for pos in positions:
        count = await _get_employee_count(db, tenant_id, pos.id)
        if count == 0:
            await db.delete(pos)
            deleted += 1
    await db.commit()
    return {"rejected": deleted}
