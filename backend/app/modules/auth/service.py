import contextlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import rbac_hooks
from app.core.email import (
    send_invitation_email,
    send_invitation_reminder_email,
    send_verification_email,
)
from app.core.s3 import get_presigned_url
from app.core.security import (
    create_access_token,
    create_email_verification_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.modules.auth.models import Invitation, Role, User, user_roles
from app.modules.auth.schemas import (
    AcceptInvitationRequest,
    ChangePasswordRequest,
    InvitationCreate,
    InvitationEmailUpdate,
    InvitationUpdate,
    RegisterRequest,
    RoleCreate,
    RoleUpdate,
    UserUpdate,
)
from app.modules.company.models import Division, Tenant
from app.modules.position.models import Position
from app.modules.storage.models import File


def _slugify(name: str) -> str:
    import re

    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:255]


def _make_tokens(user: User) -> dict[str, str]:
    return {
        "access_token": create_access_token(
            str(user.id), str(user.tenant_id), user.token_version
        ),
        "refresh_token": create_refresh_token(
            str(user.id), str(user.tenant_id), user.token_version
        ),
    }


# Statuses that revoke system access for users with an Employee card.
BLOCKED_EMPLOYEE_STATUSES = ("terminated", "inactive")


async def assert_employee_active(db: AsyncSession, user: User) -> None:
    """Raise 401 if the user has an Employee card with a blocking status.

    Users without an Employee record (e.g. tenant admins, platform admins)
    pass through. The check runs on every authenticated request and on every
    token-issuance path so terminated/inactive accounts cannot obtain or
    refresh credentials.
    """
    from app.modules.employee.models import Employee

    result = await db.execute(
        select(Employee.status).where(Employee.user_id == user.id)
    )
    status_value = result.scalar_one_or_none()
    if status_value in BLOCKED_EMPLOYEE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "employee_status_blocked",
                "status": status_value,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


def _user_to_dict(user: User, avatar_url: str | None = None) -> dict[str, Any]:
    from app.config import settings

    role_codes = [r.code for r in user.roles]
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_active": user.is_active,
        "tenant_id": user.tenant_id,
        "created_at": user.created_at,
        "email_verified_at": user.email_verified_at,
        "roles": role_codes,
        "avatar_url": avatar_url,
        "deployment_mode": settings.deployment_mode,
        # Enterprise adds e.g. ``is_platform_admin`` here; community keeps
        # the UserRead schema defaults (seam is a no-op).
        **rbac_hooks.user_read_extras(role_codes),
    }


async def _resolve_avatar_url(
    db: AsyncSession, avatar_file_id: uuid.UUID | None
) -> str | None:
    if not avatar_file_id:
        return None
    f = await db.get(File, avatar_file_id)
    if not f:
        return None
    return get_presigned_url(f.path)


# --- Auth ---


def _log_verification_link(email: str, token: str) -> None:
    """Self-hosted rescue hatch (HRP-390): when the verification email
    cannot be delivered, print the link to the backend log so the operator
    can finish the signup by hand. Never fires in SaaS — verification JWTs
    must not land in multi-tenant logs."""
    from app.config import settings

    if settings.deployment_mode != "onprem":
        return
    from app.core.email_templates import frontend_url

    logger.warning(
        "\n================= EMAIL VERIFICATION LINK =================\n"
        "Verification email to %s could not be delivered.\n"
        "Open this link to verify the account:\n"
        "%s/verify-email?token=%s\n"
        "===========================================================",
        email,
        frontend_url(),
        token,
    )


def _send_verification_or_log(email: str, user_id: str) -> None:
    """Best-effort verification email with the HRP-390 log fallback.

    Nothing may escape: the caller has already committed the user, and on
    the resend path a raised error would leak email existence through the
    response differential. Token creation stays inside the guard for the
    same reason.
    """
    token: str | None = None
    sent = False
    try:
        token = create_email_verification_token(user_id)
        sent = send_verification_email(email, token)
    except Exception:  # noqa: BLE001 - email failure must not block or leak
        logger.warning("Verification email delivery failed", exc_info=True)
    if not sent and token:
        _log_verification_link(email, token)


