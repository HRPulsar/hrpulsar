import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.access_scope import (
    assert_employee_write_scope,
    assert_not_self_edit_via_employees,
)
from app.core.errors import AppError
from app.core.s3 import get_presigned_url

# Accepted cross-module coupling (review item [35]): this service reads other
# domains' MODELS only — identity (auth), org structure (company), positions,
# avatar files (storage), and the delete-dependency check over assessment /
# exam / talent_market rows. All model modules are leaves (they import only
# app.models), so these imports cannot cycle. Service-to-service imports
# remain forbidden; cross-domain writes go through events.
from app.modules.assessment.models import PDP, Assessment
from app.modules.auth.models import Invitation, Role, User, user_roles
from app.modules.company.models import Division
from app.modules.employee.alerts import (
    ALERT_LABELS,
    AlertCode,
    compute_employee_alerts_bulk,
)
from app.modules.employee.competence_overview import compute_competence_overview
from app.modules.employee.duration import compute_duration
from app.modules.employee.models import (
    Compensation,
    Course,
    CourseCompetence,
    Education,
    Employee,
    EmployeeEvent,
    PreviousEmployment,
    WorkExperience,
    WorkExperienceCompetence,
)
from app.modules.employee.schemas import (
    CompensationCreate,
    CompensationUpdate,
    CourseCreate,
    CourseUpdate,
    EducationCreate,
    EducationUpdate,
    EmployeeCreate,
    EmployeeEventCreate,
    EmployeeUpdate,
    PreviousEmploymentCreate,
    PreviousEmploymentUpdate,
    WorkExperienceCreate,
    WorkExperienceUpdate,
)
from app.modules.exam.models import Exam
from app.modules.position.models import Position
from app.modules.storage.models import File
from app.modules.talent_market.models import TalentCandidate

logger = logging.getLogger(__name__)


def _coerce_filter_list(value: Any) -> list[Any] | None:
    """Normalize a query filter argument to a non-empty list (or None)."""
    if value is None:
        return None
    if isinstance(value, list):
        return value or None
    return [value]


def _alert_payload(code: AlertCode | None) -> dict | None:
    if code is None:
        return None
    return {"code": code, "label": ALERT_LABELS[code]}


def _employee_to_read(
    emp: Employee,
    avatar_url: str | None = None,
    alert: AlertCode | None = None,
) -> dict:
    pos = emp.position
    spec = pos.specialization if pos else None
    grade = pos.grade if pos else None
    return {
        "id": emp.id,
        "user_id": emp.user_id,
        "division_id": emp.division_id,
        "position_id": emp.position_id,
        "position_title": emp.position_title,
        "specialization_id": spec.id if spec else None,
        "specialization_title": spec.title if spec else None,
        "grade_id": grade.id if grade else None,
        "grade_title": grade.title if grade else None,
        "hire_date": emp.hire_date,
        "status": emp.status,
        # HRP-246: Status / Tenure KPI tiles on the profile page.
        "status_changed_at": emp.status_changed_at,
        "tenant_id": emp.tenant_id,
        "created_at": emp.created_at,
        "user_email": emp.user.email if emp.user else None,
        "user_name": (
            f"{emp.user.first_name} {emp.user.last_name}" if emp.user else None
        ),
        "user_first_login_at": emp.user.first_login_at if emp.user else None,
        "division_name": emp.division.name if emp.division else None,
        "avatar_url": avatar_url,
        "alert": _alert_payload(alert),
    }


def _event_to_read(event: EmployeeEvent) -> dict:
    return {
        "id": event.id,
        "employee_id": event.employee_id,
        "event_type": event.event_type,
        "description": event.description,
        "event_date": event.event_date,
        "metadata": event.metadata_,
        "old_value": event.old_value,
        "new_value": event.new_value,
        "created_at": event.created_at,
    }


