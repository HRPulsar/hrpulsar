"""HTTP layer for the moderated signup flow (HRP-259 — M1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import client_ip
from app.core.i18n import resolve_locale_from_request
from app.database import get_db
from app.modules.signup import service
from app.modules.signup.schemas import (
    SignupRequestCreate,
    SignupRequestRead,
    SignupVerifyRequest,
    SignupVerifyResponse,
)

router = APIRouter(prefix="/signup-request", tags=["signup"])


def _client_ip(request: Request) -> str | None:
    """Trusted-proxy-aware source IP for rate limiting (review P2-29).

    Delegates to the shared helper: honours ``X-Forwarded-For`` only when the
    socket peer is a configured trusted proxy, so behind the edge LB the
    throttle keys on the real client rather than the shared LB IP.
    """
    return client_ip(request)


@router.post(
    "",
    response_model=SignupRequestRead,
    status_code=status.HTTP_201_CREATED,
)
async def create(
    payload: SignupRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SignupRequestRead:
    row = await service.create_signup_request(
        db,
        payload,
        remote_ip=_client_ip(request),
        request_locale=resolve_locale_from_request(request),
    )
    return SignupRequestRead.model_validate(row, from_attributes=True)


@router.post(
    "/verify",
    response_model=SignupVerifyResponse,
)
async def verify(
    payload: SignupVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> SignupVerifyResponse:
    row, already = await service.verify_signup_request(db, payload.token)
    return SignupVerifyResponse(
        id=row.id,
        email=row.email,
        status=row.status,
        already_verified=already,
    )
