"""P1-12: password change/reset revokes previously-issued tokens.

Access/refresh JWTs carry a ``ver`` claim matched against
``User.token_version``; bumping the column invalidates every earlier token.
"""

from __future__ import annotations

import uuid

import pytest
from app.core.security import (
    create_access_token,
    create_reset_token,
)
from app.modules.auth import service
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import ChangePasswordRequest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


async def _access_for(user) -> str:
    return create_access_token(str(user.id), str(user.tenant_id), user.token_version)


class TestChangePasswordRevokesTokens:
    async def test_old_access_token_rejected_after_change(
        self, db: AsyncSession, user
    ):
        token = await _access_for(user)
        # Sanity: the access token validates before the password change.
        assert (await get_current_user(token=token, db=db)).id == user.id

        await service.change_password(
            db,
            user.id,
            ChangePasswordRequest(
                current_password="testpass123", new_password="newpass456"
            ),
        )

        with pytest.raises(HTTPException) as exc:
            await get_current_user(token=token, db=db)
        assert exc.value.status_code == 401

    async def test_old_refresh_token_rejected_after_change(
        self, db: AsyncSession, user
    ):
        # A refresh token minted at the current epoch (version captured here).
        old_version = user.token_version
        await service.change_password(
            db,
            user.id,
            ChangePasswordRequest(
                current_password="testpass123", new_password="newpass456"
            ),
        )
        with pytest.raises(HTTPException) as exc:
            await service.refresh_tokens(db, user.id, token_version=old_version)
        assert exc.value.status_code == 401
        # A token minted at the new epoch still works.
        await db.refresh(user)
        fresh = await service.refresh_tokens(
            db, user.id, token_version=user.token_version
        )
        assert fresh["token_type"] == "bearer"

    async def test_reset_password_bumps_version(self, db: AsyncSession, user):
        before = user.token_version
        token = create_reset_token(str(user.id))
        await service.reset_password(db, token, "brandnew789")
        await db.refresh(user)
        assert user.token_version == before + 1

    async def test_new_token_after_change_still_valid(
        self, db: AsyncSession, user
    ):
        await service.change_password(
            db,
            user.id,
            ChangePasswordRequest(
                current_password="testpass123", new_password="newpass456"
            ),
        )
        await db.refresh(user)
        token = await _access_for(user)
        assert (await get_current_user(token=token, db=db)).id == user.id

    async def test_legacy_token_without_ver_claim_still_valid(
        self, db: AsyncSession, user
    ):
        # A token predating this change carries no ``ver`` claim; get_current_user
        # treats the absent claim as 0, matching the default token_version, so
        # deploying the feature does not force-log-out existing sessions.
        from datetime import datetime, timedelta, timezone

        import jwt
        from app.config import settings

        payload = {
            "sub": str(user.id),
            "tenant_id": str(user.tenant_id),
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        }
        legacy = jwt.encode(
            payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
        assert (await get_current_user(token=legacy, db=db)).id == user.id

    async def test_unknown_user_still_401(self, db: AsyncSession):
        with pytest.raises(HTTPException):
            await service.refresh_tokens(db, uuid.uuid4(), token_version=0)
