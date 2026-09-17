"""``/api/work`` — containers and steps (HRP-754).

Rights (HRP-810): see ``access`` - the section's managers, the owner, the
access rules and the people on the steps read a container; the managers
and the owner edit it. Every route resolves its container through one of
the ``access`` dependencies, so a hidden container is a 404 everywhere.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import billing_hooks
from app.core.access_scope import get_visible_employee_ids
from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.work import access, coverage, service
from app.modules.work.models import WorkContainer
from app.modules.work.schemas import (
    ApplyResult,
    ContainerAccessRead,
    ContainerAccessUpdate,
    ContainerCreate,
    ContainerList,
    ContainerRead,
    ContainerStatus,
    ContainerType,
    ContainerUpdate,
    CoverageRead,
    GapRead,
    HireNeedCreate,
    HireNeedRead,
    ProcessPersonRead,
    ReclassifyRequest,
    SessionApply,
    SessionCreate,
    SessionRead,
    SkillRead,
    StepCreate,
    StepOrder,
    StepPrimitivesUpdate,
    StepRead,
    StepUpdate,
)

router = APIRouter(prefix="/work", tags=["work"])

# What a skill generation's credit hold is filed against (HRP-547).
SKILL_RESERVE_ENTITY = "work_step_skill"


def _read(actor: access.Actor, row: WorkContainer) -> ContainerRead:
    return ContainerRead.model_validate(row).model_copy(
        update={"my_access": access.level(actor, row)}
    )


# --- Containers -------------------------------------------------------------


@router.get("/containers", response_model=ContainerList)
async def list_containers(
    type: ContainerType | None = None,
    status: ContainerStatus | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.current_actor),
):
    items, total = await service.list_containers(
        db,
        actor.tenant_id,
        visible_to=access.visible(actor),
        type=type,
        status=status,
        skip=skip,
        limit=limit,
    )
    return {"items": [_read(actor, row) for row in items], "total": total}


@router.post("/containers", response_model=ContainerRead, status_code=201)
async def create_container(
    data: ContainerCreate,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.manage_actor),
):
    row = await service.create_container(
        db, actor.tenant_id, data, user_id=actor.user_id
    )
    return _read(actor, row)


@router.get("/containers/{container_id}", response_model=ContainerRead)
async def get_container(
    container_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.read_container),
):
    row = await service.get_container(db, actor.tenant_id, container_id)
    return _read(actor, row)


@router.patch("/containers/{container_id}", response_model=ContainerRead)
async def update_container(
    container_id: uuid.UUID,
    data: ContainerUpdate,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_container),
):
    # The owner edits the process but does not hand it over (HRP-810).
    if "owner_id" in data.model_fields_set and not actor.manage:
        raise AppError("work_container_owner_change_forbidden", 403)
    row = await service.update_container(
        db, actor.tenant_id, container_id, data, user_id=actor.user_id
    )
    return _read(actor, row)


@router.delete("/containers/{container_id}", status_code=204)
async def delete_container(
    container_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.manage_actor),
):
    await service.delete_container(db, actor.tenant_id, container_id)
    return Response(status_code=204)


@router.post("/containers/{container_id}/accept", response_model=ContainerRead)
async def accept_container(
    container_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_container),
):
    """The owner accepts the breakdown; admin and hr may accept any."""
    row = await service.accept_container(
        db,
        actor.tenant_id,
        container_id,
        user_id=actor.user_id,
        can_manage=actor.manage,
    )
    return _read(actor, row)


@router.get("/containers/{container_id}/access", response_model=ContainerAccessRead)
async def get_container_access(
    container_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_container),
):
    """The owner's and the managers' panel: who else reads, and the history."""
    return await service.get_container_access(db, actor.tenant_id, container_id)


@router.put("/containers/{container_id}/access", response_model=ContainerAccessRead)
async def set_container_access(
    container_id: uuid.UUID,
    data: ContainerAccessUpdate,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_container),
):
    return await service.set_container_access(
        db, actor.tenant_id, container_id, data, user_id=actor.user_id
    )


@router.get("/containers/{container_id}/people", response_model=list[ProcessPersonRead])
async def list_people(
    container_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_container),
):
    """Who the editor of this process can name: owner, rule, assignee.
    Whether each can take a step is HR data (HRP-623): the section's
    managers see it, an owner outside them is answered by the assignment."""
    return await service.list_people(db, actor.tenant_id, reveal_status=actor.manage)


# --- Steps ------------------------------------------------------------------


@router.get("/containers/{container_id}/steps", response_model=list[StepRead])
async def list_steps(
    container_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.read_container),
):
    return await service.list_steps(db, actor.tenant_id, container_id)


@router.post(
    "/containers/{container_id}/steps", response_model=StepRead, status_code=201
)
async def create_step(
    container_id: uuid.UUID,
    data: StepCreate,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_container),
):
    return await service.create_step(db, actor.tenant_id, container_id, data)


@router.put("/containers/{container_id}/steps/order", response_model=list[StepRead])
async def reorder_steps(
    container_id: uuid.UUID,
    data: StepOrder,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_container),
):
    return await service.reorder_steps(db, actor.tenant_id, container_id, data.step_ids)


@router.patch("/steps/{step_id}", response_model=StepRead)
async def update_step(
    step_id: uuid.UUID,
    data: StepUpdate,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_step),
):
    return await service.update_step(db, actor.tenant_id, step_id, data)


@router.delete("/steps/{step_id}", status_code=204)
async def delete_step(
    step_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_step),
):
    await service.delete_step(db, actor.tenant_id, step_id)
    return Response(status_code=204)


@router.put("/steps/{step_id}/primitives", response_model=StepRead)
async def set_step_primitives(
    step_id: uuid.UUID,
    data: StepPrimitivesUpdate,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_step),
):
    return await service.set_step_primitives(db, actor.tenant_id, step_id, data.codes)


@router.delete("/steps/{step_id}/primitives/{code}", response_model=StepRead)
async def remove_step_primitive(
    step_id: uuid.UUID,
    code: str,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_step),
):
    """Drop one capability of the step (HRP-776); the others are untouched."""
    return await service.remove_step_primitive(db, actor.tenant_id, step_id, code)


@router.post("/steps/{step_id}/primitives/{code}/confirm", response_model=StepRead)
async def confirm_step_primitive(
    step_id: uuid.UUID,
    code: str,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_step),
):
    """The company vouches for a code the model was unsure of (HRP-776)."""
    return await service.confirm_step_primitive(db, actor.tenant_id, step_id, code)


@router.post("/steps/{step_id}/reclassify", response_model=StepRead)
async def reclassify_step(
    step_id: uuid.UUID,
    data: ReclassifyRequest,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_step),
):
    """Synchronous: one classification call with the comment in context;
    the updated step comes back in the response."""
    return await service.reclassify_step(db, actor.tenant_id, step_id, data)


# --- Coverage (HRP-758) -----------------------------------------------------


@router.get("/containers/{container_id}/coverage", response_model=CoverageRead)
async def get_coverage(
    container_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.read_container),
    current_user: User = Depends(get_current_user),
):
    """A manager's read refreshes the competence mapping; a plain reader's
    does not start a model run. A matched colleague and what an assignee
    lacks come from assessments, so they are named within the reader's HR
    scope: everyone for admin / hr, the managed subtree for a manager, the
    reader themselves for anyone else (HRP-810, HRP-623)."""
    result = await coverage.compute(
        db,
        actor.tenant_id,
        container_id,
        user_id=actor.user_id,
        schedule_mapping=actor.manage,
    )
    visible = await get_visible_employee_ids(db, current_user)
    return (
        result if visible is None else coverage.redact_people(result, visible=visible)
    )


@router.get("/containers/{container_id}/gaps", response_model=list[GapRead])
async def list_gaps(
    container_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.read_container),
):
    return await coverage.gaps(
        db,
        actor.tenant_id,
        container_id,
        user_id=actor.user_id,
        schedule_mapping=actor.manage,
    )


@router.post(
    "/containers/{container_id}/gaps/hire-need",
    response_model=HireNeedRead,
    status_code=201,
)
async def create_hire_need(
    container_id: uuid.UUID,
    data: HireNeedCreate,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.manage_actor),
):
    """A person opens the hire need (§6); the section's managers are within
    the recruitment viewer roles the frontend gates the button on. The
    owner does not: a draft vacancy is Recruitment's record (HRP-810)."""
    return await service.create_hire_need(
        db, actor.tenant_id, container_id, data, user_id=actor.user_id
    )


