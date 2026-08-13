import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.core.s3 import get_presigned_url
from app.modules.assessment.models import (
    PDP,
    PDPComment,
    PDPItem,
    PDPItemMaterial,
    PDPVersion,
)
from app.modules.competence.material_overrides import (
    get_materials_for_specialization,
)
from app.modules.competence.models import SkillLevel
from app.modules.grade_system.models import GradeCompetenceLink, GradeSpecialization
from app.modules.storage.models import File

logger = logging.getLogger(__name__)

# HRP-16: simplified MVP graph — only the admin drives the plan, so the
# Awaiting approval / Approved stops are gone; Expired is now a pure UI cue
# (red deadline) rather than a real status.
#
# HRP-197: ``sent`` no longer permits a manual ``in_progress`` step — the
# plan auto-promotes when the owner ticks the first item. The only manual
# action from ``sent`` is ``cancel``.
#
# HRP-198: ``returned`` accepts ``review`` (admin or owner submission) and
# ``cancelled`` only; ``returned → sent`` is no longer allowed.
PDP_STATUS_TRANSITIONS = {
    "draft": ["sent", "cancelled"],
    "sent": ["cancelled"],
    "in_progress": ["review", "cancelled"],
    "review": ["done", "returned", "cancelled"],
    "returned": ["review", "cancelled"],
    "done": [],
    "cancelled": [],
}

PDP_FINALIZED_STATUSES = {"done", "cancelled"}

# HRP-38: hard cap on concurrent active development plans per employee.
# Mirrors the Assessments cap (HRP-37 REDO) — past three concurrent
# plans the employee's Development queue starts hiding work behind
# scrolling and reviewers cannot keep up. Tenant-level configuration is
# explicitly out of scope per the ticket.
MAX_ACTIVE_PDPS_PER_EMPLOYEE = 3

# HRP-189: spec/grade can only be changed while the plan is still in
# ``draft``. Sending or returning the plan locks the (specialization, grade)
# link so the employee's commitment stays stable.
PDP_GRADE_LOCKED_STATUSES = {
    "sent",
    "in_progress",
    "review",
    "returned",
    "done",
    "cancelled",
}


def _is_past_deadline(deadline: datetime | date | None) -> bool:
    """HRP-191/HRP-187: a deadline strictly before today (UTC) blocks the
    Draft→Sent and Review→Returned transitions. Same-day deadlines are
    still valid — the owner has the rest of the day to act on the plan."""
    if deadline is None:
        return False
    if isinstance(deadline, datetime):
        deadline_date = deadline.astimezone(timezone.utc).date()
    else:
        deadline_date = deadline
    return deadline_date < datetime.now(timezone.utc).date()


def _employee_full_name(p: PDP) -> str | None:
    employee = getattr(p, "employee", None)
    user = getattr(employee, "user", None) if employee is not None else None
    if not user:
        return None
    return f"{user.first_name} {user.last_name}".strip() or None


def _format_user_name(user) -> str | None:
    if not user:
        return None
    return f"{user.first_name} {user.last_name}".strip() or None


async def _resolve_reviewer_user_id(db: AsyncSession, p: PDP) -> uuid.UUID | None:
    """Reviewer user id = explicit reviewer if set, else the employee's
    division manager (as a ``users.id``). Used both to render the reviewer
    name and to gate the under-review item-toggle permission (HRP-130) —
    these two must agree, otherwise a manager who appears as the reviewer
    on screen can't actually accept items."""
    from app.modules.company.models import Division
    from app.modules.employee.models import Employee

    if p.reviewer_id:
        return p.reviewer_id

    employee = getattr(p, "employee", None)
    division_id = getattr(employee, "division_id", None) if employee else None
    if not division_id:
        return None

    division = await db.get(Division, division_id)
    if division is None or division.manager_id is None:
        return None

    manager_result = await db.execute(
        select(Employee).where(Employee.id == division.manager_id)
    )
    manager = manager_result.scalar_one_or_none()
    if manager is None or manager.user_id is None:
        return None
    return manager.user_id


async def _resolve_reviewer_name(db: AsyncSession, p: PDP) -> str | None:
    """Reviewer = explicit reviewer if set, else employee's division manager."""
    from app.modules.auth.models import User

    reviewer_user_id = await _resolve_reviewer_user_id(db, p)
    if reviewer_user_id is None:
        return None
    user = await db.get(User, reviewer_user_id)
    return _format_user_name(user)


def _pdp_to_read(p: PDP, reviewer_name: str | None = None) -> dict:
    employee = getattr(p, "employee", None)
    return {
        "id": p.id,
        "title": p.title,
        "employee_id": p.employee_id,
        "employee_name": _employee_full_name(p),
        # HRP-333: feed EmployeeSummaryLine on the Development list/detail.
        # ``employee_status`` — the PDP's own ``status`` is the plan state.
        "employee_position_title": employee.position_title if employee else None,
        "employee_status": employee.status if employee else None,
        "assessment_id": p.assessment_id,
        "author_id": p.author_id,
        "reviewer_id": p.reviewer_id,
        "reviewer_name": reviewer_name,
        "status": p.status,
        "specialization_id": p.specialization_id,
        "specialization_title": (
            p.specialization.title if p.specialization is not None else None
        ),
        "grade_id": p.grade_id,
        "grade_title": p.grade.title if p.grade is not None else None,
        "total_progress": p.total_progress,
        "deadline": p.deadline,
        "started_at": p.started_at,
        "finished_at": p.finished_at,
        "tenant_id": p.tenant_id,
        "created_at": p.created_at,
    }


async def _resolve_file_info(
    db: AsyncSession, file_id: uuid.UUID | None
) -> tuple[str | None, str | None]:
    """Return (file_url, file_name) for a file_id, or (None, None)."""
    if not file_id:
        return None, None
    f = await db.get(File, file_id)
    if not f:
        return None, None
    return get_presigned_url(f.path), f.original_name


def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


async def _build_items_snapshot(db: AsyncSession, pdp_id: uuid.UUID) -> list[dict]:
    """HRP-24: serialize items+materials at the moment a PDP enters review.

    Stored as JSONB on ``pdps.on_review_items_snapshot``. Only structural data
    is kept; presigned file URLs are re-resolved at read time so they don't
    expire while the plan sits in review.
    """
    result = await db.execute(
        select(PDPItem)
        .options(selectinload(PDPItem.materials))
        .where(PDPItem.pdp_id == pdp_id)
        .order_by(PDPItem.sort_index)
    )
    items = list(result.scalars().all())
    snapshot: list[dict] = []
    for item in items:
        materials: list[dict] = []
        for m in sorted(item.materials, key=lambda x: x.sort_index):
            materials.append(
                {
                    "id": str(m.id),
                    "material_id": str(m.material_id) if m.material_id else None,
                    "title": m.title,
                    "format": m.format,
                    "link": m.link,
                    "study_time": m.study_time,
                    "sort_index": m.sort_index,
                    "is_passed": m.is_passed,
                    "file_id": str(m.file_id) if m.file_id else None,
                }
            )
        snapshot.append(
            {
                "id": str(item.id),
                "competence_id": (
                    str(item.competence_id) if item.competence_id else None
                ),
                "title": item.title,
                "description": item.description,
                "sort_index": item.sort_index,
                "is_passed": item.is_passed,
                "entity_type": item.entity_type,
                "materials": materials,
            }
        )
    return snapshot


