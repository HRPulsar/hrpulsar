"""Analytics REST.

Rights come from the tenant's section access matrix (HRP-822): ``view`` on
``analytics`` reads every chart on the page, ``manage`` adds the two
assessment exports and the AI summary of the development loop - the gate
(``section_gate``) makes that split by method, and
the dependencies below say it out loud. How *wide* a chart is stays the
read scope's answer, not the level's: a manager handed the section reads
their own subtree, and only an admin-level role (``core/access_scope.py``)
covers the workspace. One's own loop (``/analytics/my-loop``) is personal
and outside the matrix.
"""

import uuid

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import (
    assert_employee_read_scope,
    get_current_employee,
    get_visible_division_ids,
    get_visible_employee_ids,
    pay_visible_employee_ids,
)
from app.core.errors import AppError
from app.core.schemas import TaskAccepted
from app.core.sections import matrix_levels, require_section
from app.database import get_db
from app.modules.analytics import hr_metrics as hr_metrics_service
from app.modules.analytics import service
from app.modules.assessment.scope import pdp_status_scope, runs_plans
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User

router = APIRouter(tags=["analytics"])

_view = require_section("analytics", "view")
_manage = require_section("analytics", "manage")
# Payroll is a data class of its own, not a level of the section: the same
# actors read it here as read an employee's own compensation rows -
# ``admin`` and a division manager inside their subtree, HR deliberately
# not among them (HRP-221 REDO, ``/employees/{id}/compensation``). The
# section says whether the page is yours; this says whether the pay on it
# is. Without it, handing analytics to HR would hand them a figure the
# employee card refuses them - and a one-person division turns an average
# into an exact salary. HRP-829: the card's pay tab is ``manage`` on
# ``employees`` now (``admin`` and ``manager`` by default), so this is too,
# and the figures leave out the admin-level people that tab refuses below
# the admin level (``pay_visible_employee_ids``).
_compensation = require_section("employees", "manage")


class AiSummaryRequest(BaseModel):
    """Optional echo of the ``data_version`` the client got from the GET —
    lets a cache hit skip the aggregation pass entirely."""

    data_version: str | None = None


@router.get("/analytics/assessments")
async def assessment_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
):
    return await service.assessment_stats(
        db, current_user.tenant_id, await get_visible_employee_ids(db, current_user)
    )


@router.get("/analytics/pdp")
async def pdp_stats(
    db: AsyncSession = Depends(get_db),
    # The ``development`` section's (the registry's longest prefix wins).
    # HRP-825: the level opens it, the read scope below sizes it - an
    # employee counts their own plans, as the section page already shows.
    current_user: User = Depends(get_current_user),
):
    return await service.pdp_stats(
        db,
        current_user.tenant_id,
        await get_visible_employee_ids(db, current_user),
        hide_drafts=not await runs_plans(db, current_user),
    )


@router.get("/analytics/dev-loop")
async def dev_loop(
    # HRP-724: a closed set, so a typo answers 422 instead of silently
    # reporting a window nobody asked for.
    days: service.DynamicsPeriod = service.DynamicsPeriod.quarter,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
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
    current_user: User = Depends(_view),
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
    current_user: User = Depends(_manage),
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
        # A colleague's loop is their card's sub-resource: the personal-path
        # exemption (core/sections.py) covers one's own, the employees
        # matrix the rest - none closes it like the card's other reads.
        own = await get_current_employee(db, current_user)
        if (own is None or own.id != employee_id) and (
            await matrix_levels(db, current_user)
        )["employees"] == "none":
            raise AppError("auth_insufficient_permissions", status.HTTP_403_FORBIDDEN)
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
    current_user: User = Depends(_view),
    _pay: User = Depends(_compensation),
):
    """HRP-822: salary figures for the caller's scope.

    ``require_role("admin")`` was the whole fence here - no scope at all -
    so opening the section to a division head would have handed them the
    workspace's payroll. The scope is the fence now, and ``_compensation``
    keeps the audience the one the employee card already has.
    """
    return await service.compensation_stats(
        db, current_user.tenant_id, await pay_visible_employee_ids(db, current_user)
    )


@router.get("/analytics/compensation/benchmark")
async def compensation_benchmark(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
    _pay: User = Depends(_compensation),
):
    return await service.compensation_benchmark(
        db, current_user.tenant_id, await pay_visible_employee_ids(db, current_user)
    )


@router.get("/analytics/division-matrix")
async def division_matrix(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
):
    """HRP-822: the headcount matrix for the divisions the caller manages.

    It carried no guard at all until the gate closed it (HRP-820), so the
    subtree is the only fence it has ever had; a manager's matrix now adds
    up to the employee list it links to.
    """
    return await service.division_specialization_matrix(
        db, current_user.tenant_id, await get_visible_division_ids(db, current_user)
    )


@router.get("/analytics/cpa-comparison")
async def cpa_comparison(
    cpa_id_1: uuid.UUID = Query(...),
    cpa_id_2: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
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
    current_user: User = Depends(_manage),
):
    return await service.export_assessments_xlsx(
        db, current_user.tenant_id, await get_visible_employee_ids(db, current_user)
    )


@router.post("/analytics/export/assessments/async", response_model=TaskAccepted)
async def export_assessments_async(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
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
