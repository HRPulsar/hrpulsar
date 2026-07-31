import logging
import uuid

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from jwt import PyJWTError as JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.client_ip import client_ip
from app.core.errors import AppError
from app.core.security import decode_token
from app.database import get_db
from app.modules.auth import service
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    AcceptInvitationRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    InvitationBulkCreate,
    InvitationCreate,
    InvitationEmailUpdate,
    InvitationList,
    InvitationRead,
    InvitationUpdate,
    LoginRequest,
    MagicLoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    SelectTenantRequest,
    SwitchTenantRequest,
    TenantInfo,
    TokenResponse,
    UserRead,
    UserUpdate,
    VerifyEmailRequest,
    VerifyEmailResponse,
)

logger = logging.getLogger(__name__)


def _invitation_rate_key(request: Request) -> str:
    """Per-user rate-limit key (falls back to remote address for anonymous calls).

    Result is memoized on `request.state` so we don't re-decode the JWT once
    `get_current_user` has already done it on the same request.
    """
    cached = getattr(request.state, "rate_limit_key", None)
    if cached is not None:
        return cached
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        try:
            payload = decode_token(token)
            user_id = payload.get("sub")
            if user_id:
                key = f"user:{user_id}"
                request.state.rate_limit_key = key
                return key
        except JWTError:
            pass
    # Trusted-proxy-aware source IP for anonymous callers (review P2-29).
    fallback = client_ip(request) or get_remote_address(request)
    request.state.rate_limit_key = fallback
    return fallback


# key_style="endpoint": slowapi's default ("url") buckets by the full path,
# so per-invitation URLs (/invitations/{id}/resend) would each get their own
# bucket and a user could multiply the resend budget by creating invitations.
invitations_limiter = Limiter(key_func=_invitation_rate_key, key_style="endpoint")


def _auth_ip_key(request: Request) -> str:
    """Per-source-IP key for the unauthenticated auth surface.

    Trusted-proxy-aware (see :func:`app.core.client_ip.client_ip`) so a
    forged ``X-Forwarded-For`` from a direct origin hit can't mint a fresh
    throttle bucket per request.
    """
    return client_ip(request) or "anonymous"


# Separate limiter for the auth abuse surface (login spray, mail-bomb via
# forgot/resend, refresh/magic-link enumeration). Keyed by source IP; the
# invitations limiter above stays keyed by user id.
auth_limiter = Limiter(key_func=_auth_ip_key, key_style="endpoint")

# E2E suites drive hundreds of UI logins from a single host IP, so the
# per-IP abuse limiter would flake them with 429s. Same tier check as
# _require_dev_endpoint: a stray E2E_MODE=true on a deployed environment
# keeps the limiter armed.
if settings.e2e_mode and (settings.sentry_environment or "").lower() not in {
    "production",
    "staging",
}:
    auth_limiter.enabled = False


def _require_dev_endpoint() -> None:
    """Guard for the E2E/dev-only auth endpoints below.

    404 unless ``E2E_MODE`` is on AND we are not on a deployed tier —
    belt-and-braces (review P3-48) so a misconfigured production carrying a
    stray ``E2E_MODE=true`` still cannot expose auto-register / token reveal /
    origin-group seeding.
    """
    env = (settings.sentry_environment or "").lower()
    if not settings.e2e_mode or env in {"production", "staging"}:
        # Deliberately a bare HTTPException, not AppError: the response must
        # stay indistinguishable from a nonexistent route — an error code
        # would fingerprint the hidden dev surface.
        raise HTTPException(status_code=404, detail="Not found")


router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=RegisterResponse, status_code=201)
@auth_limiter.limit(settings.auth_rate_limit_register)
async def register(
    request: Request, data: RegisterRequest, db: AsyncSession = Depends(get_db)
):
    return await service.register(
        db, data, accept_language=request.headers.get("accept-language")
    )