async def _items_from_snapshot(db: AsyncSession, snapshot: list[dict]) -> list[dict]:
    """HRP-24: rehydrate the JSON snapshot into the same shape live items use."""
    items: list[dict] = []
    for sit in snapshot:
        mats: list[dict] = []
        for m in sit.get("materials", []):
            file_uuid = _as_uuid(m.get("file_id"))
            m_url, m_name = await _resolve_file_info(db, file_uuid)
            mats.append(
                {
                    "id": _as_uuid(m.get("id")),
                    "material_id": _as_uuid(m.get("material_id")),
                    "title": m.get("title"),
                    "format": m.get("format"),
                    "link": m.get("link"),
                    "study_time": m.get("study_time"),
                    "sort_index": m.get("sort_index", 0),
                    "is_passed": bool(m.get("is_passed", False)),
                    "file_id": file_uuid,
                    "file_url": m_url,
                    "file_name": m_name,
                }
            )
        items.append(
            {
                "id": _as_uuid(sit.get("id")),
                "competence_id": _as_uuid(sit.get("competence_id")),
                "title": sit.get("title"),
                "description": sit.get("description"),
                "sort_index": sit.get("sort_index", 0),
                "is_passed": bool(sit.get("is_passed", False)),
                "entity_type": sit.get("entity_type") or "custom",
                "materials": mats,
            }
        )
    return items


async def _pdp_to_detail(
    db: AsyncSession,
    p: PDP,
    viewer_user_id: uuid.UUID | None = None,
) -> dict:
    reviewer_user_id = await _resolve_reviewer_user_id(db, p)
    reviewer_name: str | None = None
    if reviewer_user_id is not None:
        from app.modules.auth.models import User

        reviewer_user = await db.get(User, reviewer_user_id)
        reviewer_name = _format_user_name(reviewer_user)
    data = _pdp_to_read(p, reviewer_name=reviewer_name)

    # HRP-24: while the plan is under review, the assigned employee sees the
    # snapshot taken at the moment of transition rather than the live items.
    # Anyone else (admin, manager, the assessment author, …) keeps seeing the
    # current state so they can keep working on it.
    employee_user_id = getattr(getattr(p, "employee", None), "user_id", None)
    # HRP-13: owner = the user the PDP's employee is linked to.
    data["is_owner"] = (
        viewer_user_id is not None
        and employee_user_id is not None
        and viewer_user_id == employee_user_id
    )
    # HRP-130: ``is_reviewer`` mirrors the same fallback used for
    # ``reviewer_name`` (explicit reviewer OR division manager). The UI uses
    # it to enable the item checkbox for managers who appear as the implicit
    # reviewer; the backend gate in ``mark_item_passed`` resolves the same
    # way so the two never diverge.
    data["is_reviewer"] = (
        viewer_user_id is not None
        and reviewer_user_id is not None
        and viewer_user_id == reviewer_user_id
    )
    serve_snapshot = (
        p.status == "review"
        and p.on_review_items_snapshot is not None
        and viewer_user_id is not None
        and viewer_user_id == employee_user_id
    )

    if serve_snapshot:
        items = await _items_from_snapshot(db, p.on_review_items_snapshot or [])
    else:
        items = []
        for item in p.items:
            mats = []
            for m in item.materials:
                m_url, m_name = await _resolve_file_info(db, m.file_id)
                mats.append(
                    {
                        "id": m.id,
                        "material_id": m.material_id,
                        "title": m.title,
                        "format": m.format,
                        "link": m.link,
                        "study_time": m.study_time,
                        "sort_index": m.sort_index,
                        "is_passed": m.is_passed,
                        "file_id": m.file_id,
                        "file_url": m_url,
                        "file_name": m_name,
                    }
                )
            items.append(
                {
                    "id": item.id,
                    "competence_id": item.competence_id,
                    "title": item.title,
                    "description": item.description,
                    "sort_index": item.sort_index,
                    "is_passed": item.is_passed,
                    "entity_type": item.entity_type,
                    "materials": mats,
                }
            )
    data["items"] = items
    comments = []
    for c in p.comments:
        c_url, c_name = await _resolve_file_info(db, c.file_id)
        comments.append(
            {
                "id": c.id,
                "pdp_id": c.pdp_id,
                "item_id": c.item_id,
                "material_id": c.material_id,
                "user_id": c.user_id,
                "user_name": (
                    f"{c.user.first_name} {c.user.last_name}" if c.user else None
                ),
                "text": c.text,
                "file_id": c.file_id,
                "file_url": c_url,
                "file_name": c_name,
                "created_at": c.created_at,
            }
        )
    data["comments"] = comments
    return data


async def _get_pdp(db: AsyncSession, tenant_id: uuid.UUID, pdp_id: uuid.UUID) -> PDP:
    p = await db.get(PDP, pdp_id)
    if not p or p.tenant_id != tenant_id:
        raise AppError("pdp_not_found", status.HTTP_404_NOT_FOUND)
    return p


# --- CRUD ---


async def _attach_default_materials(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    competence_id: uuid.UUID,
    specialization_id: uuid.UUID | None,
    *,
    up_to_skill_level_sort_index: int | None = None,
) -> None:
    """Pre-fill PDPItemMaterial rows from get_materials_for_specialization.

    POS7: collection respects per-(material × specialization) overrides so a
    `hide` override skips a base material and an `add` override surfaces a
    competence material only for employees of the matching specialization.
    Falls back to plain base materials when `specialization_id` is None.

    HRP-189: when ``up_to_skill_level_sort_index`` is given (the PDP grade's
    target level for this competence), only materials at or below that level
    are seeded — the employee gets the target level plus every preceding
    one, never material from levels above their target.
    """
    materials = await get_materials_for_specialization(
        db, tenant_id, competence_id, specialization_id
    )
    if up_to_skill_level_sort_index is not None and materials:
        level_ids = {m.skill_level_id for m in materials}
        levels_q = await db.execute(
            select(SkillLevel).where(SkillLevel.id.in_(level_ids))
        )
        level_sort_by_id: dict[uuid.UUID, int] = {
            level.id: level.sort_index for level in levels_q.scalars().all()
        }
        materials = [
            m
            for m in materials
            if level_sort_by_id.get(m.skill_level_id, 0) <= up_to_skill_level_sort_index
        ]
    for sort_index, mat in enumerate(materials):
        db.add(
            PDPItemMaterial(
                item_id=item_id,
                material_id=mat.id,
                title=mat.title,
                format=mat.format,
                link=mat.link,
                study_time=mat.study_time,
                sort_index=sort_index,
            )
        )


