import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import TaskAccepted
from app.database import get_db
from app.modules.analytics import service
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User

router = APIRouter(tags=["analytics"])


class AiSummaryRequest(BaseModel):
    """Optional echo of the ``data_version`` the client got from the GET —
    lets a cache hit skip the aggregation pass entirely."""

    data_version: str | None = None


@router.get("/analytics/assessments")
async def assessment_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.assessment_stats(db, current_user.tenant_id)


@router.get("/analytics/pdp")
async def pdp_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.pdp_stats(db, current_user.tenant_id)


@router.get("/analytics/dev-loop")
async def dev_loop(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.dev_loop(db, current_user.tenant_id)


@router.post("/analytics/dev-loop/ai-summary")
async def dev_loop_ai_summary(
    body: AiSummaryRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """On-demand AI summary of the development loop; cached per data state."""
    return await service.dev_loop_ai_summary(
        db,
        current_user.tenant_id,
        current_user.id,
        client_fingerprint=body.data_version if body else None,
    )


@router.get("/analytics/my-loop")
async def my_loop(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Personal development loop for the logged-in employee."""
    return await service.my_loop(db, current_user.tenant_id, current_user.id)


@router.post("/analytics/my-loop/ai-summary")
async def my_loop_ai_summary(
    body: AiSummaryRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """On-demand coach-style AI summary of the personal loop; cached per data state."""
    return await service.my_loop_ai_summary(
        db,
        current_user.tenant_id,
        current_user.id,
        client_fingerprint=body.data_version if body else None,
    )


@router.get("/analytics/compensation")
async def compensation_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.compensation_stats(db, current_user.tenant_id)


@router.get("/analytics/compensation/benchmark")
async def compensation_benchmark(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.compensation_benchmark(db, current_user.tenant_id)


@router.get("/analytics/division-matrix")
async def division_matrix(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.division_specialization_matrix(db, current_user.tenant_id)


@router.get("/analytics/cpa-comparison")
async def cpa_comparison(
    cpa_id_1: uuid.UUID = Query(...),
    cpa_id_2: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.compare_cpa_rounds(
        db, current_user.tenant_id, cpa_id_1, cpa_id_2
    )


@router.get("/analytics/pdp/{pdp_id}/progress")
async def pdp_progress(
    pdp_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.pdp_progress_timeline(db, current_user.tenant_id, pdp_id)


@router.post("/analytics/export/assessments")
async def export_assessments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.export_assessments_xlsx(db, current_user.tenant_id)


@router.post("/analytics/export/assessments/async", response_model=TaskAccepted)
async def export_assessments_async(
    current_user: User = Depends(require_role("admin", "manager")),
):
    """Queue XLSX report generation as background task. Returns task_id for polling."""
    from app.core.task_enqueue import enqueue_task
    from app.modules.analytics.tasks import export_assessments_task

    result = enqueue_task(
        export_assessments_task,
        str(current_user.tenant_id),
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module="analytics",
        action="export_assessments",
    )
    return {"task_id": result.id}
