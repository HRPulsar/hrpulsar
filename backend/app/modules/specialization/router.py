"""Specialization API — list / detail / grades / positions / matrix."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import (
    can_see_compensation,
    can_see_position_grades,
    get_visible_employee_ids,
    trim_position_fields,
)
from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.employee.schemas import EmployeeDirectoryRead
from app.modules.position.schemas import PositionEmployeeRead
from app.modules.specialization import service
from app.modules.specialization.schemas import (
    DivisionPositionsBlock,
    GradePatch,
    GradesBulkAdd,
    GradesReorder,
    MatrixBulkRead,
    MatrixBulkUpsert,
    MatrixCellRead,
    MatrixUpsert,
    SpecializationDetail,
    SpecializationGradeRead,
    SpecializationRead,
)

router = APIRouter(tags=["specializations"])


async def assert_may_read_grades(db: AsyncSession, current_user: User) -> None:
    """HRP-637: 403 unless this caller may read grades at all."""
    if await can_see_position_grades(db, current_user):
        return
    raise AppError(
        "outside_division_scope",
        status.HTTP_403_FORBIDDEN,
        detail_extra={},
        detail_code_key="error_code",
    )


@router.get("/specializations", response_model=list[SpecializationRead])
async def list_specializations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_specializations(db, current_user.tenant_id)


@router.get("/specializations/{spec_id}", response_model=SpecializationDetail)
async def get_specialization(
    spec_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    detail = await service.get_specialization_detail(
        db, current_user.tenant_id, spec_id
    )
    # HRP-637: the detail embeds the same grade ladder the route below
    # serves, so it has to lose the same bands.
    if not can_see_compensation(current_user):
        for grade in detail["grades"]:
            trim_position_fields(grade, show_salary=False)
    return detail


@router.get(
    "/specializations/{spec_id}/grades",
    response_model=list[SpecializationGradeRead],
)
async def list_specialization_grades(
    spec_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # HRP-637: the ladder itself is workspace-wide — it says what grades a
    # specialization has, not who holds them — but the salary band attached
    # to each rung is compensation data.
    show_salary = can_see_compensation(current_user)
    return [
        trim_position_fields(grade, show_salary=show_salary)
        for grade in await service.get_grades_with_attrs(
            db, current_user.tenant_id, spec_id
        )
    ]


# HRP-57 P1: manage Spec×Grade pairs directly from the Specialization page.
# These complement the legacy `/grade-system/chains` endpoints — that one
# remains for admin scripts; the UI flow goes through these.
@router.post(
    "/specializations/{spec_id}/grades",
    response_model=list[SpecializationGradeRead],
    status_code=201,
)
async def add_grades(
    spec_id: uuid.UUID,
    data: GradesBulkAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hr")),
):
    return await service.add_grades(db, current_user.tenant_id, spec_id, data.grade_ids)


@router.patch(
    "/specializations/{spec_id}/grades/reorder",
    response_model=list[SpecializationGradeRead],
)
async def reorder_grades(
    spec_id: uuid.UUID,
    data: GradesReorder,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hr")),
):
    return await service.reorder_grades(
        db,
        current_user.tenant_id,
        spec_id,
        [entry.model_dump() for entry in data.orders],
    )


@router.patch(
    "/specializations/{spec_id}/grades/{grade_id}",
    response_model=SpecializationGradeRead,
)
async def patch_grade(
    spec_id: uuid.UUID,
    grade_id: uuid.UUID,
    data: GradePatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hr")),
):
    return await service.patch_grade(
        db,
        current_user.tenant_id,
        spec_id,
        grade_id,
        data.model_dump(exclude_unset=True),
    )


@router.delete(
    "/specializations/{spec_id}/grades/{grade_id}",
    status_code=204,
)
async def delete_grade(
    spec_id: uuid.UUID,
    grade_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hr")),
):
    await service.delete_grade(db, current_user.tenant_id, spec_id, grade_id)


@router.get(
    "/specializations/{spec_id}/positions",
    response_model=list[DivisionPositionsBlock],
)
async def list_specialization_positions(
    spec_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    blocks = await service.get_positions_summary(db, current_user.tenant_id, spec_id)
    # HRP-637: this is the catalogue's "position -> grade" join under
    # another URL — one specialization at a time instead of one filter
    # away — so it answers to the same flag.
    if not await can_see_position_grades(db, current_user):
        for block in blocks:
            for position in block["positions"]:
                trim_position_fields(position, show_grades=False)
    return blocks


# HRP-57 §3.1 (E4): Specialization detail "Employees" tab. Returns all
# employees in any Position attached to this specialization, in the same
# row shape as `/positions/{id}/employees` so the same UI component renders.
@router.get(
    "/specializations/{spec_id}/employees",
    response_model=list[PositionEmployeeRead | EmployeeDirectoryRead],
)
async def list_specialization_employees(
    spec_id: uuid.UUID,
    with_alerts: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # HRP-633: same trimming as the position drill-down — the two routes
    # share the row shape, so they have to share the boundary too.
    return await service.list_employees(
        db,
        current_user.tenant_id,
        spec_id,
        with_alerts=with_alerts,
        visible_employee_ids=await get_visible_employee_ids(db, current_user),
    )


@router.get(
    "/specializations/{spec_id}/matrix",
    response_model=list[MatrixCellRead],
)
async def get_matrix(
    spec_id: uuid.UUID,
    grade_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # HRP-637: ``MatrixCellRead`` carries no grade key, so there is nothing
    # here to trim — but ``grade_id`` is a query parameter, which makes the
    # route an oracle: ask it for a candidate grade and compare the answer
    # with the competence set ``/positions/{id}/competences`` still returns,
    # and set equality names the grade the position payload withholds. A
    # caller who may not read grades has no legitimate use for a lookup
    # keyed by one, so the route follows the same rule as the field.
    await assert_may_read_grades(db, current_user)
    return await service.get_matrix(db, current_user.tenant_id, spec_id, grade_id)


@router.put(
    "/specializations/{spec_id}/matrix",
    response_model=list[MatrixCellRead],
)
async def upsert_matrix(
    spec_id: uuid.UUID,
    grade_id: uuid.UUID,
    data: MatrixUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hr")),
):
    return await service.upsert_matrix(
        db,
        current_user.tenant_id,
        current_user.id,
        spec_id,
        grade_id,
        [link.model_dump() for link in data.links],
    )


@router.get("/specializations/{spec_id}/matrix-bulk", response_model=MatrixBulkRead)
async def get_matrix_bulk(
    spec_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # HRP-637: ``MatrixBulkGradeRead.grade_id`` is a required uuid, so this
    # payload cannot be blanked field-by-field the way the others are — and
    # blanking would not be enough anyway, since the grade-to-competence
    # mapping it carries is the other half of the fingerprint oracle above.
    # The whole ladder drops out instead; the builder already renders an
    # empty state for it.
    if not await can_see_position_grades(db, current_user):
        return {"grades": []}
    return await service.get_matrix_bulk(db, current_user.tenant_id, spec_id)


@router.put("/specializations/{spec_id}/matrix-bulk", response_model=MatrixBulkRead)
async def upsert_matrix_bulk(
    spec_id: uuid.UUID,
    data: MatrixBulkUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hr")),
):
    return await service.upsert_matrix_bulk(
        db,
        current_user.tenant_id,
        current_user.id,
        spec_id,
        [g.model_dump() for g in data.grades],
    )


@router.get("/competences/{competence_id}/indicators-by-level")
async def list_competence_indicators_by_level(
    competence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_competence_indicators_by_level(
        db, current_user.tenant_id, competence_id
    )