async def _auto_generate_items_from_grade_link(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pdp_id: uuid.UUID,
    specialization_id: uuid.UUID | None,
    grade_id: uuid.UUID | None,
) -> None:
    """Pre-fill PDP items from competences attached to (specialization, grade).

    Each item also receives the per-specialization material set via
    `get_materials_for_specialization` so the override formula is the single
    source of truth for «which materials does this employee see».
    """
    if not specialization_id or not grade_id:
        return

    gs_result = await db.execute(
        select(GradeSpecialization)
        .options(
            selectinload(GradeSpecialization.competence_links).selectinload(
                GradeCompetenceLink.competence
            ),
            selectinload(GradeSpecialization.competence_links).selectinload(
                GradeCompetenceLink.skill_level
            ),
        )
        .where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == specialization_id,
            GradeSpecialization.grade_id == grade_id,
        )
    )
    gs = gs_result.scalar_one_or_none()
    if not gs:
        return

    for idx, link in enumerate(gs.competence_links):
        competence = link.competence
        item_title = competence.title if competence is not None else "Competence"
        item = PDPItem(
            pdp_id=pdp_id,
            competence_id=link.competence_id,
            title=item_title,
            sort_index=idx,
            entity_type="competence",
        )
        db.add(item)
        await db.flush()
        # HRP-189: cap materials at the target level for this (grade,
        # competence) pair so the employee studies their current level
        # plus every preceding one — not higher-grade material.
        target_level_sort = (
            link.skill_level.sort_index if link.skill_level is not None else None
        )
        await _attach_default_materials(
            db,
            tenant_id,
            item.id,
            link.competence_id,
            specialization_id,
            up_to_skill_level_sort_index=target_level_sort,
        )


