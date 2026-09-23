import uuid
from collections.abc import Callable

from fastapi import Depends, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWTError as JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import rbac_hooks
from app.core.errors import AppError
from app.core.security import decode_token
from app.database import get_db
from app.modules.auth.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def resolve_user_from_access_token(db: AsyncSession, token: str) -> User | None:
    """The full access-token check, shared by every authenticated surface.

    Returns ``None`` when the token is not a usable access token for a live
    account: bad signature/shape, wrong ``type``, unknown or deactivated
    user, or a ``ver`` claim minted before the user's current epoch (bumped
    on password change/reset — review P1-12; absent claim → 0, matching
    tokens predating that change). A blocking Employee status still raises,
    because callers surface its specific reason.

    The WebSocket handshake authenticates off the same helper, so a surface
    added here cannot silently skip revocation (review B7).
    """
    try:
        payload = decode_token(token)
    except JWTError:
        return None
    user_id = payload.get("sub")
    if user_id is None or payload.get("type") != "access":
        return None
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None

    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == uid)
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if payload.get("ver", 0) != user.token_version:
        return None

    from app.modules.auth.service import assert_employee_active

    await assert_employee_active(db, user)
    return user


async def get_current_user(
    # Deliberately the raw Request rather than a ``Header(...)`` param
    # for X-Tab-Hidden: a declared header on a dependency this widely
    # shared documents itself on all ~550 authenticated endpoints in the
    # public OpenAPI, and this is a frontend-internal hint, not API
    # surface. Request is invisible to the schema.
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await resolve_user_from_access_token(db, token)
    if user is None:
        raise AppError(
            "could_not_validate_credentials",
            status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # HRP-249 (D1): keep demo-tenant inactivity TTL fresh on every
    # authenticated request. Best-effort, debounced via Redis — non-demo
    # tenants pay one cheap GET and a no-op SQL UPDATE at most.
    # X-Tab-Hidden is the frontend saying "this one is a background poll,
    # nobody is looking" — see ``touch_demo_tenant_activity``.
    from app.modules.demo.activity import touch_demo_tenant_activity

    await touch_demo_tenant_activity(
        db,
        user.tenant_id,
        background=request.headers.get("x-tab-hidden") == "1",
    )
    return user


def require_role(*role_codes: str) -> Callable:
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_roles = {r.code for r in current_user.roles}
        if not user_roles.intersection(role_codes):
            raise AppError("auth_insufficient_permissions", status.HTTP_403_FORBIDDEN)
        return current_user

    return role_checker


def require_admin() -> Callable:
    """Guard for tenant-admin-only endpoints (HRP-436).

    Resolves the allowed codes through ``rbac_hooks`` at request time, so the
    enterprise edition can widen "admin" to its platform-level role without
    core naming it.

    Currently used by the invitation registry only. The other admin surfaces
    (dictionaries, AI settings, data import, grade system) still spell
    ``require_role("admin")`` literally, so in the enterprise edition a
    platform-level role reaches invitations but not those — converting them is
    a separate change, not something this dependency has already done.
    """

    async def admin_checker(current_user: User = Depends(get_current_user)) -> User:
        user_roles = {r.code for r in current_user.roles}
        if not user_roles.intersection(rbac_hooks.admin_equivalent_codes()):
            raise AppError("auth_insufficient_permissions", status.HTTP_403_FORBIDDEN)
        return current_user

    return admin_checker


def require_permission(*codenames: str) -> Callable:
    async def permission_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        user_permissions: set[str] = set()
        for role in current_user.roles:
            for perm in role.permissions:
                user_permissions.add(perm.codename)
        if not user_permissions.intersection(codenames):
            raise AppError("auth_insufficient_permissions", status.HTTP_403_FORBIDDEN)
        return current_user

    return permission_checker
