"""Consent endpoints: templates, requests, public token view/sign (R3a)."""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    Request,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.recruitment import (
    service,
)
from app.modules.recruitment.routers.common import recruitment_public_limiter
from app.modules.recruitment.schemas import (
    ConsentRequestRead,
    ConsentSendRequest,
    ConsentSignResult,
    ConsentTemplateCreate,
    ConsentTemplateRead,
    ConsentTemplateUpdate,
    ConsentTokenView,
)

router = APIRouter(tags=["recruitment"])


# ── Consent (R3a) ──────────────────────────────────────────────────


@router.get(
    "/recruitment/consent-templates",
)
async def list_consent_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.list_consent_templates(db, current_user.tenant_id)


@router.post(
    "/recruitment/consent-templates",
    response_model=ConsentTemplateRead,
    status_code=201,
)
async def create_consent_template(
    data: ConsentTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.create_consent_template(
        db, current_user.tenant_id, data
    )


@router.put(
    "/recruitment/consent-templates/{template_id}",
    response_model=ConsentTemplateRead,
)
async def update_consent_template(
    template_id: uuid.UUID,
    data: ConsentTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.update_consent_template(
        db, current_user.tenant_id, template_id, data
    )


@router.get(
    "/recruitment/candidates/{candidate_id}/consent/latest",
)
async def get_latest_consent(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Most recent consent request for the candidate (or null)."""
    return await service.get_latest_consent(
        db, current_user.tenant_id, candidate_id
    )


@router.post(
    "/recruitment/candidates/{candidate_id}/consent/send",
    response_model=ConsentRequestRead,
    status_code=202,
)
async def send_consent_request(
    candidate_id: uuid.UUID,
    data: ConsentSendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.send_consent_request(
        db, current_user.tenant_id, current_user.id, candidate_id, data
    )


@router.get(
    "/recruitment/consent/{token}",
    response_model=ConsentTokenView,
)
@recruitment_public_limiter.limit("60/minute")
async def get_consent_by_token(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — no auth, token-based."""

    return await service.get_consent_by_token(db, token)


@router.post(
    "/recruitment/consent/{token}/sign",
    response_model=ConsentSignResult,
)
@recruitment_public_limiter.limit("10/minute")
async def sign_consent(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — record candidate consent signature."""

    client_ip = (
        request.client.host
        if request.client and request.client.host
        else None
    )
    user_agent = request.headers.get("user-agent")
    return await service.sign_consent(
        db,
        token,
        signed_ip=client_ip,
        signed_user_agent=user_agent,
    )
