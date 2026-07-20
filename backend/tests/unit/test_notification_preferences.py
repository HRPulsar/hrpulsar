"""GF10: Notification Preferences — per-user, per-event, per-channel settings."""

import uuid

from app.modules.notification.models import NotificationPreference
from app.modules.notification.service import (
    DEFAULT_EVENT_TYPES,
    _is_channel_enabled,
    get_preferences,
    update_preferences,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class _Stub:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class TestNotificationPreferences:
    # --- Default preferences ---

    async def test_get_preferences_defaults(self, db: AsyncSession, user):
        prefs = await get_preferences(db, user.id)

        expected_count = len(DEFAULT_EVENT_TYPES) * 2
        assert len(prefs) == expected_count

        for p in prefs:
            assert p["enabled"] is True
            assert p["id"] is None

    # --- Check channel enabled ---

    async def test_is_channel_enabled_default(self, db: AsyncSession, user):
        result = await _is_channel_enabled(db, user.id, "assessment_assigned", "email")
        assert result is True

    async def test_is_channel_enabled_disabled(self, db: AsyncSession, user):
        db.add(
            NotificationPreference(
                user_id=user.id,
                event_type="assessment_assigned",
                channel="email",
                enabled=False,
            )
        )
        await db.commit()

        result = await _is_channel_enabled(db, user.id, "assessment_assigned", "email")
        assert result is False

    async def test_is_channel_enabled_other_channels_unaffected(
        self, db: AsyncSession, user
    ):
        db.add(
            NotificationPreference(
                user_id=user.id,
                event_type="pdp_sent",
                channel="email",
                enabled=False,
            )
        )
        await db.commit()

        assert await _is_channel_enabled(db, user.id, "pdp_sent", "email") is False
        assert await _is_channel_enabled(db, user.id, "pdp_sent", "in_app") is True

    # --- Update preferences ---

    async def test_update_preferences_create(self, db: AsyncSession, user):
        items = [
            _Stub(event_type="assessment_assigned", channel="email", enabled=False),
            _Stub(event_type="exam_assigned", channel="in_app", enabled=False),
        ]
        result = await update_preferences(db, user.id, items)

        for p in result:
            if (
                p["event_type"] == "assessment_assigned"
                and p["channel"] == "email"
                or p["event_type"] == "exam_assigned"
                and p["channel"] == "in_app"
            ):
                assert p["enabled"] is False
                assert p["id"] is not None

    async def test_update_preferences_upsert(self, db: AsyncSession, user):
        items1 = [_Stub(event_type="pdp_deadline", channel="email", enabled=False)]
        await update_preferences(db, user.id, items1)

        assert await _is_channel_enabled(db, user.id, "pdp_deadline", "email") is False

        items2 = [_Stub(event_type="pdp_deadline", channel="email", enabled=True)]
        await update_preferences(db, user.id, items2)

        assert await _is_channel_enabled(db, user.id, "pdp_deadline", "email") is True

        result = await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id,
                NotificationPreference.event_type == "pdp_deadline",
                NotificationPreference.channel == "email",
            )
        )
        assert len(result.scalars().all()) == 1

    async def test_update_multiple_preferences(self, db: AsyncSession, user):
        items = [
            _Stub(event_type="assessment_assigned", channel="email", enabled=False),
            _Stub(event_type="assessment_assigned", channel="in_app", enabled=True),
            _Stub(event_type="pdp_sent", channel="email", enabled=False),
            _Stub(event_type="pdp_sent", channel="in_app", enabled=False),
        ]
        result = await update_preferences(db, user.id, items)

        saved = [p for p in result if p["id"] is not None]
        assert len(saved) >= 4

    # --- Tenant isolation ---

    async def test_preferences_per_user(
        self, db: AsyncSession, user, tenant, admin_role
    ):
        """Each user has independent preferences."""
        from app.core.security import hash_password
        from app.modules.auth.models import User as UserModel

        user2 = UserModel(
            email=f"other-{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("pass"),
            first_name="Other",
            last_name="User",
            tenant_id=tenant.id,
        )
        db.add(user2)
        await db.commit()
        await db.refresh(user2)

        await update_preferences(
            db,
            user.id,
            [
                _Stub(event_type="general", channel="email", enabled=False),
            ],
        )

        assert await _is_channel_enabled(db, user2.id, "general", "email") is True
        assert await _is_channel_enabled(db, user.id, "general", "email") is False
