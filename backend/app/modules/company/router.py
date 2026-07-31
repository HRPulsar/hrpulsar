import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.company import service
from app.modules.company.schemas import (
    ActivityFieldAdd,
    ActivityFieldRead,
    CompanyProfileRead,
    CompanyProfileUpdate,
    DivisionCreate,
    DivisionRead,
    DivisionScopeItem,
    DivisionTree,
    DivisionUpdate,
    LogoUrlIn,
    OnboardingStatusRead,
    SpecializationDivisionCreate,
    SpecializationDivisionRead,
    TenantRead,
    TenantUpdate,
)

router = APIRouter(tags=["company"])


# --- GF10 Improve: Public company profile ---


@router.get("/public/company/{slug}")
async def get_public_company_profile(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    result = await service.get_public_company_profile(db, slug)
    if result is None:
        raise AppError("company_not_found", status_code=404)
    return result


# --- Tenant ---


@router.get("/company", response_model=TenantRead)
async def get_company(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_tenant(db, current_user.tenant_id)


@router.put("/company", response_model=TenantRead)
async def update_company(
    data: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.update_tenant(db, current_user.tenant_id, data)


# --- GF10: Company Profile ---


@router.get("/settings/company-profile", response_model=CompanyProfileRead)
async def get_company_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_company_profile(db, current_user.tenant_id)


@router.put("/settings/company-profile", response_model=CompanyProfileRead)
async def update_company_profile(
    data: CompanyProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.update_company_profile(db, current_user.tenant_id, data)


@router.post("/settings/company-profile/logo", response_model=CompanyProfileRead)
async def upload_logo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.upload_logo(db, current_user.tenant_id, current_user.id, file)


@router.post(
    "/settings/company-profile/logo/from-url", response_model=CompanyProfileRead
)
async def upload_logo_from_url(
    payload: LogoUrlIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.upload_logo_from_url(
        db, current_user.tenant_id, current_user.id, str(payload.url)
    )


@router.delete("/settings/company-profile/logo", response_model=CompanyProfileRead)
async def delete_logo(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.delete_logo(db, current_user.tenant_id)


@router.post(
    "/settings/company-profile/activity-fields",
    response_model=ActivityFieldRead,
    status_code=201,
)
async def add_activity_field(
    data: ActivityFieldAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.add_activity_field(
        db, current_user.tenant_id, data.activity_field_id
    )


@router.delete(
    "/settings/company-profile/activity-fields/{activity_field_id}",
    response_model=ActivityFieldRead,
)
async def remove_activity_field(
    activity_field_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.remove_activity_field(
        db, current_user.tenant_id, activity_field_id
    )


# --- H3: Onboarding ---


@router.get("/onboarding/status", response_model=OnboardingStatusRead)
async def get_onboarding_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_onboarding_status(db, current_user.tenant_id)


@router.post("/onboarding/complete", response_model=TenantRead)
async def complete_onboarding(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.complete_onboarding(db, current_user.tenant_id)


# --- Divisions ---


@router.post("/divisions", response_model=DivisionRead, status_code=201)
async def create_division(
    data: DivisionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_division(db, current_user.tenant_id, data)


@router.get("/divisions", response_model=list[DivisionTree])
async def get_division_tree(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_division_tree(db, current_user.tenant_id)


@router.get("/divisions/scope", response_model=list[DivisionScopeItem])
async def get_division_scope(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Flat list of divisions visible to the current actor.

    - admin / hr / platform_admin → all tenant divisions.
    - manager → managed subtree only (own + descendants of managed divisions).
    - other roles → empty list.
    """
    from sqlalchemy import select

    from app.core.access_scope import get_visible_division_ids
    from app.modules.company.models import Division

    visible = await get_visible_division_ids(db, current_user)
    stmt = (
        select(Division.id, Division.name)
        .where(Division.tenant_id == current_user.tenant_id)
        .order_by(Division.name)
    )
    if visible is not None:
        if not visible:
            return []
        stmt = stmt.where(Division.id.in_(visible))
    result = await db.execute(stmt)
    return [{"id": r.id, "name": r.name} for r in result.all()]


@router.get("/divisions/{division_id}", response_model=DivisionRead)
async def get_division(
    division_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_division(db, current_user.tenant_id, division_id)


@router.put("/divisions/{division_id}", response_model=DivisionRead)
async def update_division(
    division_id: uuid.UUID,
    data: DivisionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_division(db, current_user.tenant_id, division_id, data)


@router.delete("/divisions/{division_id}", status_code=204)
async def delete_division(
    division_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_division(db, current_user.tenant_id, division_id)


# --- GF7: Specialization-Division Mapping ---


@router.get(
    "/divisions/{division_id}/specializations",
    response_model=list[SpecializationDivisionRead],
)
async def list_division_specializations(
    division_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_division_specializations(
        db, current_user.tenant_id, division_id
    )


@router.post(
    "/divisions/{division_id}/specializations",
    response_model=SpecializationDivisionRead,
    status_code=201,
)
async def add_division_specialization(
    division_id: uuid.UUID,
    data: SpecializationDivisionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.add_division_specialization(
        db, current_user.tenant_id, division_id, data
    )


@router.delete(
    "/divisions/{division_id}/specializations/{specialization_id}",
    response_model=SpecializationDivisionRead,
)
async def remove_division_specialization(
    division_id: uuid.UUID,
    specialization_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.remove_division_specialization(
        db, current_user.tenant_id, division_id, specialization_id
    )
