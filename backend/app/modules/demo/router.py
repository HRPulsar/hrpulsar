"""Public-demo sandbox router (HRP-251 — D3, HRP-256 — D8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.client_ip import client_ip
from app.core.errors import AppError
from app.core.i18n import resolve_locale_from_request
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.demo.schemas import (
    DemoSaveAccessRequest,
    DemoSaveAccessResponse,
    DemoStartRequest,
    DemoStartResponse,
    DemoSwitchViewRequest,
    DemoSwitchViewResponse,
)
from app.modules.demo.service import create_demo_session, switch_demo_view
from app.modules.demo.utils import is_demo_tenant
from app.modules.signup.schemas import SignupRequestCreate
from app.modules.signup.service import create_signup_request


async def _require_saas_deployment() -> None:
    # HRP-391: the public-demo sandbox is enterprise-only. Community /
    # self-hosted deployments (deployment_mode=onprem) must not expose
    # any demo endpoint — 404, not 403, so the surface is invisible.
    # Deliberately a bare HTTPException, not AppError: an error code would
    # fingerprint the hidden surface.
    if settings.deployment_mode != "saas":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


router = APIRouter(
    prefix="/demo",
    tags=["demo"],
    dependencies=[Depends(_require_saas_deployment)],
)


@router.post(
    "/start",
    response_model=DemoStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_demo_session(
    payload: DemoStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> DemoStartResponse:
    """Create a fresh public-demo sandbox.

    No authentication required. The caller passes a Cloudflare
    Turnstile token (when the server is configured for it) and gets
    back an access JWT scoped to a throw-away ``Tenant`` plus the
    front-end redirect URL that lands on the demo's first screen.
    No refresh token is issued (HRP-276 / M7) — the access token's
    TTL is pinned to the demo tenant lifetime.

    If the caller forwards their existing demo bearer token in
    ``Authorization`` and it still resolves to a live demo tenant the
    same session is returned (``resumed=true``) — clicking "Try the
    demo" twice no longer strands the old sandbox.
    """
    result = await create_demo_session(
        db,
        turnstile_token=payload.turnstile_token,
        remote_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        existing_token=_bearer_token(authorization),
    )

    # HRP-276 / M7: no refresh cookie for demo sessions — the access
    # token's TTL is pinned to the demo tenant lifetime.
    return DemoStartResponse(**result)


@router.post(
    "/save-access",
    response_model=DemoSaveAccessResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_demo_access(
    payload: DemoSaveAccessRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DemoSaveAccessResponse:
    """Capture a demo session as a pending signup request.

    Only callable from a real demo tenant — the dependency chain
    rejects a paid-account bearer with 403. The visitor flows back
    through the same email-verify → Slack moderation → magic-login
    pipeline as the landing form; on approve we provision a brand-new
    Tenant, or — when ``keep_demo_data`` was checked and the sandbox
    still exists — convert the demo tenant into the real workspace.
    """
    if not await is_demo_tenant(db, current_user.tenant_id):
        raise AppError(
            "demo_capture_requires_demo_session",
            status.HTTP_403_FORBIDDEN,
        )
    create_payload = SignupRequestCreate(
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        company_name=payload.company_name,
        role=payload.role,
        turnstile_token=payload.turnstile_token,
    )
    row = await create_signup_request(
        db,
        create_payload,
        remote_ip=_client_ip(request),
        source="demo",
        demo_tenant_id_snapshot=current_user.tenant_id,
        keep_demo_data=payload.keep_demo_data,
        request_locale=resolve_locale_from_request(request),
    )
    return DemoSaveAccessResponse(
        signup_request_id=row.id,
        email=row.email,
        status=row.status,
    )


@router.post("/switch-view", response_model=DemoSwitchViewResponse)
async def switch_view(
    payload: DemoSwitchViewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DemoSwitchViewResponse:
    """Swap the demo session between the admin and employee personas.

    Only callable with a live demo-tenant bearer — a paid-account token
    is rejected with 403 inside the service. The issued token is scoped
    to the same demo tenant, so no cross-tenant hop is possible.
    """
    result = await switch_demo_view(
        db, tenant_id=current_user.tenant_id, persona=payload.persona
    )
    return DemoSwitchViewResponse(**result)


def _bearer_token(header: str | None) -> str | None:
    """Pull the raw JWT out of an ``Authorization: Bearer …`` header.

    Returns ``None`` for a missing or malformed header — /demo/start
    treats that as "no resume hint" and provisions a fresh session.
    """
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


# Trusted-proxy-aware source IP now lives in app.core.client_ip (review P2-29);
# ``settings.trusted_proxies`` inherits ``demo_trusted_proxies`` for back-compat.
def _client_ip(request: Request) -> str | None:
    return client_ip(request)
