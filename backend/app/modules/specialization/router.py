"""Specialization API — list / detail / grades / positions / matrix."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
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
    return await service.get_specialization_detail(db, current_user.tenant_id, spec_id)


@router.get(
    "/specializations/{spec_id}/grades",
    response_model=list[SpecializationGradeRead],
)
async def list_specialization_grades(
    spec_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_grades_with_attrs(db, current_user.tenant_id, spec_id)


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
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.add_grades(
        db, current_user.tenant_id, spec_id, data.grade_ids
    )


@router.patch(
    "/specializations/{spec_id}/grades/reorder",
    response_model=list[SpecializationGradeRead],
)
async def reorder_grades(
    spec_id: uuid.UUID,
    data: GradesReorder,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
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
    current_user: User = Depends(require_role("admin", "manager")),
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
    current_user: User = Depends(require_role("admin", "manager")),
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
    return await service.get_positions_summary(db, current_user.tenant_id, spec_id)


# HRP-57 §3.1 (E4): Specialization detail "Employees" tab. Returns all
# employees in any Position attached to this specialization, in the same
# row shape as `/positions/{id}/employees` so the same UI component renders.
@router.get(
    "/specializations/{spec_id}/employees",
    response_model=list[PositionEmployeeRead],
)
async def list_specialization_employees(
    spec_id: uuid.UUID,
    with_alerts: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_employees(
        db,
        current_user.tenant_id,
        spec_id,
        with_alerts=with_alerts,
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
    current_user: User = Depends(require_role("admin", "manager")),
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
    return await service.get_matrix_bulk(db, current_user.tenant_id, spec_id)


@router.put("/specializations/{spec_id}/matrix-bulk", response_model=MatrixBulkRead)
async def upsert_matrix_bulk(
    spec_id: uuid.UUID,
    data: MatrixBulkUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
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
