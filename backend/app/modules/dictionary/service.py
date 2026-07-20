import uuid

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dictionary.models import (
    DictionaryItem,
    DictionaryItemTenantOverride,
)
from app.modules.dictionary.schemas import (
    VALID_TYPES,
    DictionaryItemCreate,
    DictionaryItemUpdate,
)


def _item_to_dict(item: DictionaryItem, is_active: bool | None = None) -> dict:
    return {
        "id": item.id,
        "type": item.type,
        "title": item.title,
        "description": item.description,
        # HRP-285: callers passing ``is_active`` substitute the
        # tenant-scoped override when present (origin items only).
        "is_active": item.is_active if is_active is None else is_active,
        "sort_index": item.sort_index,
        "tenant_id": item.tenant_id,
        "metadata": item.metadata_,
        "created_at": item.created_at,
    }


def _validate_type(item_type: str) -> None:
    if item_type not in VALID_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Invalid dictionary type: {item_type}. Valid: {', '.join(sorted(VALID_TYPES))}",
        )


async def _get_origin_override(
    db: AsyncSession, tenant_id: uuid.UUID, item_id: uuid.UUID
) -> bool | None:
    """HRP-285: read the per-tenant ``is_active`` override (if any)."""
    result = await db.execute(
        select(DictionaryItemTenantOverride.is_active).where(
            DictionaryItemTenantOverride.item_id == item_id,
            DictionaryItemTenantOverride.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


def effective_is_active_expr(tenant_id: uuid.UUID) -> ColumnElement[bool]:
    """HRP-337: tenant-effective ``is_active`` as a SQL expression.

    System (origin) items can be deactivated per tenant via
    ``dictionary_item_tenant_overrides`` without touching the origin row.
    Any query that filters or surfaces ``DictionaryItem.is_active`` for a
    tenant must use this expression instead of the raw column, otherwise
    tenant-deactivated System items keep leaking into pickers and prompts.
    """
    override = (
        select(DictionaryItemTenantOverride.is_active)
        .where(
            DictionaryItemTenantOverride.item_id == DictionaryItem.id,
            DictionaryItemTenantOverride.tenant_id == tenant_id,
        )
        .correlate(DictionaryItem)
        .scalar_subquery()
    )
    return func.coalesce(override, DictionaryItem.is_active)


async def origin_active_overrides(
    db: AsyncSession, tenant_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, bool]:
    """HRP-337: batch variant of ``_get_origin_override`` for loaded rows.

    Returns ``{item_id: overridden_is_active}`` for the given items; ids
    without an override row are absent — callers fall back to the item's
    own ``is_active``.
    """
    if not item_ids:
        return {}
    result = await db.execute(
        select(
            DictionaryItemTenantOverride.item_id,
            DictionaryItemTenantOverride.is_active,
        ).where(
            DictionaryItemTenantOverride.tenant_id == tenant_id,
            DictionaryItemTenantOverride.item_id.in_(item_ids),
        )
    )
    return {row.item_id: row.is_active for row in result.all()}


async def list_items(
    db: AsyncSession, tenant_id: uuid.UUID, item_type: str
) -> list[dict]:
    _validate_type(item_type)
    result = await db.execute(
        select(DictionaryItem, DictionaryItemTenantOverride.is_active.label("override"))
        .outerjoin(
            DictionaryItemTenantOverride,
            (DictionaryItemTenantOverride.item_id == DictionaryItem.id)
            & (DictionaryItemTenantOverride.tenant_id == tenant_id),
        )
        .where(
            DictionaryItem.type == item_type,
            or_(
                DictionaryItem.tenant_id == tenant_id,
                DictionaryItem.tenant_id.is_(None),
            ),
        )
        .order_by(DictionaryItem.sort_index, DictionaryItem.title)
    )
    return [_item_to_dict(item, override) for item, override in result.all()]


async def get_item(db: AsyncSession, tenant_id: uuid.UUID, item_id: uuid.UUID) -> dict:
    item = await db.get(DictionaryItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dictionary item not found")
    if item.tenant_id is not None and item.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dictionary item not found")
    override = (
        await _get_origin_override(db, tenant_id, item_id)
        if item.tenant_id is None
        else None
    )
    return _item_to_dict(item, override)


async def create_item(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_type: str,
    data: DictionaryItemCreate,
) -> dict:
    _validate_type(item_type)

    # Check uniqueness within type + tenant
    existing = await db.execute(
        select(DictionaryItem).where(
            DictionaryItem.type == item_type,
            DictionaryItem.title == data.title,
            DictionaryItem.tenant_id == tenant_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Item with this title already exists"
        )

    item = DictionaryItem(
        type=item_type,
        tenant_id=tenant_id,
        title=data.title,
        description=data.description,
        sort_index=data.sort_index,
        metadata_=data.metadata,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _item_to_dict(item)


async def update_item(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    data: DictionaryItemUpdate,
) -> dict:
    item = await db.get(DictionaryItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dictionary item not found")

    updates = data.model_dump(exclude_unset=True)

    if item.tenant_id is None:
        # HRP-285: origin items expose only ``is_active`` per tenant,
        # written to the override table. All other fields stay frozen.
        non_status_fields = {k for k in updates if k != "is_active"}
        if non_status_fields:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Cannot modify origin items (only is_active is tenant-scoped)",
            )
        if "is_active" not in updates:
            # Nothing to change — return current effective view.
            override = await _get_origin_override(db, tenant_id, item_id)
            return _item_to_dict(item, override)
        new_active = bool(updates["is_active"])
        stmt = (
            pg_insert(DictionaryItemTenantOverride)
            .values(item_id=item.id, tenant_id=tenant_id, is_active=new_active)
            .on_conflict_do_update(
                index_elements=[
                    DictionaryItemTenantOverride.item_id,
                    DictionaryItemTenantOverride.tenant_id,
                ],
                set_={"is_active": new_active},
            )
        )
        await db.execute(stmt)
        await db.commit()
        return _item_to_dict(item, new_active)

    if item.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dictionary item not found")

    if "metadata" in updates:
        updates["metadata_"] = updates.pop("metadata")
    for field, value in updates.items():
        setattr(item, field, value)

    await db.commit()
    await db.refresh(item)
    return _item_to_dict(item)


_EMPTY_USAGE: dict = {
    "positions": [],
    "chains": [],
    "assessments_count": 0,
    "assessment_groups_count": 0,
    "pdps_count": 0,
    "exam_pass_marks_count": 0,
    "competences_count": 0,
    "other_refs": {},
}


# HRP-365: FKs on dictionary_items that must NOT block a delete — join /
# metadata tables whose ondelete=CASCADE is the intended cleanup, not a
# live business reference. Everything else found by the metadata walk in
# ``_collect_generic_refs`` blocks the delete, so a brand-new FK lands in
# the gate automatically instead of reproducing the HRP-286 bug class.
_USAGE_EXEMPT_REFS: set[tuple[str, str]] = {
    # Per-tenant activation override rows die with the item by design.
    ("dictionary_item_tenant_overrides", "item_id"),
    # Junction: the tenant's chosen activity fields on the company profile.
    ("company_activity_fields", "activity_field_id"),
    # Per-spec material overrides are meaningless without the spec.
    ("material_specialization_overrides", "specialization_id"),
    # Junction: spec <-> division mapping is structure config, not usage.
    ("specialization_divisions", "specialization_id"),
}

# FKs already counted by name in ``_collect_item_usage`` — excluded from
# the generic walk so they are not double-counted.
_MANUALLY_COUNTED_REFS: set[tuple[str, str]] = {
    ("positions", "specialization_id"),
    ("positions", "grade_id"),
    ("grade_specializations", "specialization_id"),
    ("grade_specializations", "grade_id"),
    ("assessments", "specialization_id"),
    ("assessments", "grade_id"),
    ("assessment_groups", "specialization_id"),
    ("assessment_groups", "grade_id"),
    ("pdps", "specialization_id"),
    ("pdps", "grade_id"),
    ("exam_pass_marks", "specialization_id"),
    ("exam_pass_marks", "grade_id"),
    ("competences", "competence_type_id"),
}


async def _collect_generic_refs(
    db: AsyncSession, item: DictionaryItem
) -> dict[str, int]:
    """HRP-365: walk every FK on ``dictionary_items`` in the SQLAlchemy
    metadata and count live references to ``item``.

    Catches the references the manual enumeration missed (Talent Market
    card requirements, vacancy spec/grade, recommended grades) and any FK
    added in the future. Value-based counting needs no tenant filter: a
    tenant item's UUID can only ever appear in that tenant's rows.
    """
    from app.database import Base

    out: dict[str, int] = {}
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            if fk.column.table.name != "dictionary_items":
                continue
            key = (table.name, fk.parent.name)
            if key in _USAGE_EXEMPT_REFS or key in _MANUALLY_COUNTED_REFS:
                continue
            count = (
                await db.execute(
                    select(func.count()).select_from(table).where(fk.parent == item.id)
                )
            ).scalar_one()
            if count:
                out[f"{table.name}.{fk.parent.name}"] = int(count)
    return out


async def _collect_item_usage(
    db: AsyncSession, tenant_id: uuid.UUID, item: DictionaryItem
) -> dict:
    """HRP-103 redo + prod 500 fix (issue 7559975192): collect the live
    references that would block delete.

    Returns named lists for positions / grade chains (rendered as enumerated
    items in the confirm dialog) plus aggregate counts for tables whose FK
    on ``dictionary_items.id`` defaults to RESTRICT — assessments,
    assessment groups, PDPs, exam pass marks. Without these the prod DELETE
    surfaces a bare 500 ForeignKeyViolationError instead of a structured
    409. Returns ``_EMPTY_USAGE`` for types that have no cross-table refs.
    """
    from app.modules.assessment.models import PDP, Assessment, AssessmentGroup
    from app.modules.dictionary.models import DictionaryItem as _DI
    from app.modules.exam.models import ExamPassMark, MassExam
    from app.modules.grade_system.models import GradeSpecialization
    from app.modules.position.models import Position

    if item.type == "competence_type":
        # HRP-286 redo: competences.competence_type_id is ondelete=SET NULL,
        # so the delete would silently strip the type off every competence
        # instead of raising an FK violation — count references explicitly.
        from app.modules.competence.models import Competence

        competences_count = (
            await db.execute(
                select(func.count(Competence.id)).where(
                    Competence.tenant_id == tenant_id,
                    Competence.competence_type_id == item.id,
                )
            )
        ).scalar_one()
        usage = dict(_EMPTY_USAGE)
        usage["competences_count"] = int(competences_count)
        usage["other_refs"] = await _collect_generic_refs(db, item)
        return usage

    if item.type not in ("specialization", "grade"):
        usage = dict(_EMPTY_USAGE)
        usage["other_refs"] = await _collect_generic_refs(db, item)
        return usage

    if item.type == "specialization":
        position_predicate = Position.specialization_id == item.id
        chain_predicate = GradeSpecialization.specialization_id == item.id
        assessment_predicate = Assessment.specialization_id == item.id
        assessment_group_predicate = AssessmentGroup.specialization_id == item.id
        pdp_predicate = PDP.specialization_id == item.id
        exam_pm_predicate = ExamPassMark.specialization_id == item.id
    else:
        position_predicate = Position.grade_id == item.id
        chain_predicate = GradeSpecialization.grade_id == item.id
        assessment_predicate = Assessment.grade_id == item.id
        assessment_group_predicate = AssessmentGroup.grade_id == item.id
        pdp_predicate = PDP.grade_id == item.id
        exam_pm_predicate = ExamPassMark.grade_id == item.id

    positions_q = await db.execute(
        select(Position.id, Position.title)
        .where(Position.tenant_id == tenant_id, position_predicate)
        .order_by(Position.title)
    )
    positions = [{"id": row[0], "title": row[1]} for row in positions_q.all()]

    grade_alias = _DI.__table__.alias("grade_di")
    spec_alias = _DI.__table__.alias("spec_di")
    chains_q = await db.execute(
        select(
            GradeSpecialization.id,
            GradeSpecialization.grade_id,
            grade_alias.c.title.label("grade_title"),
            GradeSpecialization.specialization_id,
            spec_alias.c.title.label("specialization_title"),
        )
        .join(
            grade_alias, GradeSpecialization.grade_id == grade_alias.c.id, isouter=True
        )
        .join(
            spec_alias,
            GradeSpecialization.specialization_id == spec_alias.c.id,
            isouter=True,
        )
        .where(GradeSpecialization.tenant_id == tenant_id, chain_predicate)
        .order_by(spec_alias.c.title, grade_alias.c.title)
    )
    chains = [
        {
            "id": row[0],
            "grade_id": row[1],
            "grade_title": row[2],
            "specialization_id": row[3],
            "specialization_title": row[4],
        }
        for row in chains_q.all()
    ]

    assessments_count = (
        await db.execute(
            select(func.count(Assessment.id)).where(
                Assessment.tenant_id == tenant_id, assessment_predicate
            )
        )
    ).scalar_one()
    assessment_groups_count = (
        await db.execute(
            select(func.count(AssessmentGroup.id)).where(
                AssessmentGroup.tenant_id == tenant_id,
                assessment_group_predicate,
            )
        )
    ).scalar_one()
    pdps_count = (
        await db.execute(
            select(func.count(PDP.id)).where(PDP.tenant_id == tenant_id, pdp_predicate)
        )
    ).scalar_one()
    # exam_pass_marks rides tenant via mass_exams; the FK has no ondelete
    # so even a soft cleanup would block on the tenant's pass marks.
    exam_pass_marks_count = (
        await db.execute(
            select(func.count(ExamPassMark.id))
            .join(MassExam, ExamPassMark.mass_exam_id == MassExam.id)
            .where(MassExam.tenant_id == tenant_id, exam_pm_predicate)
        )
    ).scalar_one()

    return {
        "positions": positions,
        "chains": chains,
        "assessments_count": int(assessments_count),
        "assessment_groups_count": int(assessment_groups_count),
        "pdps_count": int(pdps_count),
        "exam_pass_marks_count": int(exam_pass_marks_count),
        "competences_count": 0,
        # HRP-365: Talent Market cards, vacancy spec/grade, recommended
        # grades and any future FK — caught by the metadata walk.
        "other_refs": await _collect_generic_refs(db, item),
    }


async def get_item_usage(
    db: AsyncSession, tenant_id: uuid.UUID, item_id: uuid.UUID
) -> dict:
    """HRP-103 redo: GET counterpart for the delete-confirm preview."""
    item = await db.get(DictionaryItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dictionary item not found")
    if item.tenant_id is None:
        # Origin items can never be deleted, so usage is moot — still return
        # an empty payload instead of leaking the existence of the origin
        # row to a different tenant.
        return dict(_EMPTY_USAGE)
    if item.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dictionary item not found")
    return await _collect_item_usage(db, tenant_id, item)


_IN_USE_MESSAGE = "This item has connections with other object(s). It can't be deleted"


async def delete_item(
    db: AsyncSession, tenant_id: uuid.UUID, item_id: uuid.UUID
) -> None:
    item = await db.get(DictionaryItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dictionary item not found")
    if item.tenant_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot delete origin items")
    if item.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dictionary item not found")

    # HRP-57 §8.2 (E7 / HRP-73) + prod fix (issue 7559975192): Specializations
    # and Grades are referenced from Position (ondelete=SET NULL — would
    # silently orphan the row), GradeSpecialization (ondelete=CASCADE —
    # would wipe the matrix profile), and assessments / assessment_groups /
    # pdps / exam_pass_marks (all default RESTRICT, which the DB enforces
    # with a 500 ForeignKeyViolationError if we don't gate first). The API
    # blocks the delete and demands the operator clean references first.
    # HRP-286 redo: competence types join the gate because their FK from
    # competences is SET NULL — the DB would let the delete through and
    # silently untype the competences.
    # HRP-365: the gate runs for every item type — the metadata walk in
    # _collect_generic_refs picks up FKs the manual enumeration missed
    # (Talent Market card requirements, vacancy spec/grade, recommended
    # grades) and any FK added later.
    usage = await _collect_item_usage(db, tenant_id, item)
    position_count = len(usage["positions"])
    chain_count = len(usage["chains"])
    assessments_count = usage["assessments_count"]
    assessment_groups_count = usage["assessment_groups_count"]
    pdps_count = usage["pdps_count"]
    exam_pass_marks_count = usage["exam_pass_marks_count"]
    competences_count = usage["competences_count"]
    other_refs_count = sum(usage["other_refs"].values())

    total_refs = (
        position_count
        + chain_count
        + assessments_count
        + assessment_groups_count
        + pdps_count
        + exam_pass_marks_count
        + competences_count
        + other_refs_count
    )
    if total_refs:
        # HRP-286: surface a single generic message; the per-table
        # counts were misleading reviewers since some references are
        # historical (e.g. closed assessments). The `counts` / `usage`
        # blobs stay in `detail` for callers that still want them.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "in_use",
                "type": item.type,
                "counts": {
                    "positions": position_count,
                    "chains": chain_count,
                    "assessments": assessments_count,
                    "assessment_groups": assessment_groups_count,
                    "pdps": pdps_count,
                    "exam_pass_marks": exam_pass_marks_count,
                    "competences": competences_count,
                    "others": usage["other_refs"],
                },
                # jsonable_encoder stringifies UUIDs so the JSONResponse
                # serializer that fastapi uses for HTTPException details
                # doesn't blow up on the raw Python uuid objects.
                "usage": jsonable_encoder(usage),
                "message": _IN_USE_MESSAGE,
            },
        )

    # HRP-286: belt for anything the gate above still missed (e.g. an FK
    # racing in between the check and the delete) — catch the underlying
    # FK violation and convert it to the same structured 409 so the toast
    # is never empty.
    from sqlalchemy.exc import IntegrityError

    try:
        await db.delete(item)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "in_use",
                "type": item.type,
                "message": _IN_USE_MESSAGE,
            },
        ) from None