async def _get_employee(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> Employee:
    emp = await db.get(Employee, employee_id)
    if not emp or emp.tenant_id != tenant_id:
        raise AppError("employee_not_found", status.HTTP_404_NOT_FOUND)
    return emp


async def _create_event(
    db: AsyncSession,
    employee_id: uuid.UUID,
    event_type: str,
    description: str,
    event_date: date,
    metadata: dict | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
) -> EmployeeEvent:
    event = EmployeeEvent(
        employee_id=employee_id,
        event_type=event_type,
        description=description,
        event_date=event_date,
        metadata_=metadata,
        old_value=old_value,
        new_value=new_value,
    )
    db.add(event)

    # GF11: Publish event for notification dispatch
    try:
        emp = await db.get(Employee, employee_id)
        if emp and emp.user:
            from app.core.events import publish

            await publish(
                "employee.event_created",
                {
                    "tenant_id": emp.tenant_id,
                    "employee_id": employee_id,
                    "user_id": emp.user_id,
                    "user_email": emp.user.email,
                    "employee_name": f"{emp.user.first_name} {emp.user.last_name}",
                    "event_type": event_type,
                    "description": description,
                },
            )
    except Exception:  # noqa: BLE001 - best-effort event fan-out
        pass  # Don't fail event creation if notification dispatch fails

    return event


# --- Available users ---


async def list_available_users(db: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    """Return tenant users that don't yet have an Employee record."""
    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            ~User.id.in_(
                select(Employee.user_id).where(Employee.tenant_id == tenant_id)
            ),
        )
    )
    users = result.scalars().all()

    # Find which emails came through accepted invitations
    invited_emails: set[str] = set()
    if users:
        inv_result = await db.execute(
            select(Invitation.email).where(
                Invitation.tenant_id == tenant_id,
                Invitation.status == "accepted",
            )
        )
        invited_emails = {row[0] for row in inv_result.all()}

    return [
        {
            "id": u.id,
            "email": u.email,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "origin": "invited" if u.email in invited_emails else "self-registered",
        }
        for u in users
    ]


# --- CRUD ---


async def create_employee(
    db: AsyncSession, tenant_id: uuid.UUID, data: EmployeeCreate
) -> dict:
    # Validate user belongs to tenant
    user = await db.get(User, data.user_id)
    if not user or user.tenant_id != tenant_id:
        raise AppError("employee_invalid_user", status.HTTP_400_BAD_REQUEST)

    # Check not already an employee
    existing = await db.execute(
        select(Employee).where(
            Employee.user_id == data.user_id, Employee.tenant_id == tenant_id
        )
    )
    if existing.scalar_one_or_none():
        raise AppError("user_already_employee", status.HTTP_409_CONFLICT)

    # Resolve position_title from position_id
    fields = data.model_dump()
    if data.position_id:
        pos = await db.get(Position, data.position_id)
        if not pos or pos.tenant_id != tenant_id:
            raise AppError("invalid_position_id", status.HTTP_400_BAD_REQUEST)
        fields["position_title"] = pos.title

    # HRP-246: stamp ``status_changed_at`` at create time so the Status
    # KPI tile shows "since {hire moment}" for fresh records too, not a
    # null fallback to ``created_at``.
    emp = Employee(
        tenant_id=tenant_id,
        status_changed_at=datetime.now(timezone.utc),
        **fields,
    )
    db.add(emp)
    await db.flush()

    # Auto-create hire event
    title = emp.position_title or "Employee"
    await _create_event(db, emp.id, "hire", f"Hired as {title}", data.hire_date)

    await db.commit()
    await db.refresh(emp)
    return _employee_to_read(emp)