@router.post("/auth/verify-email", response_model=VerifyEmailResponse)
async def verify_email(data: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    return await service.verify_email(db, data.token)


@router.post("/auth/resend-verification")
@auth_limiter.limit(settings.auth_rate_limit_email)
async def resend_verification(
    request: Request,
    data: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    await service.resend_verification(
        db, data.email, accept_language=request.headers.get("accept-language")
    )
    return {
        "message": "If this email exists and is unverified, a verification link has been sent"
    }


@router.post("/auth/login")
@auth_limiter.limit(settings.auth_rate_limit_login)
async def login(
    request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)
):
    return await service.login(db, data.email, data.password)


@router.post("/auth/select-tenant", response_model=TokenResponse)
@auth_limiter.limit(settings.auth_rate_limit_login)
async def select_tenant(
    request: Request, data: SelectTenantRequest, db: AsyncSession = Depends(get_db)
):
    return await service.select_tenant(db, data.email, data.password, data.tenant_id)


@router.post("/auth/switch-tenant", response_model=TokenResponse)
async def switch_tenant(
    data: SwitchTenantRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.switch_tenant(
        db, current_user.id, current_user.email, data.tenant_id
    )


@router.get("/auth/tenants", response_model=list[TenantInfo])
async def list_my_tenants(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_user_tenants(db, current_user.email)


@router.post("/auth/magic-login", response_model=VerifyEmailResponse)
@auth_limiter.limit(settings.auth_rate_limit_email)
async def magic_login(
    request: Request, data: MagicLoginRequest, db: AsyncSession = Depends(get_db)
):
    """Consume a one-time signup magic-login token (HRP-262 — M4).

    Returns the same shape as ``/auth/verify-email`` so the SPA can
    treat both as "you're signed in now" and rely on the same
    storage-of-tokens path.
    """
    return await service.magic_login(db, data.token)


@router.post("/auth/refresh", response_model=TokenResponse)
@auth_limiter.limit(settings.auth_rate_limit_refresh)
async def refresh(
    request: Request, data: RefreshRequest, db: AsyncSession = Depends(get_db)
):
    try:
        payload = decode_token(data.refresh_token)
        user_id = payload.get("sub")
        token_type = payload.get("type")
        if not user_id or token_type != "refresh":
            raise AppError("invalid_refresh_token", status.HTTP_401_UNAUTHORIZED)
    except JWTError:
        raise AppError("invalid_refresh_token", status.HTTP_401_UNAUTHORIZED)

    return await service.refresh_tokens(db, uuid.UUID(user_id), payload.get("ver", 0))


@router.get("/auth/me", response_model=UserRead)
async def me(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_me(db, current_user.id)


@router.put("/auth/me", response_model=UserRead)
async def update_me(
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.update_profile(db, current_user.id, data)


@router.post("/auth/avatar", response_model=UserRead)
async def upload_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.upload_avatar(
        db, current_user.id, current_user.tenant_id, file
    )


@router.delete("/auth/avatar", response_model=UserRead)
async def remove_avatar(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.remove_avatar(db, current_user.id, current_user.tenant_id)


@router.post("/auth/change-password", status_code=204)
async def change_password(
    data: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await service.change_password(db, current_user.id, data)


@router.post("/auth/forgot-password")
@auth_limiter.limit(settings.auth_rate_limit_email)
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    issued = await service.request_password_reset(
        db, data.email, accept_language=request.headers.get("accept-language")
    )
    # Always return success to prevent email enumeration
    if issued:
        token, locale = issued
        try:
            from app.core.email import send_password_reset_email

            send_password_reset_email(data.email, token, locale=locale)
        except Exception:  # noqa: BLE001 - must not leak email existence
            logger.warning("Password reset email delivery failed", exc_info=True)
    return {"message": "If this email exists, a reset link has been sent"}


@router.post("/auth/reset-password", status_code=204)
@auth_limiter.limit(settings.auth_rate_limit_email)
async def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    await service.reset_password(db, data.token, data.new_password)


# --- Dev / E2E helpers ---


@router.post(
    "/auth/dev/auto-register", response_model=VerifyEmailResponse, status_code=201
)
async def dev_auto_register(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    system_role: str | None = Query(None),
):
    """Register + auto-verify in one step. Only available when E2E_MODE=true.

    ``system_role`` grants an extra existing system role by code (used by
    enterprise E2E suites to mint platform-level accounts).
    """
    _require_dev_endpoint()
    return await service.dev_auto_register(db, data, system_role=system_role)


@router.get("/auth/dev/invitations/{invitation_id}/token")
async def dev_get_invitation_token(
    invitation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Reveal an invitation's bearer token. E2E-only — production never returns it."""
    from sqlalchemy import select

    from app.modules.auth.models import Invitation

    _require_dev_endpoint()
    inv = (
        await db.execute(select(Invitation).where(Invitation.id == invitation_id))
    ).scalar_one_or_none()
    if inv is None:
        raise AppError("invitation_not_found", 404)
    return {"token": inv.token}


@router.post("/auth/dev/seed-origin-group", status_code=201)
async def dev_seed_origin_group(
    payload: dict = Body(...),  # noqa: B008
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Create an origin (tenant_id IS NULL) competence group for e2e.

    Origin groups are normally produced by AI generation or platform seeds —
    neither is reachable from Playwright. This endpoint short-circuits that
    so HRP-138's "bulk-add button stays hidden on origin groups" path can
    be exercised end-to-end. E2E-only; still requires a logged-in user so
    a misconfigured staging cannot be polluted anonymously."""
    from app.modules.competence.models import CompetenceGroup

    _require_dev_endpoint()
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        # Bare HTTPException on purpose: an AppError catalog key for a
        # dev-only endpoint would fingerprint the hidden surface via the
        # shipped en/de.json (same rationale as the 404 guard above).
        raise HTTPException(status_code=400, detail="title is required")
    group = CompetenceGroup(
        title=title.strip(),
        tenant_id=None,
        is_active=True,
        can_deactivate=False,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return {"id": str(group.id), "title": group.title}


# --- Roles ---


def _role_to_dict(role):
    return {
        "id": role.id,
        "name": role.name,
        "code": role.code,
        "description": role.description,
        "is_system": role.is_system,
        "tenant_id": role.tenant_id,
        "permissions": [p.codename for p in role.permissions],
    }


@router.get("/roles", response_model=list[RoleRead])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    roles = await service.list_roles(db, current_user.tenant_id)
    return [_role_to_dict(r) for r in roles]


@router.post("/roles", response_model=RoleRead, status_code=201)
async def create_role(
    data: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    role = await service.create_role(db, current_user.tenant_id, data)
    return _role_to_dict(role)


@router.put("/roles/{role_id}", response_model=RoleRead)
async def update_role(
    role_id: uuid.UUID,
    data: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    role = await service.update_role(db, current_user.tenant_id, role_id, data)
    return _role_to_dict(role)


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_role(db, current_user.tenant_id, role_id)


# --- Invitations (GF3) ---


@router.post("/invitations", response_model=InvitationRead, status_code=201)
async def create_invitation(
    data: InvitationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hr", "manager")),
):
    inviter_role_codes = [r.code for r in current_user.roles]
    return await service.create_invitation(
        db,
        current_user.tenant_id,
        current_user.id,
        data,
        inviter_role_codes=inviter_role_codes,
    )


@router.post("/invitations/bulk", response_model=list[InvitationRead], status_code=201)
async def bulk_create_invitations(
    data: InvitationBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hr", "manager")),
):
    inviter_role_codes = [r.code for r in current_user.roles]
    results = []
    for inv_data in data.invitations:
        try:
            result = await service.create_invitation(
                db,
                current_user.tenant_id,
                current_user.id,
                inv_data,
                inviter_role_codes=inviter_role_codes,
            )
            results.append(result)
        except Exception:  # noqa: BLE001 - per-item bulk isolation
            continue  # Skip duplicates / errors in bulk
    return results


@router.get("/invitations", response_model=InvitationList)
async def list_invitations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    items, total = await service.list_invitations(
        db, current_user.tenant_id, skip, limit, status
    )
    return {"items": items, "total": total}


@router.patch("/invitations/{invitation_id}", response_model=InvitationRead)
async def update_invitation(
    invitation_id: uuid.UUID,
    data: InvitationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role("admin", "hr", "platform_admin", "manager")
    ),
):
    role_codes = [r.code for r in current_user.roles]
    return await service.update_invitation(
        db,
        current_user.tenant_id,
        invitation_id,
        data,
        role_codes=role_codes,
    )


@router.patch("/invitations/{invitation_id}/email", response_model=InvitationRead)
@invitations_limiter.limit("5/minute")
async def update_invitation_email(
    request: Request,
    invitation_id: uuid.UUID,
    data: InvitationEmailUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "platform_admin")),
):
    return await service.update_invitation_email(
        db, current_user.tenant_id, invitation_id, data, changed_by_id=current_user.id
    )


@router.post("/invitations/{invitation_id}/cancel", response_model=InvitationRead)
async def cancel_invitation(
    invitation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.cancel_invitation(db, current_user.tenant_id, invitation_id)


@router.post("/invitations/{invitation_id}/resend", response_model=InvitationRead)
@invitations_limiter.limit("3/minute")
async def resend_invitation(
    request: Request,
    invitation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.resend_invitation(db, current_user.tenant_id, invitation_id)


@router.post("/auth/accept-invite", response_model=VerifyEmailResponse)
async def accept_invitation(
    data: AcceptInvitationRequest,
    db: AsyncSession = Depends(get_db),
):
    return await service.accept_invitation(db, data)
