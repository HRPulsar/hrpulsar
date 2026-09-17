from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.task_enqueue import enqueue_task
from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.primitives import mapping_service, service
from app.modules.primitives.schemas import (
    MapEnqueued,
    MappingRead,
    MapRequest,
    PrimitiveRead,
    ReviewRequest,
    ReviewResult,
)

router = APIRouter(prefix="/primitives", tags=["primitives"])


@router.get("", response_model=list[PrimitiveRead])
async def list_primitives(
    include_retired: bool = False,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """The capability catalog, in catalog order. Retired codes are hidden
    unless asked for — they stay resolvable for already-linked rows."""
    return await service.list_primitives(db, include_retired=include_retired)


# --- Internal: competence mapping and its acceptance (§3.3–3.4) -------------
# Tag ``work-internal`` is stripped from the public OpenAPI (main.py). No UI:
# driven through /api/docs-style calls or a short script. ``require_role``
# rather than ``require_admin``: this is tenant data, not a platform surface.

internal_router = APIRouter(prefix="/primitives/internal", tags=["work-internal"])


@internal_router.post("/map", response_model=MapEnqueued, status_code=202)
async def start_mapping(
    body: MapRequest,
    current_user: User = Depends(require_role("admin")),
):
    # Imported here like every other router does with its tasks module: the
    # Celery app is not part of the request-path import graph.
    from app.modules.primitives.tasks import map_competences_task

    # The same slot coverage claims, so a run started by hand cannot overlap
    # one, plus an hourly ceiling on ``force`` - the one flag that re-sends
    # competences the model has already been paid to answer for.
    await mapping_service.claim_mapping_slot(current_user.tenant_id, force=body.force)
    try:
        result = enqueue_task(
            map_competences_task,
            str(current_user.tenant_id),
            [str(c) for c in body.competence_ids] if body.competence_ids else None,
            body.force,
            # Ids from a request body never reach the shared library.
            include_origin=False,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            module="primitives",
            action="map_competences",
        )
    except Exception:
        # Nothing will run and free the slot: the next call should be able
        # to retry rather than wait the window out.
        await mapping_service.release_mapping_slot(current_user.tenant_id)
        raise
    return MapEnqueued(task_id=result.id)


@internal_router.get("/mappings", response_model=list[MappingRead])
async def list_mappings(
    status: Literal["ai_suggested", "reviewed", "manual", "rejected"] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await mapping_service.list_mappings(
        db, current_user.tenant_id, status=status
    )


@internal_router.post("/mappings/review", response_model=ReviewResult)
async def review_mappings(
    body: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await mapping_service.review_mapping(
        db, current_user.tenant_id, body.items, reviewed_by_id=current_user.id
    )