async def list_employees(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    division_id: list[uuid.UUID] | uuid.UUID | None = None,
    status_filter: list[str] | str | None = None,
    visible_employee_ids: set[uuid.UUID] | None = None,
    specialization_id: list[uuid.UUID] | uuid.UUID | None = None,
    position_id: list[uuid.UUID] | uuid.UUID | None = None,
    grade_id: list[uuid.UUID] | uuid.UUID | None = None,
    unassigned_only: bool = False,
    with_alerts: bool = False,
    q: str | None = None,
) -> tuple[list[dict], int]:
    division_ids = _coerce_filter_list(division_id)
    status_list = _coerce_filter_list(status_filter)
    position_ids = _coerce_filter_list(position_id)
    specialization_ids = _coerce_filter_list(specialization_id)
    grade_ids = _coerce_filter_list(grade_id)

    query = select(Employee).where(Employee.tenant_id == tenant_id)
    count_query = select(func.count(Employee.id)).where(Employee.tenant_id == tenant_id)

    if visible_employee_ids is not None:
        if not visible_employee_ids:
            return [], 0
        query = query.where(Employee.id.in_(visible_employee_ids))
        count_query = count_query.where(Employee.id.in_(visible_employee_ids))

    if division_ids:
        query = query.where(Employee.division_id.in_(division_ids))
        count_query = count_query.where(Employee.division_id.in_(division_ids))
    if status_list:
        query = query.where(Employee.status.in_(status_list))
        count_query = count_query.where(Employee.status.in_(status_list))
    if position_ids:
        query = query.where(Employee.position_id.in_(position_ids))
        count_query = count_query.where(Employee.position_id.in_(position_ids))
    if unassigned_only:
        query = query.where(Employee.position_id.is_(None))
        count_query = count_query.where(Employee.position_id.is_(None))

    # spec/grade live on Position; if either filter is active, restrict the
    # employee's position with a single subquery so the predicates compose
    # cleanly when both filters are present.
    if specialization_ids or grade_ids:
        position_subq = select(Position.id).where(Position.tenant_id == tenant_id)
        if specialization_ids:
            position_subq = position_subq.where(
                Position.specialization_id.in_(specialization_ids)
            )
        if grade_ids:
            position_subq = position_subq.where(Position.grade_id.in_(grade_ids))
        query = query.where(Employee.position_id.in_(position_subq))
        count_query = count_query.where(Employee.position_id.in_(position_subq))

    # HRP-120: search by employee's user first/last name or email. Without a
    # server-side predicate the UI used to filter the current page only, so
    # entries on other pages stayed invisible.
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        full_name = func.lower(User.first_name + " " + User.last_name)
        reverse_name = func.lower(User.last_name + " " + User.first_name)
        search_predicate = or_(
            full_name.like(needle),
            reverse_name.like(needle),
            func.lower(User.first_name).like(needle),
            func.lower(User.last_name).like(needle),
            func.lower(User.email).like(needle),
        )
        # Defense-in-depth: enforce tenant equality on the User join even
        # though Employee.tenant_id is already constrained — keeps the
        # predicate honest if the 1:1 invariant ever loosens.
        join_clause = (Employee.user_id == User.id) & (User.tenant_id == tenant_id)
        query = query.join(User, join_clause).where(search_predicate)
        count_query = count_query.join(User, join_clause).where(search_predicate)

    # Stable order so paginated results don't drift when rows are inserted
    # concurrently or when the planner picks a different default order.
    query = query.order_by(Employee.created_at.desc(), Employee.id)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.offset(skip).limit(limit))
    employees = list(result.scalars().all())

    alerts_map: dict[uuid.UUID, AlertCode | None] = {}
    if with_alerts:
        alerts_map = await compute_employee_alerts_bulk(db, tenant_id, employees)

    items = []
    for e in employees:
        url = await _resolve_emp_avatar(db, e)
        items.append(_employee_to_read(e, url, alerts_map.get(e.id)))
    return items, total


async def _resolve_emp_avatar(db: AsyncSession, emp: Employee) -> str | None:
    fid = emp.user.avatar_file_id if emp.user else None
    if not fid:
        return None
    f = await db.get(File, fid)
    return get_presigned_url(f.path) if f else None


async def _resolve_emp_avatars_bulk(
    db: AsyncSession, employees: list[Employee]
) -> dict[uuid.UUID, str]:
    """Batch presigned-URL lookup for a list of employees (single SELECT).

    Avoids N+1 in /positions/{id}/employees and /specializations/{id}/employees.
    """
    file_ids = {
        emp.user.avatar_file_id
        for emp in employees
        if emp.user and emp.user.avatar_file_id
    }
    if not file_ids:
        return {}
    files = (
        (await db.execute(select(File).where(File.id.in_(file_ids)))).scalars().all()
    )
    paths_by_id = {f.id: f.path for f in files}
    out: dict[uuid.UUID, str] = {}
    for emp in employees:
        fid = emp.user.avatar_file_id if emp.user else None
        path = paths_by_id.get(fid) if fid else None
        if not path:
            continue
        url = get_presigned_url(path)
        if url:
            out[emp.id] = url
    return out