async def register(db: AsyncSession, data: RegisterRequest) -> dict[str, Any]:
    # Check email uniqueness (global, since tenant doesn't exist yet)
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    # Create tenant
    slug = _slugify(data.company_name)
    existing_slug = await db.execute(select(Tenant).where(Tenant.slug == slug))
    if existing_slug.scalar_one_or_none():
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    tenant = Tenant(name=data.company_name, slug=slug)
    db.add(tenant)
    await db.flush()

    # HRP-181 REDO: seed the canonical 9-stage recruitment funnel for
    # the new tenant. Soft-import + best-effort because the recruitment
    # module may legitimately be absent in non-recruitment builds (e.g.
    # the talent-market-only deployment shape), and an HR-funnel seed
    # error must not block account creation.
    #
    # Wrap the seed in a SAVEPOINT so an IntegrityError / ProgrammingError
    # inside ``seed_default_recruitment_stages`` (e.g. half-applied alembic
    # chain, race with a concurrent registration) only rolls back the
    # savepoint — the outer transaction stays usable for the User insert
    # below. Without the savepoint, AsyncSession enters PendingRollbackError
    # and the next ``db.flush()`` 500s.
    try:
        from app.modules.recruitment.vacancy_service import (
            seed_default_recruitment_stages,
        )

        async with db.begin_nested():
            await seed_default_recruitment_stages(db, tenant.id)
    except Exception:
        logger.exception(
            "Failed to seed default recruitment stages for tenant %s", tenant.id
        )

    # HRP-390: self-hosted installs without an email provider can never
    # deliver the verification email, and login is blocked until verified —
    # a guaranteed dead end. Verify at creation time instead; SaaS (and any
    # install with a provider) keeps the normal email verification flow.
    from app.config import settings
    from app.core.email import email_provider_configured

    auto_verify = (
        settings.deployment_mode == "onprem" and not email_provider_configured()
    )

    # Create user
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc) if auto_verify else None,
    )
    db.add(user)
    await db.flush()

    # Assign admin role via direct insert to avoid lazy loading
    admin_role = await db.execute(
        select(Role).where(Role.code == "admin", Role.is_system == True)  # noqa: E712
    )
    role = admin_role.scalar_one_or_none()
    if role:
        await db.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))

    await db.commit()

    if auto_verify:
        logger.info(
            "No email provider configured — auto-verified %s at registration "
            "(self-hosted self-serve signup, HRP-390)",
            data.email,
        )
    else:
        _send_verification_or_log(data.email, str(user.id))

    # Best-effort domain event — subscribers (e.g. the enterprise Slack
    # notifier) fan it out. Fires on account creation, before email
    # verification; a handler failure must never block registration.
    try:
        from app.core.events import publish

        await publish(
            "auth.registered",
            {
                "email": data.email,
                "company_name": data.company_name,
                "first_name": data.first_name,
                "last_name": data.last_name,
            },
        )
    except Exception:
        logger.exception("Failed to publish auth.registered event")

    return {
        "pending_verification": not auto_verify,
        "email": data.email,
        "auto_verified": auto_verify,
    }


async def dev_auto_register(
    db: AsyncSession, data: RegisterRequest, *, system_role: str | None = None
) -> dict[str, Any]:
    """Register + auto-verify in one step. For E2E tests only.

    ``system_role`` optionally grants an existing system role by code on top
    of the default admin role (e.g. the enterprise platform-admin role in
    ``DEPLOYMENT_MODE=saas`` E2E runs). The endpoint is E2E_MODE-gated.
    """
    # Reuse normal register logic (creates tenant, user, role)
    await register(db, data)

    # Auto-verify the user
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.email == data.email)
    )
    user = result.scalar_one()
    user.email_verified_at = datetime.now(timezone.utc)

    # Optionally grant an extra system role
    if system_role:
        extra_role = await db.execute(
            select(Role).where(
                Role.code == system_role, Role.is_system == True  # noqa: E712
            )
        )
        role = extra_role.scalar_one_or_none()
        if not role:
            raise ValueError(f"system role {system_role!r} not found in database")
        await db.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))

    await db.commit()
    await db.refresh(user)

    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user.id)
    )
    user = result.scalar_one()

    tokens = _make_tokens(user)
    return {"user": _user_to_dict(user), **tokens, "token_type": "bearer"}


async def verify_email(db: AsyncSession, token: str) -> dict[str, Any]:
    """Verify email using JWT token. Returns auth tokens on success."""
    from jwt import PyJWTError as JWTError

    from app.core.security import decode_token

    try:
        payload = decode_token(token)
        if payload.get("type") != "email_verify":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Invalid verification token"
            )
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid or expired verification token"
        )

    result = await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid verification token")

    if user.email_verified_at:
        # Already verified — just return tokens
        tokens = _make_tokens(user)
        return {"user": _user_to_dict(user), **tokens, "token_type": "bearer"}

    user.email_verified_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user.id)
    )
    user = result.scalar_one()

    tokens = _make_tokens(user)
    return {"user": _user_to_dict(user), **tokens, "token_type": "bearer"}


