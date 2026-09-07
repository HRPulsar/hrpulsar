import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import (
    assert_employee_read_scope,
    get_visible_employee_ids,
)
from app.core.schemas import TaskAccepted
from app.database import get_db
from app.modules.analytics import hr_metrics as hr_metrics_service
from app.modules.analytics import service
from app.modules.assessment.scope import pdp_status_scope
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
    current_user: User = Depends(require_role("admin", "manager", "hr")),
):
    return await service.assessment_stats(
        db, current_user.tenant_id, await get_visible_employee_ids(db, current_user)
    )


@router.get("/analytics/pdp")
async def pdp_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "hr")),
):
    return await service.pdp_stats(
        db, current_user.tenant_id, await get_visible_employee_ids(db, current_user)
    )


@router.get("/analytics/dev-loop")
async def dev_loop(
    # HRP-724: a closed set, so a typo answers 422 instead of silently
    # reporting a window nobody asked for.
    days: service.DynamicsPeriod = service.DynamicsPeriod.quarter,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    # HRP-638: the loop used to aggregate the whole tenant for every
    # manager — counts and finding names included — while /employees
    # honoured the read scope. Same scope on both sides now, so a tile's
    # number matches the list it links to and nobody reads a division
    # they cannot open.
    return await service.dev_loop(
        db,
        current_user.tenant_id,
        await get_visible_employee_ids(db, current_user),
        days=int(days),
    )


@router.get("/analytics/hr-metrics")
async def hr_metrics(
    days: service.DynamicsPeriod = service.DynamicsPeriod.quarter,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "hr")),
):
    """HRP-732: HR metrics over a period, each tagged with how exact it is.

    Same read scope as the rest of the page: a manager gets their subtree,
    admin and HR the whole workspace.
    """
    return await hr_metrics_service.hr_metrics(
        db,
        current_user.tenant_id,
        await get_visible_employee_ids(db, current_user),
        days=int(days),
    )


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
        visible_employee_ids=await get_visible_employee_ids(db, current_user),
        client_fingerprint=body.data_version if body else None,
    )


@router.get("/analytics/my-loop")
async def my_loop(
    days: service.DynamicsPeriod = service.DynamicsPeriod.quarter,
    employee_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Personal development loop — the caller's, or a readable colleague's.

    HRP-724: the employee profile shows the same dynamics the owner sees on
    their dashboard, so it reads this endpoint rather than growing a second
    one. Access is the card's own rule: your own loop always, anyone else's
    only inside your read scope (403 ``outside_division_scope`` otherwise).
    """
    if employee_id is not None:
        await assert_employee_read_scope(db, current_user, employee_id)
    return await service.my_loop(
        db,
        current_user.tenant_id,
        current_user.id,
        days=int(days),
        employee_id=employee_id,
    )


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
        db,
        current_user.tenant_id,
        cpa_id_1,
        cpa_id_2,
        await get_visible_employee_ids(db, current_user),
    )


@router.get("/analytics/pdp/{pdp_id}/progress")
async def pdp_progress(
    pdp_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(pdp_status_scope),
):
    return await service.pdp_progress_timeline(db, current_user.tenant_id, pdp_id)


@router.post("/analytics/export/assessments")
async def export_assessments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "hr")),
):
    return await service.export_assessments_xlsx(
        db, current_user.tenant_id, await get_visible_employee_ids(db, current_user)
    )


@router.post("/analytics/export/assessments/async", response_model=TaskAccepted)
async def export_assessments_async(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "hr")),
):
    """Queue XLSX report generation as background task. Returns task_id for polling."""
    from app.core.task_enqueue import enqueue_task
    from app.modules.analytics.tasks import export_assessments_task

    # HRP-641: the scope travels in the task arguments. Resolving it inside
    # the worker would mean resolving it for the tenant, not for whoever
    # asked — the whole point of the fence.
    visible = await get_visible_employee_ids(db, current_user)
    result = enqueue_task(
        export_assessments_task,
        str(current_user.tenant_id),
        None if visible is None else sorted(str(i) for i in visible),
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module="analytics",
        action="export_assessments",
    )
    return {"task_id": result.id}
