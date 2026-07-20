import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.position import service
from app.modules.position.schemas import (
    PositionBulkAction,
    PositionCreate,
    PositionEmployeeRead,
    PositionList,
    PositionMatrix,
    PositionMatrixStatus,
    PositionOccupancy,
    PositionRead,
    PositionStatusUpdate,
    PositionUpdate,
)

router = APIRouter(tags=["positions"])


@router.post("/positions", response_model=PositionRead, status_code=201)
async def create_position(
    data: PositionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_position(db, current_user.tenant_id, data)


@router.post("/positions/bulk-action")
async def bulk_action_positions(
    data: PositionBulkAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.bulk_action_positions(db, current_user.tenant_id, data)


@router.get("/positions", response_model=PositionList)
async def list_positions(
    skip: int = Query(0, ge=0),
    # HRP-64: filter dropdowns on /employees and similar pages need the full
    # roster in a single round-trip — the previous `le=100` cap silently 422'd
    # `?limit=200` requests, which the frontend swallowed into an empty list
    # ("No options" in the picker). The bumped ceiling is still bounded so a
    # pathological caller can't dump the entire table.
    limit: int = Query(50, ge=1, le=500),
    search: str | None = None,
    is_active: bool | None = None,
    source: str | None = None,
    specialization_id: uuid.UUID | None = None,
    grade_id: uuid.UUID | None = None,
    division_id: uuid.UUID | None = None,
    # HRP-72 (E6): richer list filters per HRP-57 § 7.3.
    lifecycle_status: str | None = Query(
        default=None,
        description="active|on_hold|frozen|closed",
    ),
    has_vacancies: bool | None = Query(
        default=None,
        description="True returns rows where headcount > assigned employees.",
    ),
    matrix_unconfigured: bool | None = Query(
        default=None,
        description="True returns rows whose (spec, grade) pair has no GradeCompetenceLink.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = await service.list_positions(
        db,
        current_user.tenant_id,
        skip,
        limit,
        search,
        is_active,
        source,
        specialization_id,
        grade_id,
        division_id,
        lifecycle_status=lifecycle_status,
        has_vacancies=has_vacancies,
        matrix_unconfigured=matrix_unconfigured,
    )
    return {"items": items, "total": total}


@router.get("/positions/{position_id}", response_model=PositionRead)
async def get_position(
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_position(db, current_user.tenant_id, position_id)


@router.put("/positions/{position_id}", response_model=PositionRead)
async def update_position(
    position_id: uuid.UUID,
    data: PositionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_position(db, current_user.tenant_id, position_id, data)


@router.delete("/positions/{position_id}", status_code=204)
async def delete_position(
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_position(db, current_user.tenant_id, position_id)


@router.get(
    "/positions/{position_id}/employees",
    response_model=list[PositionEmployeeRead],
)
async def list_position_employees(
    position_id: uuid.UUID,
    with_alerts: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_position_employees(
        db,
        current_user.tenant_id,
        position_id,
        with_alerts=with_alerts,
    )


@router.get(
    "/positions/{position_id}/occupancy",
    response_model=PositionOccupancy,
)
async def get_position_occupancy(
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_position_occupancy(db, current_user.tenant_id, position_id)


@router.get(
    "/positions/{position_id}/matrix-status",
    response_model=PositionMatrixStatus,
)
async def get_position_matrix_status(
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_matrix_status(db, current_user.tenant_id, position_id)


@router.get(
    "/positions/{position_id}/competences",
    response_model=PositionMatrix,
)
async def get_position_competences(
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_position_competence_matrix(
        db, current_user.tenant_id, position_id
    )


@router.post(
    "/positions/{position_id}/status",
    response_model=PositionRead,
)
async def set_position_status(
    position_id: uuid.UUID,
    data: PositionStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.set_position_status(
        db, current_user.tenant_id, position_id, data.lifecycle_status
    )


@router.post(
    "/positions/{position_id}/deactivate",
    response_model=PositionRead,
    deprecated=True,
    description=(
        "Deprecated since POS6: use POST /positions/{id}/status with "
        "lifecycle_status='frozen' instead. Kept for backwards compatibility "
        "with pre-POS6 API clients."
    ),
)
async def deactivate_position(
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.deactivate_position(db, current_user.tenant_id, position_id)