async def resend_verification(db: AsyncSession, email: str) -> None:
    """Resend verification email. Always returns success to prevent email enumeration."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user and not user.email_verified_at:
        _send_verification_or_log(email, str(user.id))


async def magic_login(db: AsyncSession, token: str) -> dict[str, Any]:
    """Consume a one-time magic-login token (HRP-262 — M4).

    Token shape (see ``app.core.security.create_magic_login_token``):
      ``sub`` = ``User.id``, ``tenant_id`` = approved tenant id,
      ``type`` = ``magic_login``, ``jti`` = random uuid.

    Replay guard: ``SETNX magic-login:used:<jti> ex=86400`` so a
    stolen link cannot be re-used and a double-click in a slow webmail
    client doesn't accidentally invalidate the visitor's session.
    Redis failure here fails *open* — better to let a fresh approve
    sign in than to lock out every newly approved company.
    """
    from jwt import PyJWTError as JWTError

    from app.core.security import decode_token

    try:
        payload = decode_token(token)
    except JWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Magic-login link is invalid or expired."
        ) from exc
    if payload.get("type") != "magic_login":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Magic-login link is invalid."
        )
    jti = payload.get("jti")
    user_id_raw = payload.get("sub")
    if not jti or not user_id_raw:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Magic-login link is invalid."
        )

    try:
        user_id = uuid.UUID(str(user_id_raw))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Magic-login link is invalid."
        ) from exc

    # Load + validate the user BEFORE burning the JTI. A transient DB
    # error or an account-status guard tripping must not strand the
    # link as "already used" — the visitor would then have no recovery
    # path other than asking a moderator to re-approve.
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not available.")

    # Verify the JWT's tenant_id claim matches the user's current
    # tenant. If a moderator re-tenants the user between approve and
    # click, the token must NOT silently issue access to whichever
    # tenant the user happens to be on now.
    token_tenant_id = payload.get("tenant_id")
    if token_tenant_id and str(user.tenant_id) != str(token_tenant_id):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Magic-login link is invalid."
        )

    await assert_employee_active(db, user)

    # Replay guard now — at this point any failure means the JWT was
    # genuinely valid and the user was reachable, so burning the JTI
    # is the correct decision.
    await _consume_magic_jti(jti)

    await _stamp_first_login(db, user)

    tokens = _make_tokens(user)
    return {"user": _user_to_dict(user), **tokens, "token_type": "bearer"}


async def _consume_magic_jti(jti: str) -> None:
    """One-time JTI guard backed by Redis ``SET NX EX``.

    Falls *open* on Redis errors: a transient flake here would otherwise
    lock out every newly approved account, and the JWT itself is still
    expiry-bounded (`settings.magic_login_token_ttl_hours`). The replay
    window is the JTI TTL — pinned to the JWT TTL so a deploy that
    later raises the JWT lifetime can't open a replay window beyond it.
    """
    import contextlib as _contextlib

    import redis.asyncio as aioredis

    from app.config import settings

    ttl_seconds = max(1, settings.magic_login_token_ttl_hours * 3600)
    client = None
    try:
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        ok = await client.set(
            f"magic-login:used:{jti}",
            "1",
            nx=True,
            ex=ttl_seconds,
        )
        if not ok:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "This sign-in link has already been used.",
            )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        # Fail CLOSED (review P3-46): the replay guard is the only thing
        # stopping a captured one-time link from minting multiple sessions,
        # so a Redis outage must block sign-in, not wave it through. Redis
        # outages are rare and transient; the user can retry or use password
        # login. Previously this fell open.
        logger.exception("magic-login: redis unavailable, refusing jti=%s", jti)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Sign-in is temporarily unavailable. Please try again shortly.",
        ) from None
    finally:
        if client is not None:
            with _contextlib.suppress(Exception):
                await client.aclose()  # type: ignore[attr-defined]


async def _get_tenant_info(db: AsyncSession, user: User) -> dict[str, Any]:
    """Build tenant info dict for a user (includes tenant name/slug and user roles)."""
    tenant = await db.get(Tenant, user.tenant_id)
    return {
        "id": user.tenant_id,
        "name": tenant.name if tenant else "Unknown",
        "slug": tenant.slug if tenant else "",
        "roles": [r.code for r in user.roles],
    }


async def _stamp_first_login(db: AsyncSession, user: User) -> None:
    """HRP-246: stamp ``users.first_login_at`` on the first successful login.

    Called from every successful login path (single-tenant `login`,
    multi-tenant `select_tenant`, and the impersonation entry point
    below). Idempotent — once set, the timestamp never moves.
    """
    if user.first_login_at is not None:
        return
    user.first_login_at = datetime.now(timezone.utc)
    await db.commit()


async def login(db: AsyncSession, email: str, password: str) -> dict[str, Any]:
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.email == email)
    )
    users = list(result.scalars().all())
    if not users:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    # Verify password against all user records with this email
    valid_users = [u for u in users if verify_password(password, u.password_hash)]
    if not valid_users:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    # Filter to active, verified users
    active_users = [u for u in valid_users if u.is_active and u.email_verified_at]

    # If all valid users are inactive/unverified, give appropriate error
    if not active_users:
        # Check if any are just unverified
        unverified = [u for u in valid_users if u.is_active and not u.email_verified_at]
        if unverified:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Email not verified. Check your inbox or request a new verification email.",
            )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")

    # Single tenant — return tokens directly (preserves existing behavior)
    if len(active_users) == 1:
        user = active_users[0]
        await assert_employee_active(db, user)
        await _stamp_first_login(db, user)
        tokens = _make_tokens(user)
        role_codes = [r.code for r in user.roles]
        response: dict[str, Any] = {**tokens, "token_type": "bearer"}
        # Enterprise adds the post-login redirect for platform-level roles.
        response.update(rbac_hooks.login_response_extras(role_codes))
        return response

    # Multiple tenants — require tenant selection
    tenants = []
    for u in active_users:
        tenants.append(await _get_tenant_info(db, u))

    return {
        "requires_tenant_selection": True,
        "tenants": tenants,
    }


async def select_tenant(
    db: AsyncSession, email: str, password: str, tenant_id: uuid.UUID
) -> dict[str, str]:
    """Complete login for a specific tenant after tenant selection."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.email == email, User.tenant_id == tenant_id)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")
    if not user.email_verified_at:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Email not verified")
    await assert_employee_active(db, user)
    await _stamp_first_login(db, user)

    tokens = _make_tokens(user)
    role_codes = [r.code for r in user.roles]
    result_dict: dict[str, Any] = {**tokens, "token_type": "bearer"}
    # Enterprise adds the post-login redirect for platform-level roles.
    result_dict.update(rbac_hooks.login_response_extras(role_codes))
    return result_dict


