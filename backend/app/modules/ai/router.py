import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import billing_hooks
from app.core.schemas import TaskAccepted
from app.database import get_db
from app.modules.ai import service
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User

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


class EmbedRequest(BaseModel):
    entity_type: str = Field(max_length=50)
    entity_id: uuid.UUID
    text_content: str = Field(max_length=5000)


class BatchEmbedRequest(BaseModel):
    items: list[EmbedRequest] = Field(min_length=1, max_length=100)


class SearchRequest(BaseModel):
    query: str = Field(max_length=1000)
    entity_type: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


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
    current_user: User = Depends(require_role("admin", "manager")),
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
    current_user: User = Depends(require_role("admin", "manager")),
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
    current_user: User = Depends(require_role("admin", "manager")),
):
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
    current_user: User = Depends(require_role("admin", "manager")),
):
    if sync:
        return await service.generate_positions(
            db, current_user.tenant_id, current_user.id
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
        cost,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module="ai",
        action="generate_positions",
    )
    response.status_code = status.HTTP_202_ACCEPTED
    return {"task_id": result.id}


@router.post("/ai/embed")
async def create_embedding(
    data: EmbedRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    return await service.create_embedding(
        db, data.entity_type, data.entity_id, data.text_content
    )


@router.post("/ai/search")
async def semantic_search(
    data: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.semantic_search(
        db,
        current_user.tenant_id,
        current_user.id,
        data.query,
        data.entity_type,
        data.limit,
    )


# --- I3d: Batch embedding endpoint ---


@router.post("/ai/embed/batch", response_model=TaskAccepted)
async def batch_embed(
    data: BatchEmbedRequest,
    current_user: User = Depends(require_role("admin")),
):
    """Queue batch embedding generation as background task."""
    from app.core.task_enqueue import enqueue_task
    from app.modules.ai.tasks import batch_embed_task

    items = [
        {
            "entity_type": item.entity_type,
            "entity_id": str(item.entity_id),
            "text_content": item.text_content,
        }
        for item in data.items
    ]
    result = enqueue_task(
        batch_embed_task,
        items,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module="ai",
        action="batch_embed",
    )
    return {"task_id": result.id}
