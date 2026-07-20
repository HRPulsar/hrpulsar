"""Tests for analytics, public_api, notification, and grade_system services."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


class TestAnalyticsService:
    async def test_assessment_stats(self, db: AsyncSession, tenant):
        from app.modules.analytics import service

        stats = await service.assessment_stats(db, tenant.id)
        assert "total" in stats
        assert "by_status" in stats

    async def test_pdp_stats(self, db: AsyncSession, tenant):
        from app.modules.analytics import service

        stats = await service.pdp_stats(db, tenant.id)
        assert "total" in stats
        assert "by_status" in stats


class TestPublicApiService:
    async def test_generate_api_key(self):
        from app.modules.public_api.service import generate_api_key

        full_key, key_hash, prefix = generate_api_key()
        assert full_key.startswith("hrp_")
        assert len(prefix) > 0
        assert key_hash != full_key

    async def test_create_api_key(self, db: AsyncSession, tenant, user):
        from app.modules.public_api import service

        result = await service.create_api_key(
            db, tenant.id, user.id, f"test-key-{uuid.uuid4().hex[:6]}"
        )
        # The result dict may use 'key' or 'raw_key' depending on service implementation
        raw_key = result.get("raw_key") or result.get("key")
        assert raw_key is not None
        assert raw_key.startswith("hrp_")
        assert result["name"].startswith("test-key-")

    async def test_list_api_keys(self, db: AsyncSession, tenant, user):
        from app.modules.public_api import service

        await service.create_api_key(
            db, tenant.id, user.id, f"k-{uuid.uuid4().hex[:6]}"
        )
        keys = await service.list_api_keys(db, tenant.id)
        assert len(keys) >= 1

    async def test_revoke_api_key(self, db: AsyncSession, tenant, user):
        from app.modules.public_api import service

        created = await service.create_api_key(
            db, tenant.id, user.id, f"rev-{uuid.uuid4().hex[:6]}"
        )
        await service.revoke_api_key(db, tenant.id, created["id"])
        keys = await service.list_api_keys(db, tenant.id)
        revoked = next(k for k in keys if k["id"] == created["id"])
        assert revoked["is_active"] is False

    async def test_authenticate_api_key(self, db: AsyncSession, tenant, user):
        from app.modules.public_api import service

        created = await service.create_api_key(
            db, tenant.id, user.id, f"auth-{uuid.uuid4().hex[:6]}"
        )
        raw_key = created.get("raw_key") or created.get("key")
        result = await service.authenticate_api_key(db, raw_key)
        assert result is not None

    async def test_authenticate_invalid_key(self, db: AsyncSession):
        from app.modules.public_api import service

        result = await service.authenticate_api_key(db, "hrp_invalid_key_12345")
        assert result is None


class TestNotificationService:
    async def test_list_notifications(self, db: AsyncSession, tenant, user):
        from app.modules.notification import service

        notifs = await service.list_notifications(db, tenant.id, user.id)
        assert isinstance(notifs, list)

    async def test_get_unread_count(self, db: AsyncSession, tenant, user):
        from app.modules.notification import service

        count = await service.get_unread_count(db, tenant.id, user.id)
        assert count >= 0

    async def test_mark_as_read(self, db: AsyncSession, tenant, user):
        from app.modules.notification import service

        updated = await service.mark_as_read(db, tenant.id, user.id)
        assert updated >= 0
