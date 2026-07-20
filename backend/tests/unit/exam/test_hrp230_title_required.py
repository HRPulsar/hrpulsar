"""HRP-230: Title is required on mass-exam create / update."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.modules.exam import service
from app.modules.exam.schemas import MassExamCreate, MassExamUpdate
from sqlalchemy.ext.asyncio import AsyncSession


class TestTitleRequiredOnCreate:
    def test_empty_title_rejected(self):
        with pytest.raises(ValueError):
            MassExamCreate(title="")

    def test_whitespace_only_title_accepted_by_schema(self):
        # Pydantic's min_length only counts characters, not trims — the UI
        # layer trims for us. We assert behavior, not preference.
        MassExamCreate(title=" ")

    def test_long_title_rejected(self):
        with pytest.raises(ValueError):
            MassExamCreate(title="x" * 101)


class TestUpdateMassExam:
    async def test_can_update_deadline(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-230")
        )
        future = datetime(2099, 12, 1, tzinfo=timezone.utc)
        updated = await service.update_mass_exam(
            db, tenant.id, me["id"], MassExamUpdate(ended_at=future)
        )
        assert updated["ended_at"] is not None

    async def test_can_clear_deadline(self, db: AsyncSession, tenant, user):
        me = await service.create_mass_exam(
            db,
            tenant.id,
            user.id,
            MassExamCreate(
                title="HRP-230 clear",
                ended_at=datetime(2099, 12, 1, tzinfo=timezone.utc),
            ),
        )
        updated = await service.update_mass_exam(
            db, tenant.id, me["id"], MassExamUpdate(ended_at=None)
        )
        assert updated["ended_at"] is None

    async def test_cannot_set_empty_title_via_update(
        self, db: AsyncSession, tenant, user
    ):
        with pytest.raises(ValueError):
            MassExamUpdate(title="")