async def switch_tenant(
    db: AsyncSession,
    current_user_id: uuid.UUID,
    current_email: str,
    target_tenant_id: uuid.UUID,
) -> dict[str, str]:
    """Switch to a different tenant without re-entering password."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.email == current_email, User.tenant_id == target_tenant_id)
    )
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No account in target tenant")
    if not target_user.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Account is deactivated in target tenant"
        )
    await assert_employee_active(db, target_user)
    await _stamp_first_login(db, target_user)

    tokens = _make_tokens(target_user)
    return {**tokens, "token_type": "bearer"}


async def list_user_tenants(db: AsyncSession, email: str) -> list[dict[str, Any]]:
    """List all tenants where a user with this email has an active, verified account."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.email == email, User.is_active == True)  # noqa: E712
    )
    users = list(result.scalars().all())
    tenants = []
    for u in users:
        if u.email_verified_at:
            tenants.append(await _get_tenant_info(db, u))
    return tenants


async def refresh_tokens(
    db: AsyncSession, user_id: uuid.UUID, token_version: int = 0
) -> dict[str, str]:
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    # Reject a refresh token from before the user's current epoch — i.e. one
    # minted before a password change/reset (review P1-12).
    if token_version != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    await assert_employee_active(db, user)

    tokens = _make_tokens(user)
    return {**tokens, "token_type": "bearer"}


