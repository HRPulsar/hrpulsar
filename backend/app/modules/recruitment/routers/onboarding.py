"""Recruitment onboarding wizard endpoints (R4c)."""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import require_role
from app.modules.auth.models import User
from app.modules.recruitment import (
    onboarding_service,
)
from app.modules.recruitment.schemas import (
    OnboardingState,
)

router = APIRouter(tags=["recruitment"])


# ── R4c: Onboarding wizard ───────────────────────────────────────────


@router.get("/recruitment/onboarding", response_model=OnboardingState)
async def get_onboarding(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hr", "hrd")),
):
    return await onboarding_service.get_state(db, current_user.tenant_id)


@router.post("/recruitment/onboarding/dismiss", response_model=OnboardingState)
async def dismiss_onboarding(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hr", "hrd")),
):
    return await onboarding_service.dismiss(db, current_user.tenant_id)


@router.post("/recruitment/onboarding/demo-seed", status_code=201)
async def seed_recruitment_demo(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await onboarding_service.seed_demo(
        db, current_user.tenant_id, current_user.id
    )


@router.post("/recruitment/onboarding/demo-cleanup")
async def cleanup_recruitment_demo(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await onboarding_service.cleanup_demo(db, current_user.tenant_id)