async def get_employee(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> dict:
    emp = await _get_employee(db, tenant_id, employee_id)
    url = await _resolve_emp_avatar(db, emp)
    return _employee_to_read(emp, url)


async def update_employee(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    data: EmployeeUpdate,
    current_user: User,
) -> dict:
    emp = await _get_employee(db, tenant_id, employee_id)
    await assert_employee_write_scope(db, current_user, emp)
    assert_not_self_edit_via_employees(current_user, emp)
    updates = data.model_dump(exclude_unset=True)
    today = date.today()

    # HRP-121: Name/Last name live on the underlying User row. Strip them
    # out so the Employee loop below doesn't try to setattr them on the
    # wrong model, then apply to the eagerly-loaded user directly. RBAC is
    # already enforced via assert_employee_write_scope above.
    user_updates: dict[str, str] = {}
    for field in ("first_name", "last_name"):
        if field in updates:
            value = updates.pop(field)
            if value is None:
                continue
            trimmed = value.strip()
            if not trimmed:
                raise AppError(
                    "employee_name_field_empty",
                    status.HTTP_400_BAD_REQUEST,
                    field=field,
                )
            user_updates[field] = trimmed
    if user_updates:
        if emp.user is None:
            # Employee.user_id is FK NOT NULL; a missing user means broken
            # invariant, not "no name to update". Surface it.
            raise AppError("user_not_found", status.HTTP_404_NOT_FOUND)
        before = {"first_name": emp.user.first_name, "last_name": emp.user.last_name}
        for field, value in user_updates.items():
            setattr(emp.user, field, value)
        after = {"first_name": emp.user.first_name, "last_name": emp.user.last_name}
        if before != after:
            await _create_event(
                db,
                emp.id,
                "name_change",
                "Name updated",
                today,
                old_value=before,
                new_value=after,
            )

    # Auto-create events for tracked changes
    if "division_id" in updates and updates["division_id"] != emp.division_id:
        await _create_event(
            db,
            emp.id,
            "division_change",
            "Division changed",
            today,
            old_value={
                "division_id": str(emp.division_id) if emp.division_id else None
            },
            new_value={
                "division_id": (
                    str(updates["division_id"]) if updates["division_id"] else None
                )
            },
        )
    # Reject position_title-only updates (must go through position_id)
    if "position_title" in updates and "position_id" not in updates:
        del updates["position_title"]

    # Resolve position_title when position_id changes
    if "position_id" in updates and updates["position_id"] != emp.position_id:
        if updates["position_id"]:
            pos = await db.get(Position, updates["position_id"])
            if not pos or pos.tenant_id != tenant_id:
                raise AppError("invalid_position_id", status.HTTP_400_BAD_REQUEST)
            updates["position_title"] = pos.title
        else:
            updates["position_title"] = None
        await _create_event(
            db,
            emp.id,
            "position_change",
            f"Position changed to {updates.get('position_title', '')}",
            today,
            old_value={"position_title": emp.position_title},
            new_value={"position_title": updates.get("position_title")},
        )
    if "status" in updates and updates["status"] != emp.status:
        old_status = emp.status
        new_status = updates["status"]
        diff = {
            "old_value": {"status": old_status},
            "new_value": {"status": new_status},
        }
        # HRP-246: stamp so the profile STATUS KPI tile can render
        # "since {date of last status change}" without re-deriving it
        # from the events log on every page render.
        emp.status_changed_at = datetime.now(timezone.utc)
        if new_status == "terminated":
            await _create_event(
                db, emp.id, "termination", "Employment terminated", today, **diff
            )
        elif new_status == "inactive":
            await _create_event(
                db,
                emp.id,
                "status_inactive",
                "Employment marked inactive",
                today,
                **diff,
            )
        elif new_status == "active" and old_status in ("terminated", "inactive"):
            await _create_event(
                db,
                emp.id,
                "status_reactivated",
                "Employment reactivated",
                today,
                **diff,
            )

    for field, value in updates.items():
        setattr(emp, field, value)
    await db.commit()
    await db.refresh(emp)
    return _employee_to_read(emp)


async def delete_employee(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    current_user: User,
) -> dict:
    emp = await _get_employee(db, tenant_id, employee_id)
    await assert_employee_write_scope(db, current_user, emp)

    # HRP-65: hard-delete blocked when the employee has dependent objects.
    # CASCADE / SET NULL on the FKs would silently nuke or demote linked rows,
    # which is destructive — the API returns 409 instead and the operator
    # must clean those up first (or terminate via status update).
    #   - Assessment / PDP / Exam: ondelete=CASCADE on employee_id
    #   - TalentCandidate: ondelete=CASCADE on employee_id (required for
    #     demo purge — see talentcand_employee_cascade migration); the
    #     explicit check below preserves the has_connections guard so we
    #     don't silently drop talent_market entries on a direct delete.
    #   - Division.manager_id / deputy_manager_id: ondelete=SET NULL (silent)
    has_connections = False
    for model in (Assessment, PDP, Exam, TalentCandidate):
        exists_q = select(model.id).where(model.employee_id == emp.id).limit(1)
        if (await db.execute(exists_q)).scalar_one_or_none() is not None:
            has_connections = True
            break
    if not has_connections:
        manages_division_q = (
            select(Division.id)
            .where(
                Division.tenant_id == tenant_id,
                or_(
                    Division.manager_id == emp.id,
                    Division.deputy_manager_id == emp.id,
                ),
            )
            .limit(1)
        )
        if (await db.execute(manages_division_q)).scalar_one_or_none() is not None:
            has_connections = True

    if has_connections:
        first = (emp.user.first_name if emp.user else None) or ""
        last = (emp.user.last_name if emp.user else None) or ""
        full_name = f"{first} {last}".strip() or "Employee"
        raise AppError(
            "employee_has_connections",
            status.HTTP_409_CONFLICT,
            detail_extra={},
            detail_code_key="error_code",
            detail_code="has_connections",
            full_name=full_name,
        )

    snapshot = _employee_to_read(emp)
    await db.delete(emp)
    await db.commit()
    return snapshot


_NON_DOWNGRADABLE_ROLES = frozenset({"admin", "hr", "platform_admin"})


async def downgrade_employee_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> dict:
    """Strip the `manager` role from an employee.

    Re-checks server-side that the user no longer manages any division of the
    tenant. Refuses to downgrade users who hold admin / hr / platform_admin —
    those roles are independent of division assignments.
    """
    emp = await _get_employee(db, tenant_id, employee_id)

    still_managing = (
        await db.execute(
            select(func.count(Division.id)).where(
                Division.tenant_id == tenant_id,
                or_(
                    Division.manager_id == emp.id,
                    Division.deputy_manager_id == emp.id,
                ),
            )
        )
    ).scalar() or 0
    if still_managing > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "still_manages_divisions",
                "count": still_managing,
            },
        )

    role_rows = await db.execute(
        select(Role)
        .join(user_roles, user_roles.c.role_id == Role.id)
        .where(user_roles.c.user_id == emp.user_id)
    )
    user_role_codes = {r.code: r for r in role_rows.scalars().all()}

    if user_role_codes.keys() & _NON_DOWNGRADABLE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "cannot_downgrade_admin"},
        )

    manager_role = user_role_codes.get("manager")
    if manager_role is None:
        return {"employee_id": emp.id, "user_id": emp.user_id, "downgraded": False}

    await db.execute(
        user_roles.delete().where(
            user_roles.c.user_id == emp.user_id,
            user_roles.c.role_id == manager_role.id,
        )
    )
    await db.commit()
    logger.info(
        "employee.role_downgraded",
        extra={
            "event": "employee.role_downgraded",
            "tenant_id": str(tenant_id),
            "user_id": str(emp.user_id),
            "employee_id": str(emp.id),
            "from_role": "manager",
        },
    )
    return {"employee_id": emp.id, "user_id": emp.user_id, "downgraded": True}


