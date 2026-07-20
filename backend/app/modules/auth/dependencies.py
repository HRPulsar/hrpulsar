import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWTError as JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import decode_token
from app.database import get_db
from app.modules.auth.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        token_type = payload.get("type")
        if user_id is None or token_type != "access":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    # Reject tokens minted before the user's current epoch — bumped on
    # password change/reset (review P1-12). Absent claim → 0, matching the
    # default for users/tokens predating this change.
    if payload.get("ver", 0) != user.token_version:
        raise credentials_exception
    from app.modules.auth.service import assert_employee_active

    await assert_employee_active(db, user)

    # HRP-249 (D1): keep demo-tenant inactivity TTL fresh on every
    # authenticated request. Best-effort, debounced via Redis — non-demo
    # tenants pay one cheap GET and a no-op SQL UPDATE at most.
    from app.modules.demo.activity import touch_demo_tenant_activity

    await touch_demo_tenant_activity(db, user.tenant_id)
    return user


def require_role(*role_codes: str) -> Callable:
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_roles = {r.code for r in current_user.roles}
        if not user_roles.intersection(role_codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return role_checker


def require_permission(*codenames: str) -> Callable:
    async def permission_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        user_permissions: set[str] = set()
        for role in current_user.roles:
            for perm in role.permissions:
                user_permissions.add(perm.codename)
        if not user_permissions.intersection(codenames):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return permission_checker
