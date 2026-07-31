import uuid

from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.dependencies import require_role
from app.modules.auth.models import User
from app.modules.company.models import Division
from app.modules.dictionary.models import DictionaryItem
from app.modules.dictionary.service import effective_is_active_expr
from app.modules.employee.models import Employee
from app.modules.public_api import service
from app.modules.public_api.schemas import (
    AssessmentBatchCreate,
    DivisionBatchCreate,
    EmployeeBatchCreate,
    EmployeeBatchUpdate,
    ExamBatchAssign,
    GradeBatchCreate,
    SpecializationBatchCreate,
)


def _get_api_key_for_rate_limit(request: Request) -> str:
    return request.headers.get("X-API-Key", get_remote_address(request))


limiter = Limiter(key_func=_get_api_key_for_rate_limit, key_style="endpoint")

router = APIRouter(tags=["public-api"])


# --- API Key management (admin) ---


class APIKeyCreate(BaseModel):
    name: str = Field(max_length=255)


class APIKeyRead(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    is_active: bool | None = None
    last_used_at: str | None = None
    created_at: str | None = None
    key: str | None = None  # Only on creation


@router.post("/api-keys", status_code=201)
async def create_api_key(
    data: APIKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.create_api_key(
        db, current_user.tenant_id, current_user.id, data.name
    )


@router.get("/api-keys")
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.list_api_keys(db, current_user.tenant_id)


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.revoke_api_key(db, current_user.tenant_id, key_id)


# --- Public API endpoints (API key auth) ---


async def _get_tenant_from_api_key(
    x_api_key: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    key = await service.authenticate_api_key(db, x_api_key)
    if not key:
        raise AppError("invalid_api_key", status.HTTP_401_UNAUTHORIZED)
    return key


# --- Read endpoints ---


@router.get("/v1/employees")
@limiter.limit(settings.public_api_rate_limit)
async def public_list_employees(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    division_id: uuid.UUID | None = None,
    status_filter: str | None = Query(None, alias="status"),
    api_key=Depends(_get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = api_key.tenant_id
    base = select(Employee).where(Employee.tenant_id == tenant_id)
    count_q = select(func.count(Employee.id)).where(Employee.tenant_id == tenant_id)

    if division_id:
        base = base.where(Employee.division_id == division_id)
        count_q = count_q.where(Employee.division_id == division_id)
    if status_filter:
        base = base.where(Employee.status == status_filter)
        count_q = count_q.where(Employee.status == status_filter)

    result = await db.execute(base.offset(skip).limit(limit))
    total_r = await db.execute(count_q)
    employees = result.scalars().all()
    return {
        "items": [
            {
                "id": str(e.id),
                "user_id": str(e.user_id),
                "position": e.position,
                "hire_date": str(e.hire_date),
                "status": e.status,
                "division_id": str(e.division_id) if e.division_id else None,
                "user_email": e.user.email if e.user else None,
                "user_name": (
                    f"{e.user.first_name} {e.user.last_name}" if e.user else None
                ),
            }
            for e in employees
        ],
        "total": total_r.scalar() or 0,
    }


@router.get("/v1/divisions")
@limiter.limit(settings.public_api_rate_limit)
async def public_list_divisions(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    api_key=Depends(_get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = api_key.tenant_id
    result = await db.execute(
        select(Division)
        .where(Division.tenant_id == tenant_id)
        .offset(skip)
        .limit(limit)
    )
    total_r = await db.execute(
        select(func.count(Division.id)).where(Division.tenant_id == tenant_id)
    )
    return {
        "items": [
            {
                "id": str(d.id),
                "name": d.name,
                "description": d.description,
                "parent_id": str(d.parent_id) if d.parent_id else None,
            }
            for d in result.scalars().all()
        ],
        "total": total_r.scalar() or 0,
    }


async def _dictionary_items_page(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    item_type: str,
    skip: int,
    limit: int,
) -> tuple[list[tuple[DictionaryItem, bool]], int]:
    """Page of dictionary items with the tenant-effective ``is_active`` (HRP-380).

    System (origin) items can be deactivated per tenant; the raw column
    would report them as active to integrations.
    """
    tenant_scope = or_(
        DictionaryItem.tenant_id == tenant_id,
        DictionaryItem.tenant_id.is_(None),
    )
    result = await db.execute(
        select(DictionaryItem, effective_is_active_expr(tenant_id))
        .where(DictionaryItem.type == item_type, tenant_scope)
        # id tiebreaker: sort_index ties would otherwise reorder between
        # OFFSET pages, letting integrations skip or duplicate rows.
        .order_by(DictionaryItem.sort_index, DictionaryItem.id)
        .offset(skip)
        .limit(limit)
    )
    total_r = await db.execute(
        select(func.count(DictionaryItem.id)).where(
            DictionaryItem.type == item_type, tenant_scope
        )
    )
    return list(result.tuples().all()), total_r.scalar() or 0


@router.get("/v1/specializations")
@limiter.limit(settings.public_api_rate_limit)
async def public_list_specializations(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    api_key=Depends(_get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await _dictionary_items_page(
        db, api_key.tenant_id, "specialization", skip, limit
    )
    return {
        "items": [
            {
                "id": str(i.id),
                "title": i.title,
                "description": i.description,
                "is_active": is_active,
            }
            for i, is_active in rows
        ],
        "total": total,
    }


@router.get("/v1/grades")
@limiter.limit(settings.public_api_rate_limit)
async def public_list_grades(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    api_key=Depends(_get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await _dictionary_items_page(
        db, api_key.tenant_id, "grade", skip, limit
    )
    return {
        "items": [
            {
                "id": str(i.id),
                "title": i.title,
                "description": i.description,
                "is_active": is_active,
                "sort_index": i.sort_index,
            }
            for i, is_active in rows
        ],
        "total": total,
    }


@router.get("/v1/dictionaries/{item_type}")
@limiter.limit(settings.public_api_rate_limit)
async def public_list_dictionaries(
    request: Request,
    item_type: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    api_key=Depends(_get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await _dictionary_items_page(
        db, api_key.tenant_id, item_type, skip, limit
    )
    return {
        "items": [
            {
                "id": str(i.id),
                "title": i.title,
                "description": i.description,
                "is_active": is_active,
            }
            for i, is_active in rows
        ],
        "total": total,
    }


# --- Batch write endpoints ---


@router.post("/v1/employees:batch", status_code=200)
@limiter.limit(settings.public_api_rate_limit)
async def public_batch_create_employees(
    request: Request,
    data: EmployeeBatchCreate,
    api_key=Depends(_get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    return await service.batch_create_employees(db, api_key.tenant_id, data.items)


@router.patch("/v1/employees:batch", status_code=200)
@limiter.limit(settings.public_api_rate_limit)
async def public_batch_update_employees(
    request: Request,
    data: EmployeeBatchUpdate,
    api_key=Depends(_get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    return await service.batch_update_employees(db, api_key.tenant_id, data.items)


@router.post("/v1/divisions:batch", status_code=200)
@limiter.limit(settings.public_api_rate_limit)
async def public_batch_create_divisions(
    request: Request,
    data: DivisionBatchCreate,
    api_key=Depends(_get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    return await service.batch_create_divisions(db, api_key.tenant_id, data.items)


@router.post("/v1/specializations:batch", status_code=200)
@limiter.limit(settings.public_api_rate_limit)
async def public_batch_create_specializations(
    request: Request,
    data: SpecializationBatchCreate,
    api_key=Depends(_get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    return await service.batch_create_specializations(db, api_key.tenant_id, data.items)


@router.post("/v1/grades:batch", status_code=200)
@limiter.limit(settings.public_api_rate_limit)
async def public_batch_create_grades(
    request: Request,
    data: GradeBatchCreate,
    api_key=Depends(_get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    return await service.batch_create_grades(db, api_key.tenant_id, data.items)


@router.post("/v1/assessments:batch", status_code=200)
@limiter.limit(settings.public_api_rate_limit)
async def public_batch_create_assessments(
    request: Request,
    data: AssessmentBatchCreate,
    api_key=Depends(_get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    return await service.batch_create_assessments(
        db, api_key.tenant_id, api_key.created_by, data
    )


@router.post("/v1/exams:batch", status_code=200)
@limiter.limit(settings.public_api_rate_limit)
async def public_batch_assign_exams(
    request: Request,
    data: ExamBatchAssign,
    api_key=Depends(_get_tenant_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    return await service.batch_assign_exams(db, api_key.tenant_id, data)


# --- OpenAPI spec ---


@router.get("/v1/openapi.json")
@limiter.limit(settings.public_api_rate_limit)
async def public_openapi_spec(
    request: Request,
    api_key=Depends(_get_tenant_from_api_key),
):
    """Return OpenAPI spec filtered to Public API v1 endpoints only."""
    from fastapi.openapi.utils import get_openapi

    full_schema = get_openapi(
        title=f"{settings.brand_name} Public API",
        version="1.0.0",
        description=f"{settings.brand_name} Public API for external integrations. Authenticate with X-API-Key header.",
        routes=request.app.routes,
    )

    # Filter to /v1/ paths only
    filtered_paths = {}
    for path, methods in full_schema.get("paths", {}).items():
        if "/v1/" in path:
            filtered_paths[path] = methods

    full_schema["paths"] = filtered_paths
    full_schema["info"]["title"] = f"{settings.brand_name} Public API"
    full_schema["info"]["description"] = (
        f"{settings.brand_name} Public API for external integrations.\n\n"
        "## Authentication\n"
        "All endpoints require an API key passed via the `X-API-Key` header.\n"
        f"API keys can be created by tenant admins via the {settings.brand_name} dashboard.\n\n"
        "## Rate Limiting\n"
        f"All endpoints are rate-limited to {settings.public_api_rate_limit} per API key.\n\n"
        "## Batch Operations\n"
        f"Batch endpoints accept up to {settings.public_api_batch_max_items} items per request.\n"
        "Responses include per-item results with partial success support."
    )

    return full_schema