# --- Step skills (HRP-760) ---------------------------------------------------


@router.post("/steps/{step_id}/skill", response_model=SkillRead, status_code=202)
async def generate_step_skill(
    step_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_step),
):
    """Queued (W6, §5.12): the row comes back ``generating`` and the
    screen polls ``GET`` until it is ready. Prechecked before the row is
    claimed, so a tenant without credits is refused rather than left with
    a row that blocks the button for three minutes."""
    action = service.BILLING_ACTION_SKILL
    cost = await billing_hooks.resolve_cost(db, actor.tenant_id, action)
    await billing_hooks.precheck_action(
        db, actor.tenant_id, action, amount_override=cost
    )
    row = await service.start_step_skill(
        db, actor.tenant_id, step_id, user_id=actor.user_id
    )
    row_id, stamp = row.id, row.updated_at

    from app.core.task_enqueue import enqueue_task
    from app.modules.work.tasks import generate_step_skill as task

    try:
        # HRP-547 hold for the minute the worker takes (§5.11): the To do
        # tab queues a whole section at once, and without a hold every one
        # of those requests would pass the same balance check before the
        # first worker deducted anything - a tenant with credit for one
        # skill could queue twelve and end up overdrawn.
        await billing_hooks.reserve_action(
            db,
            actor.tenant_id,
            actor.user_id,
            action,
            entity_type=SKILL_RESERVE_ENTITY,
            entity_id=row_id,
            ttl=service.SKILL_GENERATING_TIMEOUT,
            amount_override=cost,
        )
        await db.commit()
        enqueue_task(
            task,
            str(row_id),
            stamp.isoformat(),
            cost,
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            module="work",
            action=action,
        )
    except Exception as exc:
        # The row is already committed as generating and nothing will run
        # it: the hold was refused (a parallel request took the last of the
        # balance between the precheck and here) or the queue is down. Left
        # alone it would block the button until it goes stale three minutes
        # from now, and a hold would sit on the balance until the sweep.
        await db.rollback()
        await billing_hooks.release_action(
            db,
            actor.tenant_id,
            entity_type=SKILL_RESERVE_ENTITY,
            entity_id=row_id,
            action=action,
        )
        # The row says what the response says: on a refused hold that is
        # "credit limit reached", not a generic failure the user cannot act
        # on once the toast is gone.
        await service.fail_step_skill(
            db,
            row_id,
            exc.detail
            if isinstance(exc, AppError) and isinstance(exc.detail, str)
            else "Could not start the generation",
        )
        raise
    return row


