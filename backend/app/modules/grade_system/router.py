import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.grade_system import service
from app.modules.grade_system.schemas import (
    GradeCompetenceLinkCreate,
    GradeCompetenceLinkRead,
    GradeOptionRead,
    GradeSpecializationCreate,
    GradeSpecializationRead,
    GradeSpecializationUpdate,
)

router = APIRouter(tags=["grade-system"])


@router.get(
    "/grade-system/specializations/{specialization_id}",
    response_model=list[GradeSpecializationRead],
)
async def list_chains(
    specialization_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_by_specialization(
        db, current_user.tenant_id, specialization_id
    )


@router.get(
    "/grade-system/specializations/{specialization_id}/grades",
    response_model=list[GradeOptionRead],
)
async def list_specialization_grades(
    specialization_id: uuid.UUID,
    include_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # HRP-293: grade picker options for Development plans — chains of the
    # specialization minus tenant-deactivated grades; include_id keeps a
    # saved grade selectable.
    return await service.list_grades_for_specialization(
        db, current_user.tenant_id, specialization_id, include_id=include_id
    )


@router.get(
    "/grade-system/divisions/{division_id}",
    response_model=list[GradeSpecializationRead],
)
async def list_chains_by_division(
    division_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_by_division(db, current_user.tenant_id, division_id)


@router.post(
    "/grade-system/chains",
    response_model=GradeSpecializationRead,
    status_code=201,
)
async def create_chain(
    data: GradeSpecializationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.create_chain(db, current_user.tenant_id, data)


@router.put(
    "/grade-system/chains/{chain_id}",
    response_model=GradeSpecializationRead,
)
async def update_chain(
    chain_id: uuid.UUID,
    data: GradeSpecializationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.update_chain(db, current_user.tenant_id, chain_id, data)


@router.delete("/grade-system/chains/{chain_id}", status_code=204)
async def delete_chain(
    chain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_chain(db, current_user.tenant_id, chain_id)


@router.post(
    "/grade-system/chains/{chain_id}/competences",
    response_model=GradeCompetenceLinkRead,
    status_code=201,
)
async def add_competence_link(
    chain_id: uuid.UUID,
    data: GradeCompetenceLinkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.add_competence_link(db, current_user.tenant_id, chain_id, data)


@router.delete("/grade-system/links/{link_id}", status_code=204)
async def remove_competence_link(
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.remove_competence_link(db, current_user.tenant_id, link_id)