# --- Events ---


async def list_events(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    event_type: str | None = None,
) -> list[dict]:
    emp = await _get_employee(db, tenant_id, employee_id)
    query = (
        select(EmployeeEvent)
        .where(EmployeeEvent.employee_id == emp.id)
        .order_by(EmployeeEvent.event_date.desc())
    )
    if event_type:
        query = query.where(EmployeeEvent.event_type == event_type)
    result = await db.execute(query)
    return [_event_to_read(e) for e in result.scalars().all()]


async def create_event(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    data: EmployeeEventCreate,
    current_user: User,
) -> dict:
    emp = await _get_employee(db, tenant_id, employee_id)
    await assert_employee_write_scope(db, current_user, emp)
    event = await _create_event(
        db,
        emp.id,
        data.event_type,
        data.description or "",
        data.event_date,
        data.metadata,
    )
    await db.commit()
    await db.refresh(event)
    return _event_to_read(event)


# ---------------------------------------------------------------------------
# HRP-153: Competence overview
# ---------------------------------------------------------------------------


async def get_competence_overview(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> dict:
    emp = await _get_employee(db, tenant_id, employee_id)
    return await compute_competence_overview(db, tenant_id, emp)


# ---------------------------------------------------------------------------
# Generic child-resource helpers (used by GF1 + GF2 entities)
# ---------------------------------------------------------------------------


async def _get_child(
    db: AsyncSession,
    model: Any,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    label: str,
) -> Any:
    item = await db.get(model, item_id)
    if not item or item.tenant_id != tenant_id:
        raise AppError(
            "employee_child_not_found", status.HTTP_404_NOT_FOUND, label=label
        )
    return item


async def _list_children(
    db: AsyncSession,
    model: Any,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> list[dict[str, Any]]:
    await _get_employee(db, tenant_id, employee_id)
    result = await db.execute(
        select(model)
        .where(model.employee_id == employee_id)
        .order_by(model.created_at.desc())
    )
    return [dict_from_model(r) for r in result.scalars().all()]


def dict_from_model(obj) -> dict:
    """Convert an ORM instance to a dict of its column values."""
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


async def _assert_child_scope(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    current_user: User,
    *,
    allow_self_owner: bool = False,
) -> Employee:
    """Guard for "write something under /employees/{id}/...".

    Default behaviour is admin/manager-only (delegated to
    `assert_employee_write_scope`). Pass `allow_self_owner=True` to let a
    regular employee modify their *own* records — HRP-66 carves out the
    Education / Courses sections so people can keep their training history
    current without HR babysitting.
    """
    emp = await _get_employee(db, tenant_id, employee_id)
    if allow_self_owner and emp.user_id == current_user.id:
        return emp
    await assert_employee_write_scope(db, current_user, emp)
    return emp


async def _create_child(
    db: AsyncSession,
    model: Any,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    data: Any,
    current_user: User,
    *,
    allow_self_owner: bool = False,
) -> dict[str, Any]:
    await _assert_child_scope(
        db, tenant_id, employee_id, current_user, allow_self_owner=allow_self_owner
    )
    item = model(
        tenant_id=tenant_id,
        employee_id=employee_id,
        **data.model_dump(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return dict_from_model(item)


async def _update_child(
    db: AsyncSession,
    model: Any,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    data: Any,
    label: str,
    current_user: User,
    *,
    allow_self_owner: bool = False,
) -> dict[str, Any]:
    item = await _get_child(db, model, tenant_id, item_id, label)
    await _assert_child_scope(
        db, tenant_id, item.employee_id, current_user, allow_self_owner=allow_self_owner
    )
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return dict_from_model(item)


async def _delete_child(
    db: AsyncSession,
    model: Any,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    label: str,
    current_user: User,
    *,
    allow_self_owner: bool = False,
) -> dict[str, Any]:
    item = await _get_child(db, model, tenant_id, item_id, label)
    await _assert_child_scope(
        db, tenant_id, item.employee_id, current_user, allow_self_owner=allow_self_owner
    )
    result = dict_from_model(item)
    await db.delete(item)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Competence link helpers (GF1 / GF2 Improve)
# ---------------------------------------------------------------------------


def _competence_refs(links) -> list[dict]:
    """Extract competence refs from relationship links."""
    return [
        {
            "id": link.competence_id,
            "title": link.competence.title if link.competence else "",
        }
        for link in links
    ]


async def _sync_competence_links(
    db: AsyncSession,
    link_model: Any,
    fk_field: str,
    parent_id: uuid.UUID,
    competence_ids: list[uuid.UUID],
) -> None:
    """Diff existing competence links against the desired set and only
    touch rows that change.

    HRP-141: the previous implementation deleted every row then re-inserted
    the desired ones in the same flush. Whenever the desired set kept a
    competence that was already linked, SQLAlchemy emitted the INSERT
    before the matching DELETE, tripping the (parent_id, competence_id)
    UNIQUE constraint. Diffing keeps untouched links in place so editing a
    course or work experience without changing its competences just works.
    """
    result = await db.execute(
        select(link_model).where(getattr(link_model, fk_field) == parent_id)
    )
    existing: dict[uuid.UUID, Any] = {
        link.competence_id: link for link in result.scalars().all()
    }
    desired = set(competence_ids)

    for cid, link in existing.items():
        if cid not in desired:
            await db.delete(link)

    for cid in desired:
        if cid not in existing:
            db.add(link_model(**{fk_field: parent_id, "competence_id": cid}))


def _we_to_read(we: WorkExperience) -> dict:
    d = dict_from_model(we)
    d["competences"] = _competence_refs(we.competence_links)
    d["division_name"] = we.division.name if we.division else None
    d["position_title"] = we.position.title if we.position else d.get("title")
    d["duration"] = compute_duration(we.start_date, we.end_date)
    return d


async def _resolve_employment_refs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    division_id: uuid.UUID | None,
    position_id: uuid.UUID | None,
) -> tuple[Division | None, Position | None]:
    """Validate that a Division/Position pair belongs to the tenant.

    HRP-151 — the rebuilt Current Employment form requires both refs, so
    the validation has to surface a 400 instead of a 500 when a stale
    UUID is sent.
    """
    division: Division | None = None
    position: Position | None = None
    if division_id is not None:
        division = await db.get(Division, division_id)
        if not division or division.tenant_id != tenant_id:
            raise AppError("invalid_division_id", status.HTTP_400_BAD_REQUEST)
    if position_id is not None:
        position = await db.get(Position, position_id)
        if not position or position.tenant_id != tenant_id:
            raise AppError("invalid_position_id", status.HTTP_400_BAD_REQUEST)
    return division, position


def _course_to_read(course: Course) -> dict:
    d = dict_from_model(course)
    d["competences"] = _competence_refs(course.competence_links)
    return d


# ---------------------------------------------------------------------------
# GF1: Work Experience
# ---------------------------------------------------------------------------


async def list_work_experiences(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> list[dict]:
    await _get_employee(db, tenant_id, employee_id)
    result = await db.execute(
        select(WorkExperience)
        .options(
            selectinload(WorkExperience.competence_links),
            # HRP-163: ``division`` / ``position`` are no longer eager-
            # loaded on the model; opt in here so ``_we_to_read`` can
            # render names/titles without per-row lazy SELECTs.
            selectinload(WorkExperience.division),
            selectinload(WorkExperience.position),
        )
        .where(WorkExperience.employee_id == employee_id)
        .order_by(WorkExperience.start_date.desc(), WorkExperience.created_at.desc())
    )
    return [_we_to_read(we) for we in result.scalars().unique().all()]


async def create_work_experience(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    data: WorkExperienceCreate,
    current_user: User,
) -> dict:
    await _assert_child_scope(db, tenant_id, employee_id, current_user)
    _division, position = await _resolve_employment_refs(
        db, tenant_id, data.division_id, data.position_id
    )
    fields = data.model_dump(exclude={"competence_ids"})
    # HRP-151: title is legacy (project-style entries) but the DB column
    # is still queried by Work history widgets — backfill from the
    # canonical Position so reads stay populated.
    if not fields.get("title") and position is not None:
        fields["title"] = position.title
    we = WorkExperience(tenant_id=tenant_id, employee_id=employee_id, **fields)
    db.add(we)
    await db.flush()
    if data.competence_ids:
        await _sync_competence_links(
            db,
            WorkExperienceCompetence,
            "work_experience_id",
            we.id,
            data.competence_ids,
        )
    await db.commit()
    await db.refresh(we)
    # HRP-163: division / position are lazy=select after the model change;
    # refresh them explicitly so ``_we_to_read`` can render division_name
    # and position_title.
    await db.refresh(we, ["competence_links", "division", "position"])
    return _we_to_read(we)


async def update_work_experience(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    data: WorkExperienceUpdate,
    current_user: User,
) -> dict:
    we = await _get_child(db, WorkExperience, tenant_id, item_id, "Work experience")
    await _assert_child_scope(db, tenant_id, we.employee_id, current_user)
    updates = data.model_dump(exclude_unset=True, exclude={"competence_ids"})
    if "division_id" in updates or "position_id" in updates:
        new_div_id = updates.get("division_id", we.division_id)
        new_pos_id = updates.get("position_id", we.position_id)
        await _resolve_employment_refs(db, tenant_id, new_div_id, new_pos_id)
    for field, value in updates.items():
        setattr(we, field, value)
    if data.competence_ids is not None:
        await _sync_competence_links(
            db,
            WorkExperienceCompetence,
            "work_experience_id",
            we.id,
            data.competence_ids,
        )
    await db.commit()
    await db.refresh(we)
    await db.refresh(we, ["competence_links", "division", "position"])
    return _we_to_read(we)


async def delete_work_experience(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User,
) -> dict:
    return await _delete_child(
        db, WorkExperience, tenant_id, item_id, "Work experience", current_user
    )


# ---------------------------------------------------------------------------
# GF1: Previous Employment
# ---------------------------------------------------------------------------


async def list_previous_employments(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> list[dict]:
    return await _list_children(db, PreviousEmployment, tenant_id, employee_id)


async def create_previous_employment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    data: PreviousEmploymentCreate,
    current_user: User,
) -> dict:
    return await _create_child(
        db, PreviousEmployment, tenant_id, employee_id, data, current_user
    )


async def update_previous_employment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    data: PreviousEmploymentUpdate,
    current_user: User,
) -> dict:
    return await _update_child(
        db,
        PreviousEmployment,
        tenant_id,
        item_id,
        data,
        "Previous employment",
        current_user,
    )


async def delete_previous_employment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User,
) -> dict:
    return await _delete_child(
        db,
        PreviousEmployment,
        tenant_id,
        item_id,
        "Previous employment",
        current_user,
    )


# ---------------------------------------------------------------------------
# GF2: Education
# ---------------------------------------------------------------------------


async def list_education(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> list[dict]:
    return await _list_children(db, Education, tenant_id, employee_id)


async def create_education(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    data: EducationCreate,
    current_user: User,
) -> dict:
    # HRP-66: employees may manage their own Education entries.
    return await _create_child(
        db,
        Education,
        tenant_id,
        employee_id,
        data,
        current_user,
        allow_self_owner=True,
    )


async def update_education(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    data: EducationUpdate,
    current_user: User,
) -> dict:
    return await _update_child(
        db,
        Education,
        tenant_id,
        item_id,
        data,
        "Education",
        current_user,
        allow_self_owner=True,
    )


async def delete_education(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User,
) -> dict:
    return await _delete_child(
        db,
        Education,
        tenant_id,
        item_id,
        "Education",
        current_user,
        allow_self_owner=True,
    )


# ---------------------------------------------------------------------------
# GF2: Courses & Certifications
# ---------------------------------------------------------------------------


async def list_courses(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> list[dict]:
    await _get_employee(db, tenant_id, employee_id)
    result = await db.execute(
        select(Course)
        .options(selectinload(Course.competence_links))
        .where(Course.employee_id == employee_id)
        .order_by(Course.created_at.desc())
    )
    return [_course_to_read(c) for c in result.scalars().unique().all()]


async def create_course(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    data: CourseCreate,
    current_user: User,
) -> dict:
    # HRP-66: Courses live under the Education tab and inherit the same
    # self-service carve-out — employees may add/edit their own entries.
    await _assert_child_scope(
        db, tenant_id, employee_id, current_user, allow_self_owner=True
    )
    fields = data.model_dump(exclude={"competence_ids"})
    course = Course(tenant_id=tenant_id, employee_id=employee_id, **fields)
    db.add(course)
    await db.flush()
    if data.competence_ids:
        await _sync_competence_links(
            db, CourseCompetence, "course_id", course.id, data.competence_ids
        )
    await db.commit()
    await db.refresh(course)
    await db.refresh(course, ["competence_links"])
    return _course_to_read(course)


async def update_course(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    data: CourseUpdate,
    current_user: User,
) -> dict:
    course = await _get_child(db, Course, tenant_id, item_id, "Course")
    await _assert_child_scope(
        db, tenant_id, course.employee_id, current_user, allow_self_owner=True
    )
    updates = data.model_dump(exclude_unset=True, exclude={"competence_ids"})
    for field, value in updates.items():
        setattr(course, field, value)
    if data.competence_ids is not None:
        await _sync_competence_links(
            db, CourseCompetence, "course_id", course.id, data.competence_ids
        )
    await db.commit()
    await db.refresh(course)
    await db.refresh(course, ["competence_links"])
    return _course_to_read(course)


async def delete_course(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User,
) -> dict:
    return await _delete_child(
        db, Course, tenant_id, item_id, "Course", current_user, allow_self_owner=True
    )


# ---------------------------------------------------------------------------
# GF5: Compensation
# ---------------------------------------------------------------------------


async def list_compensations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    current_user: User,
) -> list[dict]:
    # HRP-221 (REDO): division managers can list Compensation only for
    # employees inside their managed subtree — mirrors the write-scope
    # check on the mutating endpoints. Admin / HR / platform_admin pass
    # through unconditionally.
    emp = await _get_employee(db, tenant_id, employee_id)
    await assert_employee_write_scope(db, current_user, emp)
    return await _list_children(db, Compensation, tenant_id, employee_id)


async def create_compensation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    data: CompensationCreate,
    current_user: User,
) -> dict:
    result = await _create_child(
        db, Compensation, tenant_id, employee_id, data, current_user
    )
    # HRP-221: serialize through Pydantic with mode="json" so any date/uuid
    # fields land as ISO strings in JSONB — mirrors update_compensation
    # (line 1302) and protects against the same "datetime is not JSON
    # serializable" 500 once the model picks up new fields.
    new_value = data.model_dump(
        include={"type", "amount", "currency"}, mode="json"
    )
    await _create_event(
        db,
        employee_id,
        "compensation_change",
        f"New {data.type}: {data.amount} {data.currency}",
        data.effective_date,
        new_value=new_value,
    )
    await db.commit()
    return result


async def update_compensation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    data: CompensationUpdate,
    current_user: User,
) -> dict:
    old = await _get_child(db, Compensation, tenant_id, item_id, "Compensation")
    old_vals = {"type": old.type, "amount": old.amount, "currency": old.currency}
    effective = (
        data.effective_date if data.effective_date is not None else old.effective_date
    )
    end = data.end_date if "end_date" in data.model_fields_set else old.end_date
    if end is not None and end < effective:
        raise AppError(
            "compensation_end_date_before_effective_date",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    result = await _update_child(
        db, Compensation, tenant_id, item_id, data, "Compensation", current_user
    )
    updates = data.model_dump(exclude_unset=True, mode="json")
    if "amount" in updates or "type" in updates:
        await _create_event(
            db,
            old.employee_id,
            "compensation_change",
            "Compensation updated",
            date.today(),
            old_value=old_vals,
            new_value=updates,
        )
        await db.commit()
    return result


async def delete_compensation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User,
) -> dict:
    item = await _get_child(db, Compensation, tenant_id, item_id, "Compensation")
    employee_id = item.employee_id
    result = await _delete_child(
        db, Compensation, tenant_id, item_id, "Compensation", current_user
    )
    await _create_event(
        db,
        employee_id,
        "compensation_change",
        "Compensation record removed",
        date.today(),
    )
    await db.commit()
    return result