async def _reload_pdp_for_read(
    db: AsyncSession, tenant_id: uuid.UUID, pdp_id: uuid.UUID
) -> dict:
    result = await db.execute(
        select(PDP).where(PDP.id == pdp_id, PDP.tenant_id == tenant_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise AppError("pdp_not_found", status.HTTP_404_NOT_FOUND)
    reviewer_name = await _resolve_reviewer_name(db, p)
    return _pdp_to_read(p, reviewer_name=reviewer_name)


async def create_pdp(
    db: AsyncSession, tenant_id: uuid.UUID, author_id: uuid.UUID, data
) -> dict:
    # HRP-38: cap concurrent active plans per employee. Active = status
    # not in ({done, cancelled}). The error wording matches the
    # Assessments cap (HRP-37) so the Create plan dialog can render the
    # same red banner.
    active_count_q = select(func.count(PDP.id)).where(
        PDP.tenant_id == tenant_id,
        PDP.employee_id == data.employee_id,
        PDP.status.notin_(PDP_FINALIZED_STATUSES),
    )
    active_count = (await db.execute(active_count_q)).scalar() or 0
    if active_count >= MAX_ACTIVE_PDPS_PER_EMPLOYEE:
        raise AppError(
            "pdp_active_limit_reached",
            status.HTTP_409_CONFLICT,
            active_count=active_count,
            limit=MAX_ACTIVE_PDPS_PER_EMPLOYEE,
        )

    p = PDP(
        tenant_id=tenant_id,
        title=data.title,
        employee_id=data.employee_id,
        assessment_id=data.assessment_id,
        author_id=author_id,
        reviewer_id=data.reviewer_id,
        specialization_id=data.specialization_id,
        grade_id=data.grade_id,
        deadline=data.deadline,
    )
    db.add(p)
    await db.flush()

    await _auto_generate_items_from_grade_link(
        db,
        tenant_id,
        p.id,
        data.specialization_id,
        data.grade_id,
    )

    await db.commit()
    return await _reload_pdp_for_read(db, tenant_id, p.id)


async def _recompute_items_for_grade_change(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pdp_id: uuid.UUID,
    specialization_id: uuid.UUID | None,
    grade_id: uuid.UUID | None,
) -> None:
    """HRP-189: rebuild the items + materials from scratch when the
    (specialization, grade) link changes.

    Because the link can only be changed while the plan is still in
    ``draft`` (no items are passed yet), wiping everything is safe — we
    drop the old set, regenerate the auto-items from the new (spec, grade)
    pair, and reset ``total_progress`` to zero. The dialog warns the user
    that "All items will be replaced with the new specialization & grade set."
    so this matches the documented contract.
    """
    pdp_row = await db.get(PDP, pdp_id)
    if pdp_row is None or pdp_row.status != "draft":
        # Hard fail-fast — any call from a non-draft state would silently
        # nuke completed work. Callers (router transitions, update_pdp)
        # already gate on draft; this assertion catches regressions.
        raise AppError(
            "pdp_grade_replace_draft_only",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    existing_result = await db.execute(select(PDPItem).where(PDPItem.pdp_id == pdp_id))
    for item in existing_result.scalars().all():
        await db.delete(item)
    await db.flush()

    if specialization_id and grade_id:
        await _auto_generate_items_from_grade_link(
            db, tenant_id, pdp_id, specialization_id, grade_id
        )
    await db.flush()

    pdp = await db.get(PDP, pdp_id)
    if pdp is not None:
        pdp.total_progress = 0


async def update_pdp(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pdp_id: uuid.UUID,
    data,
) -> dict:
    p = await _get_pdp(db, tenant_id, pdp_id)

    if p.status in PDP_FINALIZED_STATUSES:
        raise AppError(
            "pdp_not_editable_status",
            status.HTTP_409_CONFLICT,
            pdp_status=p.status,
        )

    fields = data.model_dump(exclude_unset=True)

    spec_changed = (
        "specialization_id" in fields
        and fields["specialization_id"] != p.specialization_id
    )
    grade_changed = "grade_id" in fields and fields["grade_id"] != p.grade_id
    grade_link_changed = spec_changed or grade_changed

    if grade_link_changed and p.status in PDP_GRADE_LOCKED_STATUSES:
        raise AppError(
            "pdp_grade_locked_status",
            status.HTTP_409_CONFLICT,
            pdp_status=p.status,
        )

    if "title" in fields:
        p.title = fields["title"]
    if "deadline" in fields:
        p.deadline = fields["deadline"]
    if "specialization_id" in fields:
        p.specialization_id = fields["specialization_id"]
    if "grade_id" in fields:
        p.grade_id = fields["grade_id"]

    if grade_link_changed:
        await db.flush()
        await _recompute_items_for_grade_change(
            db,
            tenant_id,
            pdp_id,
            p.specialization_id,
            p.grade_id,
        )

    await db.commit()
    return await _reload_pdp_for_read(db, tenant_id, pdp_id)


async def list_pdps(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID | None = None,
    visible_employee_ids: set[uuid.UUID] | None = None,
    *,
    hide_drafts: bool = False,
) -> list[dict]:
    query = (
        select(PDP).where(PDP.tenant_id == tenant_id).order_by(PDP.created_at.desc())
    )
    if visible_employee_ids is not None:
        if not visible_employee_ids:
            return []
        query = query.where(PDP.employee_id.in_(visible_employee_ids))
    if employee_id:
        query = query.where(PDP.employee_id == employee_id)
    # HRP-19: a non-admin viewer (employee, manager) sees plans that are
    # actually being acted on — drafts are still being authored and should
    # stay hidden until the admin sends them.
    if hide_drafts:
        query = query.where(PDP.status != "draft")
    result = await db.execute(query)
    pdps = result.scalars().all()
    out: list[dict] = []
    for p in pdps:
        reviewer_name = await _resolve_reviewer_name(db, p)
        out.append(_pdp_to_read(p, reviewer_name=reviewer_name))
    return out


async def get_pdp_detail(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pdp_id: uuid.UUID,
    viewer_user_id: uuid.UUID | None = None,
) -> dict:
    result = await db.execute(
        select(PDP)
        .options(
            selectinload(PDP.items).selectinload(PDPItem.materials),
            selectinload(PDP.comments),
        )
        .where(PDP.id == pdp_id, PDP.tenant_id == tenant_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise AppError("pdp_not_found", status.HTTP_404_NOT_FOUND)
    return await _pdp_to_detail(db, p, viewer_user_id=viewer_user_id)


PDP_VERSION_STATUSES = {"sent", "review", "returned", "done"}


async def _create_version_snapshot(
    db: AsyncSession, pdp_id: uuid.UUID, pdp_status: str
) -> None:
    """Create a snapshot of the PDP at the current state."""
    result = await db.execute(
        select(PDP)
        .options(
            selectinload(PDP.items).selectinload(PDPItem.materials),
            selectinload(PDP.comments),
        )
        .where(PDP.id == pdp_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        return

    # Determine next version number
    count_result = await db.execute(
        select(func.count(PDPVersion.id)).where(PDPVersion.pdp_id == pdp_id)
    )
    next_version = (count_result.scalar() or 0) + 1

    snapshot = await _pdp_to_detail(db, p)
    # Convert datetimes to strings for JSON serialization
    import json
    from datetime import date, datetime

    def json_serializer(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    # Round-trip through JSON to ensure clean serialization
    snapshot = json.loads(json.dumps(snapshot, default=json_serializer))

    version = PDPVersion(
        pdp_id=pdp_id,
        version_number=next_version,
        status=pdp_status,
        snapshot=snapshot,
    )
    db.add(version)


async def change_pdp_status(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pdp_id: uuid.UUID,
    new_status: str,
    *,
    bypass_transition_check: bool = False,
) -> dict:
    p = await _get_pdp(db, tenant_id, pdp_id)

    # HRP-19: the plan owner can submit ``returned -> review`` even though the
    # generic transition map only allows admins to bounce a returned plan back
    # to ``sent`` or ``cancelled``. The router validates the owner case and
    # then asks us to skip the strict check; everyone else still goes through
    # the map.
    if not bypass_transition_check:
        allowed = PDP_STATUS_TRANSITIONS.get(p.status, [])
        if new_status not in allowed:
            raise AppError(
                "pdp_invalid_transition",
                status.HTTP_400_BAD_REQUEST,
                from_status=p.status,
                to_status=new_status,
                allowed=allowed,
            )

    # HRP-130: a plan in ``review`` can only be returned to the employee
    # if there is still work left for them — i.e. at least one item is
    # unchecked. Once the admin/reviewer has accepted every item, the only
    # sensible action is to complete the plan. The UI hides the Return
    # button in that case; this guard catches privileged callers that hit
    # the API directly.
    if p.status == "review" and new_status == "returned":
        items_result = await db.execute(select(PDPItem).where(PDPItem.pdp_id == pdp_id))
        items = list(items_result.scalars().all())
        if items and all(it.is_passed for it in items):
            raise AppError(
                "pdp_all_items_accepted",
                status.HTTP_409_CONFLICT,
            )

    # HRP-12: don't let the admin "send" an empty plan — the employee would
    # land on an unactionable card. Every item must also carry at least one
    # material so the assignee actually has something to study.
    if p.status == "draft" and new_status == "sent":
        items_result = await db.execute(
            select(PDPItem)
            .options(selectinload(PDPItem.materials))
            .where(PDPItem.pdp_id == pdp_id)
        )
        items = list(items_result.scalars().all())
        if not items:
            raise AppError(
                "pdp_no_items_to_send",
                status.HTTP_409_CONFLICT,
            )
        if any(not it.materials for it in items):
            raise AppError(
                "pdp_item_missing_material_send",
                status.HTTP_409_CONFLICT,
            )
        # HRP-191: the admin can't launch a plan whose deadline has already
        # elapsed — the employee would land on an overdue plan from minute
        # one. Same-day deadlines are still accepted.
        if _is_past_deadline(p.deadline):
            raise AppError(
                "assessment_deadline_in_past",
                status.HTTP_400_BAD_REQUEST,
            )

    # HRP-187: returning a plan from review to the owner requires every
    # item to carry at least one material — same contract Send already
    # enforces on Draft → Sent. Without this gate the admin could add a
    # bare item during review and immediately bounce the plan back, leaving
    # the owner with an unactionable card. The 409 mirrors the Draft → Sent
    # error so the UI can surface the same tooltip.
    if p.status == "review" and new_status == "returned":
        items_result = await db.execute(
            select(PDPItem)
            .options(selectinload(PDPItem.materials))
            .where(PDPItem.pdp_id == pdp_id)
        )
        items_for_return = list(items_result.scalars().all())
        if any(not it.materials for it in items_for_return):
            raise AppError(
                "pdp_item_missing_material_return",
                status.HTTP_409_CONFLICT,
            )

    # HRP-187: a past deadline also blocks Review → Returned. The UI keeps
    # the Return button enabled (parity with Assessments and Talent market)
    # and surfaces this 400 as a snackbar error.
    if (
        p.status == "review"
        and new_status == "returned"
        and _is_past_deadline(p.deadline)
    ):
        raise AppError(
            "assessment_deadline_in_past",
            status.HTTP_400_BAD_REQUEST,
        )

    previous_status = p.status
    p.status = new_status

    if new_status == "in_progress" and not p.started_at:
        p.started_at = datetime.now(timezone.utc)
    elif new_status in PDP_FINALIZED_STATUSES:
        # HRP-132: terminal-status timestamp drives the "Done at" /
        # "Cancelled at" label on PDP cards and the details page. We reuse
        # ``finished_at`` for both ``done`` and ``cancelled`` — the status
        # tells the renderer which copy to show.
        p.finished_at = datetime.now(timezone.utc)

    # HRP-24: freeze items when entering review; clear the snapshot once the
    # plan moves on so the employee starts seeing live data again.
    if previous_status != "review" and new_status == "review":
        p.on_review_items_snapshot = await _build_items_snapshot(db, pdp_id)
    elif previous_status == "review" and new_status != "review":
        p.on_review_items_snapshot = None

    # GF12: Auto-save version on key transitions
    if new_status in PDP_VERSION_STATUSES:
        await _create_version_snapshot(db, pdp_id, new_status)

    await db.commit()

    notifier = None
    if previous_status == "draft" and new_status == "sent":
        notifier = _notify_pdp_sent
    elif new_status == "review":
        # HRP-244: notify the reviewer that they have a plan to evaluate.
        notifier = _notify_pdp_review_submitted
    elif new_status == "returned":
        notifier = _notify_pdp_returned
    elif new_status == "done":
        notifier = _notify_pdp_done
    elif new_status == "cancelled" and previous_status in {
        "sent",
        "in_progress",
        "review",
        "returned",
    }:
        # HRP-244: silent on draft → cancelled (the employee never saw the plan).
        notifier = _notify_pdp_cancelled

    if notifier is not None:
        # i18n F4: read the tenant default once per transition — each
        # notified recipient layers its own User.language on top of it.
        from app.modules.company.models import Tenant

        tenant = await db.get(Tenant, p.tenant_id) if p.tenant_id else None
        await notifier(db, p, tenant_default=tenant.default_locale if tenant else None)

    return await _reload_pdp_for_read(db, tenant_id, pdp_id)


def _pdp_owner_user(p: PDP):
    employee = getattr(p, "employee", None)
    return getattr(employee, "user", None) if employee is not None else None


def _employee_display_name(user) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.email


async def _notify_pdp_sent(
    db: AsyncSession, p: PDP, *, tenant_default: str | None = None
) -> None:
    """Email the employee that their development plan was sent for execution."""
    try:
        from app.core.email import enqueue_email
        from app.core.email_templates import render_pdp_sent_email
        from app.core.i18n import format_date, resolve_locale

        user = _pdp_owner_user(p)
        if not user or not user.email:
            return

        employee_name = _employee_display_name(user)
        locale = resolve_locale(
            user_language=user.language, tenant_default=tenant_default
        )
        # i18n F7: deadline is rendered in the recipient's locale (the old
        # strftime("%B %d, %Y") hardcoded English month names).
        deadline = format_date(p.deadline, locale) if p.deadline else None
        subject, body = render_pdp_sent_email(
            employee_name,
            deadline=deadline,
            pdp_title=p.title,
            locale=locale,
        )
        enqueue_email(
            user.email,
            subject,
            body,
            tenant_id=str(p.tenant_id),
            template_code="pdp.sent",
        )
    except Exception:
        # Email delivery is best-effort; the status change must not roll back.
        # Log so silent failures still produce a trace for ops.
        logger.exception("PDP sent notification failed for pdp_id=%s", p.id)


async def _notify_pdp_review_submitted(
    db: AsyncSession, p: PDP, *, tenant_default: str | None = None
) -> None:
    """HRP-244: tell the reviewer that the owner has submitted the plan."""
    try:
        from app.core.email import enqueue_email
        from app.core.email_templates import render_pdp_review_submitted_email
        from app.core.i18n import resolve_locale
        from app.modules.auth.models import User

        owner = _pdp_owner_user(p)
        if not owner:
            return
        reviewer_user_id = await _resolve_reviewer_user_id(db, p)
        if reviewer_user_id is None:
            return
        # HRP-244 review fix: when the owner manages their own division the
        # manager-fallback resolves them as the reviewer; skip the self-mail
        # to mirror the done / cancelled paths.
        if reviewer_user_id == getattr(owner, "id", None):
            return
        reviewer = await db.get(User, reviewer_user_id)
        if not reviewer or not reviewer.email:
            return

        employee_name = _employee_display_name(owner)
        subject, body = render_pdp_review_submitted_email(
            employee_name,
            pdp_title=p.title,
            locale=resolve_locale(
                user_language=reviewer.language, tenant_default=tenant_default
            ),
        )
        enqueue_email(
            reviewer.email,
            subject,
            body,
            tenant_id=str(p.tenant_id),
            template_code="pdp.review_submitted",
        )
    except Exception:
        logger.exception("PDP review-submitted notification failed for pdp_id=%s", p.id)


async def _notify_pdp_returned(
    db: AsyncSession, p: PDP, *, tenant_default: str | None = None
) -> None:
    """HRP-244: tell the owner that the reviewer bounced the plan back."""
    try:
        from app.core.email import enqueue_email
        from app.core.email_templates import render_pdp_returned_email
        from app.core.i18n import resolve_locale

        user = _pdp_owner_user(p)
        if not user or not user.email:
            return

        employee_name = _employee_display_name(user)
        subject, body = render_pdp_returned_email(
            employee_name,
            pdp_title=p.title,
            locale=resolve_locale(
                user_language=user.language, tenant_default=tenant_default
            ),
        )
        enqueue_email(
            user.email,
            subject,
            body,
            tenant_id=str(p.tenant_id),
            template_code="pdp.returned",
        )
    except Exception:
        logger.exception("PDP returned notification failed for pdp_id=%s", p.id)


async def _notify_pdp_done(
    db: AsyncSession, p: PDP, *, tenant_default: str | None = None
) -> None:
    """HRP-244: notify both the owner and the reviewer that the plan is complete."""
    try:
        from app.core.email import enqueue_email
        from app.core.email_templates import (
            render_pdp_done_to_employee_email,
            render_pdp_done_to_reviewer_email,
        )
        from app.core.i18n import resolve_locale
        from app.modules.auth.models import User

        owner = _pdp_owner_user(p)
        # HRP-584: _format_user_name returns None for a missing owner AND
        # for a blank first/last name — both route the templates to their
        # nameless copy instead of leaking the login email as a name.
        owner_display = _format_user_name(owner)
        if owner and owner.email:
            # i18n F4: two recipients, two independent locales.
            owner_locale = resolve_locale(
                user_language=owner.language, tenant_default=tenant_default
            )
            subject, body = render_pdp_done_to_employee_email(
                owner_display,
                pdp_title=p.title,
                locale=owner_locale,
            )
            enqueue_email(
                owner.email,
                subject,
                body,
                tenant_id=str(p.tenant_id),
                template_code="pdp.done.employee",
            )

        reviewer_user_id = await _resolve_reviewer_user_id(db, p)
        if reviewer_user_id is None:
            return
        # Don't double-notify when the reviewer is also the plan owner.
        if owner and reviewer_user_id == owner.id:
            return
        reviewer = await db.get(User, reviewer_user_id)
        if not reviewer or not reviewer.email:
            return
        # HRP-244 review fix: when the owner record is missing (User row
        # deactivated / deleted) the reviewer still gets a notice so the
        # lifecycle event is not silently lost; HRP-584 — the template
        # renders its nameless copy variant in that case.
        reviewer_locale = resolve_locale(
            user_language=reviewer.language, tenant_default=tenant_default
        )
        subject, body = render_pdp_done_to_reviewer_email(
            owner_display,
            pdp_title=p.title,
            locale=reviewer_locale,
        )
        enqueue_email(
            reviewer.email,
            subject,
            body,
            tenant_id=str(p.tenant_id),
            template_code="pdp.done.reviewer",
        )
    except Exception:
        logger.exception("PDP done notification failed for pdp_id=%s", p.id)


async def _notify_pdp_cancelled(
    db: AsyncSession, p: PDP, *, tenant_default: str | None = None
) -> None:
    """HRP-244: notify both the owner and the reviewer about a post-launch cancel."""
    try:
        from app.core.email import enqueue_email
        from app.core.email_templates import (
            render_pdp_cancelled_to_employee_email,
            render_pdp_cancelled_to_reviewer_email,
        )
        from app.core.i18n import resolve_locale
        from app.modules.auth.models import User

        owner = _pdp_owner_user(p)
        # HRP-584: missing owner or blank name -> nameless copy (see
        # _notify_pdp_done).
        owner_display = _format_user_name(owner)
        if owner and owner.email:
            # i18n F4: two recipients, two independent locales.
            owner_locale = resolve_locale(
                user_language=owner.language, tenant_default=tenant_default
            )
            subject, body = render_pdp_cancelled_to_employee_email(
                owner_display,
                pdp_title=p.title,
                locale=owner_locale,
            )
            enqueue_email(
                owner.email,
                subject,
                body,
                tenant_id=str(p.tenant_id),
                template_code="pdp.cancelled.employee",
            )

        reviewer_user_id = await _resolve_reviewer_user_id(db, p)
        if reviewer_user_id is None:
            return
        if owner and reviewer_user_id == owner.id:
            return
        reviewer = await db.get(User, reviewer_user_id)
        if not reviewer or not reviewer.email:
            return
        # HRP-584: a missing owner renders the nameless copy variant.
        reviewer_locale = resolve_locale(
            user_language=reviewer.language, tenant_default=tenant_default
        )
        subject, body = render_pdp_cancelled_to_reviewer_email(
            owner_display,
            pdp_title=p.title,
            locale=reviewer_locale,
        )
        enqueue_email(
            reviewer.email,
            subject,
            body,
            tenant_id=str(p.tenant_id),
            template_code="pdp.cancelled.reviewer",
        )
    except Exception:
        logger.exception("PDP cancelled notification failed for pdp_id=%s", p.id)


# --- Items ---


def _ensure_pdp_editable(p: PDP) -> None:
    if p.status in PDP_FINALIZED_STATUSES:
        raise AppError(
            "pdp_not_editable_status",
            status.HTTP_409_CONFLICT,
            pdp_status=p.status,
        )


async def add_item(
    db: AsyncSession, tenant_id: uuid.UUID, pdp_id: uuid.UUID, data
) -> dict:
    p = await _get_pdp(db, tenant_id, pdp_id)
    _ensure_pdp_editable(p)

    # HRP-201: every new item lands at the bottom of the list regardless of
    # whatever ``sort_index`` the client may have sent — clients used to ship
    # ``0`` and the resulting collisions made the order shuffle whenever an
    # item was toggled.
    max_sort_result = await db.execute(
        select(func.max(PDPItem.sort_index)).where(PDPItem.pdp_id == pdp_id)
    )
    current_max = max_sort_result.scalar()
    next_sort = (current_max + 1) if current_max is not None else 0

    item = PDPItem(
        pdp_id=pdp_id,
        competence_id=data.competence_id,
        title=data.title,
        description=data.description,
        sort_index=next_sort,
        entity_type=data.entity_type,
    )
    db.add(item)
    await db.flush()
    # HRP-199: adding an item changes the progress denominator (e.g. 1/2 → 1/3)
    # so the cached ``total_progress`` value goes stale unless we recompute.
    await _recompute_progress(db, pdp_id)
    await db.commit()
    await db.refresh(item)
    return {
        "id": item.id,
        "competence_id": item.competence_id,
        "title": item.title,
        "description": item.description,
        "sort_index": item.sort_index,
        "is_passed": item.is_passed,
        "entity_type": item.entity_type,
        "materials": [],
    }


def _ensure_item_editable(item: PDPItem) -> None:
    """HRP-200: a passed item is read-only until an admin/reviewer clears
    the checkbox. This keeps the recorded growth intact and prevents an
    accidental edit from rewriting history."""
    if item.is_passed:
        raise AppError(
            "pdp_item_passed_read_only",
            status.HTTP_403_FORBIDDEN,
        )


async def update_item(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pdp_id: uuid.UUID,
    item_id: uuid.UUID,
    data,
) -> dict:
    p = await _get_pdp(db, tenant_id, pdp_id)
    _ensure_pdp_editable(p)
    result = await db.execute(
        select(PDPItem)
        .options(selectinload(PDPItem.materials))
        .where(PDPItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item or item.pdp_id != pdp_id:
        raise AppError("pdp_item_not_found", status.HTTP_404_NOT_FOUND)
    _ensure_item_editable(item)

    fields = data.model_dump(exclude_unset=True)
    if "title" in fields:
        item.title = fields["title"]
    if "description" in fields:
        item.description = fields["description"]
    await db.commit()
    mats: list[dict] = []
    for m in item.materials:
        m_url, m_name = await _resolve_file_info(db, m.file_id)
        mats.append(
            {
                "id": m.id,
                "material_id": m.material_id,
                "title": m.title,
                "format": m.format,
                "link": m.link,
                "study_time": m.study_time,
                "sort_index": m.sort_index,
                "is_passed": m.is_passed,
                "file_id": m.file_id,
                "file_url": m_url,
                "file_name": m_name,
            }
        )
    return {
        "id": item.id,
        "competence_id": item.competence_id,
        "title": item.title,
        "description": item.description,
        "sort_index": item.sort_index,
        "is_passed": item.is_passed,
        "entity_type": item.entity_type,
        "materials": mats,
    }


async def delete_item(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pdp_id: uuid.UUID,
    item_id: uuid.UUID,
) -> None:
    p = await _get_pdp(db, tenant_id, pdp_id)
    _ensure_pdp_editable(p)
    result = await db.execute(
        select(PDPItem)
        .options(selectinload(PDPItem.materials))
        .where(PDPItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item or item.pdp_id != pdp_id:
        raise AppError("pdp_item_not_found", status.HTTP_404_NOT_FOUND)
    _ensure_item_editable(item)
    await db.delete(item)
    await db.flush()
    await _recompute_progress(db, pdp_id)
    await db.commit()


async def _recompute_progress(db: AsyncSession, pdp_id: uuid.UUID) -> None:
    items_result = await db.execute(select(PDPItem).where(PDPItem.pdp_id == pdp_id))
    items = list(items_result.scalars().all())
    total = len(items)
    passed = sum(1 for i in items if i.is_passed)
    progress = int((passed / total * 100) if total > 0 else 0)
    pdp = await db.get(PDP, pdp_id)
    if pdp is not None:
        pdp.total_progress = progress


async def reorder_items(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pdp_id: uuid.UUID,
    ordered_ids: list[uuid.UUID],
) -> list[dict]:
    p = await _get_pdp(db, tenant_id, pdp_id)
    _ensure_pdp_editable(p)
    items_result = await db.execute(select(PDPItem).where(PDPItem.pdp_id == pdp_id))
    items = {i.id: i for i in items_result.scalars().all()}
    missing = [iid for iid in ordered_ids if iid not in items]
    if missing or len(ordered_ids) != len(items):
        raise AppError(
            "pdp_reorder_incomplete",
            status.HTTP_400_BAD_REQUEST,
        )
    for idx, iid in enumerate(ordered_ids):
        items[iid].sort_index = idx
    await db.commit()
    return await _list_items_for_pdp(db, pdp_id)


async def _list_items_for_pdp(db: AsyncSession, pdp_id: uuid.UUID) -> list[dict]:
    result = await db.execute(
        select(PDPItem)
        .options(selectinload(PDPItem.materials))
        .where(PDPItem.pdp_id == pdp_id)
        .order_by(PDPItem.sort_index)
    )
    items = list(result.scalars().all())
    out: list[dict] = []
    for item in items:
        mats: list[dict] = []
        for m in item.materials:
            m_url, m_name = await _resolve_file_info(db, m.file_id)
            mats.append(
                {
                    "id": m.id,
                    "material_id": m.material_id,
                    "title": m.title,
                    "format": m.format,
                    "link": m.link,
                    "study_time": m.study_time,
                    "sort_index": m.sort_index,
                    "is_passed": m.is_passed,
                    "file_id": m.file_id,
                    "file_url": m_url,
                    "file_name": m_name,
                }
            )
        out.append(
            {
                "id": item.id,
                "competence_id": item.competence_id,
                "title": item.title,
                "description": item.description,
                "sort_index": item.sort_index,
                "is_passed": item.is_passed,
                "entity_type": item.entity_type,
                "materials": mats,
            }
        )
    return out


# HRP-13/19/20/130: marking an item is gated by both *who* is acting and
# *what state* the plan is in.
#
# * Owner (the employee the plan belongs to): can MARK ``is_passed=True``
#   while the plan is in ``sent``/``in_progress``/``returned``. HRP-20:
#   completion is one-way — once an item is passed, the owner cannot
#   clear it (the checkbox is meant to record actual progress, not a
#   toggle). The frontend disables the box once it's ticked; the API
#   returns 409 on bypass attempts.
# * Admin / Platform admin / the PDP's assigned reviewer: can toggle
#   items both ways while the plan is in ``review`` (HRP-130 — they
#   need this to mark which items they accept before clicking "Return").
# ``draft``/``done``/``cancelled`` block everyone.
PDP_OWNER_PASS_STATUSES = {"sent", "in_progress", "returned"}
PDP_REVIEWER_PASS_STATUSES = {"review"}


async def mark_item_passed(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pdp_id: uuid.UUID,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    is_passed: bool = True,
    is_admin: bool = False,
) -> dict:
    p = await _get_pdp(db, tenant_id, pdp_id)

    employee_user_id = getattr(getattr(p, "employee", None), "user_id", None)
    is_owner = employee_user_id is not None and employee_user_id == user_id
    # HRP-130: a manager who shows up as the implicit reviewer (division
    # manager fallback) must also be allowed to toggle items in ``review``.
    # Mirror the same resolution the UI uses to render the reviewer name.
    reviewer_user_id = await _resolve_reviewer_user_id(db, p)
    is_pdp_reviewer = reviewer_user_id is not None and reviewer_user_id == user_id

    if p.status in PDP_OWNER_PASS_STATUSES:
        if not is_owner:
            raise AppError(
                "pdp_only_owner_can_mark_items",
                status.HTTP_403_FORBIDDEN,
            )
    elif p.status in PDP_REVIEWER_PASS_STATUSES:
        if not (is_admin or is_pdp_reviewer):
            raise AppError(
                "pdp_only_reviewer_can_mark_items",
                status.HTTP_403_FORBIDDEN,
            )
    else:
        # ``draft``/``done``/``cancelled`` — covers HRP-17 (terminal) and
        # the "not yet started" guard for draft in one place.
        raise AppError(
            "pdp_cannot_mark_items_status",
            status.HTTP_409_CONFLICT,
            pdp_status=p.status,
        )

    item = await db.get(PDPItem, item_id)
    if not item or item.pdp_id != pdp_id:
        raise AppError("pdp_item_not_found", status.HTTP_404_NOT_FOUND)

    # HRP-19 (REDO) overrides the earlier HRP-20 one-way guard: the owner
    # must be able to uncheck and re-check items while the plan is in
    # ``sent``/``in_progress``/``returned``. HRP-20's own step 3 ("after
    # unticking, the plan stays In Progress") already presumes uncheck
    # works; the one-way restriction was incompatible with that. The
    # auto-promotion below still fires on the first ``True`` tick, and
    # unticking never demotes the plan back to ``sent``.
    item.is_passed = is_passed

    # HRP-20: the first time the OWNER ticks an item while the plan is in
    # ``sent``, the plan auto-promotes to ``in_progress`` (and records
    # started_at). Reviewer/admin toggles in ``review`` never move the
    # plan back to ``in_progress``.
    if p.status == "sent" and is_passed and is_owner:
        p.status = "in_progress"
        if not p.started_at:
            p.started_at = datetime.now(timezone.utc)

    await db.commit()

    # Recalculate progress
    result = await db.execute(select(PDPItem).where(PDPItem.pdp_id == pdp_id))
    items = result.scalars().all()
    total = len(items)
    passed = sum(1 for i in items if i.is_passed)
    progress = int((passed / total * 100) if total > 0 else 0)

    pdp = await db.get(PDP, pdp_id)
    if pdp is None:
        raise AppError("pdp_not_found", status.HTTP_404_NOT_FOUND)
    pdp.total_progress = progress
    await db.commit()

    return {"item_id": item_id, "is_passed": is_passed, "total_progress": progress}


# --- Materials ---


async def add_material(
    db: AsyncSession, tenant_id: uuid.UUID, pdp_id: uuid.UUID, item_id: uuid.UUID, data
) -> dict:
    p = await _get_pdp(db, tenant_id, pdp_id)
    _ensure_pdp_editable(p)
    item = await db.get(PDPItem, item_id)
    if not item or item.pdp_id != pdp_id:
        raise AppError("pdp_item_not_found", status.HTTP_404_NOT_FOUND)
    _ensure_item_editable(item)

    mat = PDPItemMaterial(
        item_id=item_id,
        material_id=data.material_id,
        title=data.title,
        format=data.format,
        link=data.link,
        study_time=data.study_time,
        sort_index=data.sort_index,
        file_id=getattr(data, "file_id", None),
    )
    db.add(mat)
    await db.commit()
    await db.refresh(mat)
    f_url, f_name = await _resolve_file_info(db, mat.file_id)
    return {
        "id": mat.id,
        "material_id": mat.material_id,
        "title": mat.title,
        "format": mat.format,
        "link": mat.link,
        "study_time": mat.study_time,
        "sort_index": mat.sort_index,
        "is_passed": mat.is_passed,
        "file_id": mat.file_id,
        "file_url": f_url,
        "file_name": f_name,
    }


async def update_material(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pdp_id: uuid.UUID,
    item_id: uuid.UUID,
    material_id: uuid.UUID,
    data,
) -> dict:
    p = await _get_pdp(db, tenant_id, pdp_id)
    _ensure_pdp_editable(p)
    item = await db.get(PDPItem, item_id)
    if not item or item.pdp_id != pdp_id:
        raise AppError("pdp_item_not_found", status.HTTP_404_NOT_FOUND)
    _ensure_item_editable(item)
    mat = await db.get(PDPItemMaterial, material_id)
    if not mat or mat.item_id != item_id:
        raise AppError("pdp_material_not_found", status.HTTP_404_NOT_FOUND)

    fields = data.model_dump(exclude_unset=True)
    for attr in ("title", "format", "link", "study_time", "file_id"):
        if attr in fields:
            setattr(mat, attr, fields[attr])
    await db.commit()
    await db.refresh(mat)
    f_url, f_name = await _resolve_file_info(db, mat.file_id)
    return {
        "id": mat.id,
        "material_id": mat.material_id,
        "title": mat.title,
        "format": mat.format,
        "link": mat.link,
        "study_time": mat.study_time,
        "sort_index": mat.sort_index,
        "is_passed": mat.is_passed,
        "file_id": mat.file_id,
        "file_url": f_url,
        "file_name": f_name,
    }


async def delete_material(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pdp_id: uuid.UUID,
    item_id: uuid.UUID,
    material_id: uuid.UUID,
) -> None:
    p = await _get_pdp(db, tenant_id, pdp_id)
    _ensure_pdp_editable(p)
    item = await db.get(PDPItem, item_id)
    if not item or item.pdp_id != pdp_id:
        raise AppError("pdp_item_not_found", status.HTTP_404_NOT_FOUND)
    _ensure_item_editable(item)
    mat = await db.get(PDPItemMaterial, material_id)
    if not mat or mat.item_id != item_id:
        raise AppError("pdp_material_not_found", status.HTTP_404_NOT_FOUND)
    await db.delete(mat)
    await db.commit()


# --- Comments ---


async def add_comment(
    db: AsyncSession, tenant_id: uuid.UUID, pdp_id: uuid.UUID, user_id: uuid.UUID, data
) -> dict:
    p = await _get_pdp(db, tenant_id, pdp_id)
    # HRP-17: a finished plan is read-only; new comments would create the
    # illusion that the plan can still move forward.
    _ensure_pdp_editable(p)

    comment = PDPComment(
        pdp_id=pdp_id,
        item_id=data.item_id,
        material_id=getattr(data, "material_id", None),
        user_id=user_id,
        text=data.text,
        file_id=getattr(data, "file_id", None),
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    # Resolve user name
    user_name = None
    if comment.user_id:
        from app.modules.auth.models import User

        user = await db.get(User, comment.user_id)
        if user:
            user_name = f"{user.first_name} {user.last_name}"

    f_url, f_name = await _resolve_file_info(db, comment.file_id)
    return {
        "id": comment.id,
        "pdp_id": comment.pdp_id,
        "item_id": comment.item_id,
        "material_id": comment.material_id,
        "user_id": comment.user_id,
        "user_name": user_name,
        "text": comment.text,
        "file_id": comment.file_id,
        "file_url": f_url,
        "file_name": f_name,
        "created_at": comment.created_at,
    }


# ---------------------------------------------------------------------------
# GF12: PDP Versions
# ---------------------------------------------------------------------------


def _version_to_read(v: PDPVersion) -> dict:
    return {
        "id": v.id,
        "pdp_id": v.pdp_id,
        "version_number": v.version_number,
        "status": v.status,
        "created_at": v.created_at,
    }


async def list_versions(
    db: AsyncSession, tenant_id: uuid.UUID, pdp_id: uuid.UUID
) -> list[dict]:
    await _get_pdp(db, tenant_id, pdp_id)
    result = await db.execute(
        select(PDPVersion)
        .where(PDPVersion.pdp_id == pdp_id)
        .order_by(PDPVersion.version_number.asc())
    )
    return [_version_to_read(v) for v in result.scalars().all()]


async def get_version(
    db: AsyncSession, tenant_id: uuid.UUID, pdp_id: uuid.UUID, version_id: uuid.UUID
) -> dict:
    await _get_pdp(db, tenant_id, pdp_id)
    v = await db.get(PDPVersion, version_id)
    if not v or v.pdp_id != pdp_id:
        raise AppError("pdp_version_not_found", status.HTTP_404_NOT_FOUND)
    data = _version_to_read(v)
    data["snapshot"] = v.snapshot
    return data


async def restore_version(
    db: AsyncSession, tenant_id: uuid.UUID, pdp_id: uuid.UUID, version_id: uuid.UUID
) -> dict:
    """GF12: Restore PDP items and materials from a previous version snapshot."""
    p = await _get_pdp(db, tenant_id, pdp_id)
    v = await db.get(PDPVersion, version_id)
    if not v or v.pdp_id != pdp_id:
        raise AppError("pdp_version_not_found", status.HTTP_404_NOT_FOUND)

    snapshot = v.snapshot

    # Delete current items (cascade deletes materials)
    existing_items = await db.execute(select(PDPItem).where(PDPItem.pdp_id == pdp_id))
    for item in existing_items.scalars().all():
        await db.delete(item)
    await db.flush()

    # Recreate items and materials from snapshot
    for item_data in snapshot.get("items", []):
        new_item = PDPItem(
            pdp_id=pdp_id,
            competence_id=item_data.get("competence_id"),
            title=item_data["title"],
            description=item_data.get("description"),
            sort_index=item_data.get("sort_index", 0),
            is_passed=item_data.get("is_passed", False),
            entity_type=item_data.get("entity_type", "custom"),
        )
        db.add(new_item)
        await db.flush()

        for mat_data in item_data.get("materials", []):
            db.add(
                PDPItemMaterial(
                    item_id=new_item.id,
                    material_id=mat_data.get("material_id"),
                    title=mat_data["title"],
                    format=mat_data.get("format"),
                    link=mat_data.get("link"),
                    study_time=mat_data.get("study_time"),
                    sort_index=mat_data.get("sort_index", 0),
                    is_passed=mat_data.get("is_passed", False),
                )
            )

    # Restore progress from snapshot
    p.total_progress = snapshot.get("total_progress", 0)

    await db.commit()
    return await get_pdp_detail(db, tenant_id, pdp_id)
