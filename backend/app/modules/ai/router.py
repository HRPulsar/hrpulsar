import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import billing_hooks
from app.core.errors import AppError
from app.core.sections import require_section
from app.database import get_db
from app.modules.ai import service
from app.modules.assessment.scope import assert_assessment_in_scope
from app.modules.auth.models import User
from app.modules.position.scope import resolve_managed_divisions

router = APIRouter(tags=["ai"])


class GenerateCompetencesRequest(BaseModel):
    specialization: str = Field(max_length=255)
    company_description: str = Field(default="", max_length=2000)
    activity_fields: str = Field(default="", max_length=1000)


class GenerateIndicatorsRequest(BaseModel):
    competence_title: str = Field(max_length=300)
    context: str = Field(default="", max_length=1000)


class SuggestPDPRequest(BaseModel):
    assessment_id: uuid.UUID


# ---------------------------------------------------------------------------
# AI generation — default async (202 + task_id), ?sync=true for legacy.
#
# Deliberately NO response_model on the generate-* endpoints: they are
# polymorphic on ?sync= (async branch returns {task_id}, sync branch returns
# the service result), so a single model would break the sync branch.
#
# Default async because the LLM call takes 5–60 s and synchronous handlers
# pinned a DB pool slot for the whole duration. precheck_credits runs in the
# handler so
# 402s short-circuit before we enqueue; consume_credits runs inside the
# Celery task after the work succeeds.
# ---------------------------------------------------------------------------


@router.post("/ai/generate-competences")
async def generate_competences(
    data: GenerateCompetencesRequest,
    response: Response,
    sync: bool = Query(False, description="Run synchronously (legacy clients)"),
    db: AsyncSession = Depends(get_db),
    # HRP-827: drafting the catalogue is authoring it - ``/ai`` sits outside
    # the gate, so the ``competences`` level is asked here.
    current_user: User = Depends(require_section("competences", "manage")),
):
    if sync:
        return await service.generate_competences(
            db,
            current_user.tenant_id,
            current_user.id,
            data.specialization,
            data.company_description,
            data.activity_fields,
        )
    cost = await billing_hooks.resolve_cost(
        db, current_user.tenant_id, "ai.generate_competences"
    )
    await billing_hooks.precheck_action(
        db, current_user.tenant_id, "ai.generate_competences", amount_override=cost
    )
    from app.core.task_enqueue import enqueue_task
    from app.modules.ai.tasks import generate_competences_task

    result = enqueue_task(
        generate_competences_task,
        str(current_user.tenant_id),
        str(current_user.id),
        data.specialization,
        data.company_description,
        data.activity_fields,
        cost,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module="ai",
        action="generate_competences",
    )
    response.status_code = status.HTTP_202_ACCEPTED
    return {"task_id": result.id}


@router.post("/ai/generate-indicators")
async def generate_indicators(
    data: GenerateIndicatorsRequest,
    response: Response,
    sync: bool = Query(False, description="Run synchronously (legacy clients)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_section("competences", "manage")),
):
    if sync:
        return await service.generate_indicators(
            db,
            current_user.tenant_id,
            current_user.id,
            data.competence_title,
            data.context,
        )
    cost = await billing_hooks.resolve_cost(
        db, current_user.tenant_id, "ai.generate_indicators"
    )
    await billing_hooks.precheck_action(
        db, current_user.tenant_id, "ai.generate_indicators", amount_override=cost
    )
    from app.core.task_enqueue import enqueue_task
    from app.modules.ai.tasks import generate_indicators_task

    result = enqueue_task(
        generate_indicators_task,
        str(current_user.tenant_id),
        str(current_user.id),
        data.competence_title,
        data.context,
        cost,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module="ai",
        action="generate_indicators",
    )
    response.status_code = status.HTTP_202_ACCEPTED
    return {"task_id": result.id}


@router.post("/ai/suggest-pdp")
async def suggest_pdp(
    data: SuggestPDPRequest,
    response: Response,
    sync: bool = Query(False, description="Run synchronously (legacy clients)"),
    db: AsyncSession = Depends(get_db),
    # HRP-825: drafting a plan is authoring one - ``/ai`` sits outside the
    # gate, so the ``development`` level is asked here.
    current_user: User = Depends(require_section("development", "manage")),
):
    # HRP-638: the plan is drafted for the assessment's assessee and paid
    # for out of the tenant's credits, so the same subtree fence as the
    # assessment routes applies before either branch spends anything.
    await assert_assessment_in_scope(db, current_user, data.assessment_id)
    if sync:
        return await service.suggest_pdp(
            db, current_user.tenant_id, current_user.id, data.assessment_id
        )
    cost = await billing_hooks.resolve_cost(
        db, current_user.tenant_id, "ai.generate_pdp_goals"
    )
    await billing_hooks.precheck_action(
        db, current_user.tenant_id, "ai.generate_pdp_goals", amount_override=cost
    )
    from app.core.task_enqueue import enqueue_task
    from app.modules.ai.tasks import suggest_pdp_task

    result = enqueue_task(
        suggest_pdp_task,
        str(current_user.tenant_id),
        str(current_user.id),
        str(data.assessment_id),
        cost,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module="ai",
        action="suggest_pdp",
    )
    response.status_code = status.HTTP_202_ACCEPTED
    return {"task_id": result.id}


@router.post("/ai/generate-positions")
async def generate_positions(
    response: Response,
    sync: bool = Query(False, description="Run synchronously (legacy clients)"),
    db: AsyncSession = Depends(get_db),
    # HRP-828: drafting positions is authoring them - ``/ai`` sits outside
    # the gate, so the ``company`` level is asked here.
    current_user: User = Depends(require_section("company", "manage")),
):
    # HRP-631 (QA 06.10): the generator drafts the workspace's job
    # catalogue, so it is for the roles whose write scope is the workspace
    # (``ADMIN_ROLE_CODES``). Anyone scoped to a subtree - a division head,
    # or a role the tenant raised to ``manage`` - is refused before the run
    # is charged; they author positions by hand inside their subtree.
    if await resolve_managed_divisions(db, current_user) is not None:
        raise AppError("auth_insufficient_permissions", status.HTTP_403_FORBIDDEN)
    if sync:
        return await service.generate_positions(
            db, current_user.tenant_id, current_user.id, None
        )
    cost = await billing_hooks.resolve_cost(
        db, current_user.tenant_id, "ai.generate_positions"
    )
    await billing_hooks.precheck_action(
        db, current_user.tenant_id, "ai.generate_positions", amount_override=cost
    )
    from app.core.task_enqueue import enqueue_task
    from app.modules.ai.tasks import generate_positions_task

    result = enqueue_task(
        generate_positions_task,
        str(current_user.tenant_id),
        str(current_user.id),
        None,
        cost,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module="ai",
        action="generate_positions",
    )
    response.status_code = status.HTTP_202_ACCEPTED
    return {"task_id": result.id}