@router.get("/steps/{step_id}/skill", response_model=SkillRead)
async def get_step_skill(
    step_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.read_step),
):
    return await service.get_step_skill(db, actor.tenant_id, step_id)


@router.get("/steps/{step_id}/skill/download")
async def download_step_skill(
    step_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.read_step),
):
    """The same text as a file. The name is fixed ASCII (the Agent Skills
    format wants ``SKILL.md``), so no RFC 5987 encoding is needed."""
    skill = await service.get_step_skill(db, actor.tenant_id, step_id)
    if skill.content is None:
        raise AppError("work_skill_not_found", 404)
    return Response(
        content=skill.content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="SKILL.md"'},
    )


# --- AI decomposition (HRP-755) ---------------------------------------------


@router.post("/decomposition/sessions", response_model=SessionRead, status_code=201)
async def create_session(
    data: SessionCreate,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.current_actor),
):
    # The container arrives in the body, so the edit check is here.
    await access.ensure(db, actor, data.container_id, edit=True)
    # Precheck before the row exists: a 402 must not leave a pending row
    # holding the container's one-active-run slot.
    action = service.BILLING_ACTION_START
    cost = await billing_hooks.resolve_cost(db, actor.tenant_id, action)
    await billing_hooks.precheck_action(
        db, actor.tenant_id, action, amount_override=cost
    )
    sess = await service.create_session(
        db, actor.tenant_id, actor.user_id, data.container_id, cost=cost
    )
    session_id = sess.id
    # Imported here like the other routers: Celery stays out of the
    # request-path import graph.
    from app.core.task_enqueue import enqueue_task
    from app.modules.work import tasks

    try:
        # HRP-547 hold for the minutes the worker takes, as the SKILL.md
        # path does: the one-active-run guard is per container, so without
        # a hold a tenant can start one run per container and every one of
        # them passes the same balance check before the first worker
        # deducts anything. The TTL is the reaper's cutoff - past it no
        # worker of this run is left to charge.
        await billing_hooks.reserve_action(
            db,
            actor.tenant_id,
            actor.user_id,
            action,
            entity_type=service.DECOMPOSITION_RESERVE_ENTITY,
            entity_id=session_id,
            ttl=timedelta(minutes=tasks.REAPER_STUCK_AGE_MINUTES),
            amount_override=cost,
        )
        await db.commit()
        result = enqueue_task(
            tasks.run_decomposition_session,
            str(session_id),
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            module="work",
            action=action,
        )
    except Exception:
        # The hold was refused (a parallel start took the last of the
        # balance between the precheck and here) or the queue is down. The
        # reaper only collects `running` rows: a pending row nobody will
        # ever run would hold the container's slot until someone deletes
        # it, and a hold would sit on the balance until the sweep.
        await db.rollback()
        await service.release_session_hold(db, actor.tenant_id, session_id)
        await service.fail_session(db, session_id, "Could not start the decomposition")
        raise
    sess.celery_task_id = result.id
    await db.commit()
    await db.refresh(sess)
    return sess


@router.get(
    "/containers/{container_id}/decomposition/latest",
    response_model=SessionRead | None,
)
async def latest_session(
    container_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.read_container),
):
    return await service.latest_session(db, actor.tenant_id, container_id)


@router.get("/decomposition/sessions/{session_id}", response_model=SessionRead)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.read_session),
):
    return await service.get_session(db, actor.tenant_id, session_id)


@router.post("/decomposition/sessions/{session_id}/apply", response_model=ApplyResult)
async def apply_session(
    session_id: uuid.UUID,
    data: SessionApply,
    force: bool = Query(
        False,
        description=(
            "Replace steps that carry a generated skill or the tenant's own "
            "edits; without it such a container answers 409."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_session),
):
    return await service.apply_session(
        db,
        actor.tenant_id,
        session_id,
        idempotency_key=data.idempotency_key,
        force=force,
    )


@router.delete("/decomposition/sessions/{session_id}", response_model=SessionRead)
async def cancel_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: access.Actor = Depends(access.edit_session),
):
    return await service.cancel_session(db, actor.tenant_id, session_id)