async def get_me(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    avatar_url = await _resolve_avatar_url(db, user.avatar_file_id)
    payload = _user_to_dict(user, avatar_url)

    # Demo-session metadata so the SPA can render <DemoBanner/> without
    # a second /tenant lookup. Cheap: tenant id is on the user already.
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is not None:
        payload["tenant_is_demo"] = bool(getattr(tenant, "is_demo", False))
        payload["tenant_expires_at"] = getattr(tenant, "expires_at", None)
    return payload


async def update_profile(
    db: AsyncSession, user_id: uuid.UUID, data: UserUpdate
) -> dict[str, Any]:
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    # Explicit allowlist — never iterate model_dump() onto the User row.
    # Privileged fields (status, role_code, is_active, email, tenant_id, id)
    # cannot be reached from this endpoint: schema rejects them via extra='forbid'
    # and only the names below are written here.
    payload = data.model_dump(exclude_unset=True)
    if "first_name" in payload:
        user.first_name = payload["first_name"]
    if "last_name" in payload:
        user.last_name = payload["last_name"]
    await db.commit()
    await db.refresh(user)

    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user.id)
    )
    user = result.scalar_one()
    avatar_url = await _resolve_avatar_url(db, user.avatar_file_id)
    return _user_to_dict(user, avatar_url)


async def upload_avatar(
    db: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID, file: Any
) -> dict[str, Any]:
    """Upload user avatar via storage service, update user record."""
    from app.modules.storage import service as storage_service

    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    # Delete old avatar if exists
    if user.avatar_file_id:
        with contextlib.suppress(HTTPException):
            await storage_service.delete(db, tenant_id, user.avatar_file_id)

    # Upload new avatar
    file_data = await storage_service.upload(
        db, tenant_id, user_id, file, entity_type="avatar", entity_id=user_id
    )

    # Update user record
    user.avatar_file_id = file_data["id"]
    await db.commit()
    await db.refresh(user)

    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user.id)
    )
    user = result.scalar_one()
    return _user_to_dict(user, file_data.get("url"))


async def remove_avatar(
    db: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> dict[str, Any]:
    """Remove user avatar."""
    from app.modules.storage import service as storage_service

    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if not user.avatar_file_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No avatar to remove")

    with contextlib.suppress(HTTPException):
        await storage_service.delete(db, tenant_id, user.avatar_file_id)

    user.avatar_file_id = None
    await db.commit()
    await db.refresh(user)

    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user.id)
    )
    return _user_to_dict(result.scalar_one())


async def change_password(
    db: AsyncSession, user_id: uuid.UUID, data: ChangePasswordRequest
) -> None:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Current password is incorrect"
        )

    user.password_hash = hash_password(data.new_password)
    # Revoke every previously-issued access/refresh token (review P1-12).
    user.token_version += 1
    await db.commit()


async def request_password_reset(db: AsyncSession, email: str) -> str | None:
    """Generate a password reset token. Returns token or None if email not found."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        return None  # Don't reveal if email exists

    # Use a short-lived JWT as reset token (15 min)
    from app.core.security import create_reset_token

    return create_reset_token(str(user.id))


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    from jwt import PyJWTError as JWTError

    from app.core.security import decode_token

    try:
        payload = decode_token(token)
        if payload.get("type") != "reset":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid reset token")
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid or expired reset token"
        )

    user = await db.get(User, uuid.UUID(user_id))
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid reset token")

    user.password_hash = hash_password(new_password)
    # Revoke every previously-issued access/refresh token (review P1-12).
    user.token_version += 1
    await db.commit()


# --- Roles ---


async def list_roles(db: AsyncSession, tenant_id: uuid.UUID) -> list[Role]:
    result = await db.execute(
        select(Role)
        .options(selectinload(Role.permissions))
        .where(or_(Role.tenant_id == tenant_id, Role.is_system == True))  # noqa: E712
    )
    return list(result.scalars().all())


async def create_role(db: AsyncSession, tenant_id: uuid.UUID, data: RoleCreate) -> Role:
    existing = await db.execute(select(Role).where(Role.code == data.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Role code already exists")

    role = Role(tenant_id=tenant_id, **data.model_dump())
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return role


async def update_role(
    db: AsyncSession, tenant_id: uuid.UUID, role_id: uuid.UUID, data: RoleUpdate
) -> Role:
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    if role.is_system:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot modify system roles")
    if role.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(role, field, value)
    await db.commit()
    await db.refresh(role)
    return role


async def delete_role(
    db: AsyncSession, tenant_id: uuid.UUID, role_id: uuid.UUID
) -> None:
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    if role.is_system:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot delete system roles")
    if role.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")

    await db.delete(role)
    await db.commit()


# --- Invitations (GF3) ---


INVITATION_EXPIRE_DAYS = 7


# Per-tier inviter permissions. Managers can only invite employees;
# admin/hr can invite their own tier or below. Enterprise merges extra
# tiers (e.g. the platform-admin tier) via the rbac_hooks seam.
_INVITE_ALLOWED: dict[str, frozenset[str]] = {
    "admin": frozenset({"admin", "hr", "manager", "employee"}),
    "hr": frozenset({"admin", "hr", "manager", "employee"}),
    "manager": frozenset({"employee"}),
}


def _allowed_invite_roles(inviter_role_codes: list[str]) -> frozenset[str]:
    tiers = {**_INVITE_ALLOWED, **rbac_hooks.extra_invite_tiers()}
    allowed: set[str] = set()
    for code in inviter_role_codes:
        allowed |= tiers.get(code, frozenset())
    return frozenset(allowed)


def _assert_role_within_inviter(
    inviter_role_codes: list[str], requested_role_code: str
) -> None:
    if requested_role_code not in _allowed_invite_roles(inviter_role_codes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "role_above_inviter"},
        )


async def _validate_invitation_scope(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    division_id: uuid.UUID | None,
    position_id: uuid.UUID | None,
) -> None:
    if division_id is not None:
        division = await db.get(Division, division_id)
        if division is None or division.tenant_id != tenant_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Division not found")
    if position_id is not None:
        position = await db.get(Position, position_id)
        if position is None or position.tenant_id != tenant_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Position not found")


async def _load_invitation(db: AsyncSession, invitation_id: uuid.UUID) -> Invitation:
    result = await db.execute(
        select(Invitation)
        .options(
            selectinload(Invitation.inviter),
            selectinload(Invitation.position),
            selectinload(Invitation.division),
        )
        .where(Invitation.id == invitation_id)
    )
    return result.scalar_one()


def _invitation_to_read(inv: Invitation) -> dict[str, Any]:
    return {
        "id": inv.id,
        "email": inv.email,
        "name": inv.name,
        "role_code": inv.role_code,
        "invited_by": inv.invited_by,
        "inviter_name": (
            f"{inv.inviter.first_name} {inv.inviter.last_name}" if inv.inviter else None
        ),
        "division_id": inv.division_id,
        "division_name": inv.division.name if inv.division else None,
        "position_id": inv.position_id,
        "position_title": inv.position.title if inv.position else None,
        "status": inv.status,
        "expires_at": inv.expires_at,
        "accepted_at": inv.accepted_at,
        "created_at": inv.created_at,
    }


async def create_invitation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    inviter_id: uuid.UUID,
    data: InvitationCreate,
    *,
    inviter_role_codes: list[str] | None = None,
) -> dict[str, Any]:
    if inviter_role_codes is None:
        inviter = await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == inviter_id)
        )
        inviter_user = inviter.scalar_one_or_none()
        inviter_role_codes = (
            [r.code for r in inviter_user.roles] if inviter_user else []
        )

    # Validate role_code exists first — unknown roles surface as 400, while
    # known-but-disallowed surface as 403 role_above_inviter.
    role = await db.execute(
        select(Role).where(
            Role.code == data.role_code,
            or_(Role.tenant_id == tenant_id, Role.is_system == True),  # noqa: E712
        )
    )
    if not role.scalar_one_or_none():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Role '{data.role_code}' not found"
        )

    _assert_role_within_inviter(inviter_role_codes, data.role_code)

    # HRP-195: manager invitations must carry a division — the accept flow
    # installs the new user as that division's manager; without it the
    # invitation is meaningless (UI already blocks; this guard closes the
    # direct API path).
    if data.role_code == "manager" and data.division_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Manager invitations require a division",
        )

    # Check that email is not already a user in this tenant
    existing_user = await db.execute(
        select(User).where(User.email == data.email, User.tenant_id == tenant_id)
    )
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "User with this email already exists"
        )

    # Check no pending invitation for same email in this tenant
    existing_inv = await db.execute(
        select(Invitation).where(
            Invitation.email == data.email,
            Invitation.tenant_id == tenant_id,
            Invitation.status == "pending",
        )
    )
    if existing_inv.scalar_one_or_none():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Pending invitation already exists for this email"
        )

    await _validate_invitation_scope(db, tenant_id, data.division_id, data.position_id)

    token = secrets.token_urlsafe(32)
    inv = Invitation(
        email=data.email,
        name=data.name,
        token=token,
        role_code=data.role_code,
        invited_by=inviter_id,
        division_id=data.division_id,
        position_id=data.position_id,
        tenant_id=tenant_id,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITATION_EXPIRE_DAYS),
    )
    db.add(inv)
    await db.commit()

    # Reload with relationships so the response carries division/position/inviter
    inv = await _load_invitation(db, inv.id)

    # Send invitation email (best-effort, don't fail the request).
    # HRP-301: demo tenants are allowed to dispatch invitations so a
    # prospective HR admin can walk through the full onboarding loop
    # during their evaluation. Bounded by the demo session TTL and the
    # concurrent-session cap; not a free email blast surface.
    with contextlib.suppress(Exception):
        send_invitation_email(
            data.email,
            data.name,
            token,
            INVITATION_EXPIRE_DAYS,
            tenant_id=tenant_id,
        )

    return _invitation_to_read(inv)


async def list_invitations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    status_filter: str | None = None,
) -> tuple[list[dict], int]:
    query = (
        select(Invitation)
        .options(
            selectinload(Invitation.inviter),
            selectinload(Invitation.position),
            selectinload(Invitation.division),
        )
        .where(Invitation.tenant_id == tenant_id)
    )
    count_query = select(func.count(Invitation.id)).where(
        Invitation.tenant_id == tenant_id
    )

    if status_filter:
        query = query.where(Invitation.status == status_filter)
        count_query = count_query.where(Invitation.status == status_filter)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(Invitation.created_at.desc()).offset(skip).limit(limit)
    )
    return [_invitation_to_read(i) for i in result.scalars().all()], total


async def cancel_invitation(
    db: AsyncSession, tenant_id: uuid.UUID, invitation_id: uuid.UUID
) -> dict[str, Any]:
    inv = await db.get(Invitation, invitation_id)
    if not inv or inv.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    if inv.status != "pending":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only pending invitations can be cancelled"
        )

    inv.status = "cancelled"
    await db.commit()
    inv = await _load_invitation(db, inv.id)
    return _invitation_to_read(inv)


async def resend_invitation(
    db: AsyncSession, tenant_id: uuid.UUID, invitation_id: uuid.UUID
) -> dict[str, Any]:
    inv = await db.get(Invitation, invitation_id)
    if not inv or inv.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    if inv.status != "pending":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only pending invitations can be resent"
        )

    # Extend expiry
    inv.expires_at = datetime.now(timezone.utc) + timedelta(days=INVITATION_EXPIRE_DAYS)
    await db.commit()
    inv = await _load_invitation(db, inv.id)

    # HRP-301: see create_invitation — demo tenants ship invitations.
    with contextlib.suppress(Exception):
        send_invitation_reminder_email(
            inv.email,
            inv.name,
            inv.token,
            INVITATION_EXPIRE_DAYS,
            tenant_id=tenant_id,
        )

    return _invitation_to_read(inv)


async def update_invitation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invitation_id: uuid.UUID,
    data: InvitationUpdate,
    *,
    role_codes: list[str],
) -> dict[str, Any]:
    inv = await db.get(Invitation, invitation_id)
    if not inv or inv.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    if inv.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only pending invitations can be edited"
        )

    payload = data.model_dump(exclude_unset=True)

    is_admin = bool(set(role_codes) & rbac_hooks.admin_equivalent_codes())
    if "role_code" in payload and not is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only admins can change invitation role"
        )

    if "role_code" in payload:
        new_role_code = payload["role_code"]
        role = await db.execute(
            select(Role).where(
                Role.code == new_role_code,
                or_(Role.tenant_id == tenant_id, Role.is_system == True),  # noqa: E712
            )
        )
        if not role.scalar_one_or_none():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Role '{new_role_code}' not found"
            )
        _assert_role_within_inviter(role_codes, new_role_code)
        inv.role_code = new_role_code

    if "division_id" in payload or "position_id" in payload:
        await _validate_invitation_scope(
            db,
            tenant_id,
            payload.get("division_id") if "division_id" in payload else None,
            payload.get("position_id") if "position_id" in payload else None,
        )

    if "division_id" in payload:
        inv.division_id = payload["division_id"]
    if "position_id" in payload:
        inv.position_id = payload["position_id"]

    await db.commit()
    inv = await _load_invitation(db, inv.id)
    return _invitation_to_read(inv)


async def update_invitation_email(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invitation_id: uuid.UUID,
    data: InvitationEmailUpdate,
    *,
    changed_by_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    inv = await db.get(Invitation, invitation_id)
    if not inv or inv.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    if inv.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only pending invitations can be edited"
        )

    new_email = data.email
    old_email = inv.email
    if new_email != inv.email:
        existing_user = await db.execute(
            select(User).where(User.email == new_email, User.tenant_id == tenant_id)
        )
        if existing_user.scalar_one_or_none():
            raise HTTPException(
                status.HTTP_409_CONFLICT, "User with this email already exists"
            )

        existing_inv = await db.execute(
            select(Invitation).where(
                Invitation.email == new_email,
                Invitation.tenant_id == tenant_id,
                Invitation.status == "pending",
                Invitation.id != invitation_id,
            )
        )
        if existing_inv.scalar_one_or_none():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Pending invitation already exists for this email",
            )

    inv.email = new_email
    inv.token = secrets.token_urlsafe(32)
    inv.expires_at = datetime.now(timezone.utc) + timedelta(days=INVITATION_EXPIRE_DAYS)
    await db.commit()
    inv = await _load_invitation(db, inv.id)

    if old_email != new_email:
        logger.info(
            "invitation.email_changed",
            extra={
                "event": "invitation.email_changed",
                "invitation_id": str(invitation_id),
                "tenant_id": str(tenant_id),
                "old_email": old_email,
                "new_email": new_email,
                "invited_by": str(inv.invited_by),
                "changed_by": str(changed_by_id) if changed_by_id else None,
            },
        )

    # HRP-301: see create_invitation — demo tenants ship invitations.
    with contextlib.suppress(Exception):
        send_invitation_email(
            inv.email,
            inv.name,
            inv.token,
            INVITATION_EXPIRE_DAYS,
            tenant_id=tenant_id,
        )

    return _invitation_to_read(inv)


async def accept_invitation(
    db: AsyncSession, data: AcceptInvitationRequest
) -> dict[str, Any]:
    # Find invitation by token
    result = await db.execute(select(Invitation).where(Invitation.token == data.token))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    if inv.status != "pending":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invitation is no longer valid"
        )
    if inv.expires_at < datetime.now(timezone.utc):
        inv.status = "expired"
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invitation has expired")

    # Check email not already taken in this tenant
    existing = await db.execute(
        select(User).where(User.email == inv.email, User.tenant_id == inv.tenant_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "User with this email already exists"
        )

    # Create user (invitation proves email ownership)
    user = User(
        email=inv.email,
        password_hash=hash_password(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
        tenant_id=inv.tenant_id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()

    # Assign role
    role_result = await db.execute(
        select(Role).where(
            Role.code == inv.role_code,
            or_(Role.tenant_id == inv.tenant_id, Role.is_system == True),  # noqa: E712
        )
    )
    role = role_result.scalar_one_or_none()
    if role:
        await db.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))

    # Create employee card if division or position specified
    emp = None
    if inv.division_id or inv.position_id:
        from app.modules.employee.models import Employee

        position_title = inv.position.title if inv.position else "Employee"
        emp = Employee(
            user_id=user.id,
            tenant_id=inv.tenant_id,
            division_id=inv.division_id,
            position_id=inv.position_id,
            position_title=position_title,
            hire_date=datetime.now(timezone.utc).date(),
        )
        db.add(emp)
        await db.flush()

    # HRP-195: when invited as Manager with a division pre-selected, make
    # the new user the actual Manager of that division. The previous
    # manager (if any) is auto-downgraded via the same path used by the
    # division-edit flow so the role/division graph stays consistent.
    if inv.role_code == "manager" and inv.division_id and emp is not None:
        from app.modules.company.service import (
            _auto_downgrade_to_employee,
            _compute_pending_downgrades,
        )

        division = await db.get(Division, inv.division_id)
        if division and division.tenant_id == inv.tenant_id:
            previous_manager_id = division.manager_id
            division.manager_id = emp.id
            await db.flush()
            if previous_manager_id and previous_manager_id != emp.id:
                entries = await _compute_pending_downgrades(
                    db, inv.tenant_id, [previous_manager_id]
                )
                await _auto_downgrade_to_employee(db, inv.tenant_id, entries)

    # Mark invitation as accepted
    inv.status = "accepted"
    inv.accepted_at = datetime.now(timezone.utc)
    await db.commit()

    # Reload user with roles
    user_result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user.id)
    )
    user = user_result.scalar_one()

    tokens = _make_tokens(user)
    return {
        "user": _user_to_dict(user),
        **tokens,
        "token_type": "bearer",
    }
