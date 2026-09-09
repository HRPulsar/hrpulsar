"""HRP-742: an existing scale's divergence threshold is readable and editable.

The threshold could only be set while creating a scale — the list the
settings page renders never showed it back, so a workspace that picked
the wrong number had to build a new scale to change it.
"""

from __future__ import annotations

import uuid

import pytest
from app.core.errors import AppError
from app.modules.recruitment import manager_assessment_service as service
from app.modules.recruitment.manager_assessment_schemas import (
    ScaleCreate,
    ScaleLevelIn,
    ScaleUpdate,
)
from sqlalchemy.ext.asyncio import AsyncSession


def _payload(threshold: int) -> ScaleCreate:
    return ScaleCreate(
        name=f"Scale {uuid.uuid4().hex[:6]}",
        divergence_threshold=threshold,
        levels=[
            ScaleLevelIn(value=1, label="L1", weight=0),
            ScaleLevelIn(value=2, label="L2", weight=50),
            ScaleLevelIn(value=3, label="L3", weight=100),
        ],
    )


class TestScaleDivergenceThreshold:
    async def test_list_and_detail_report_the_threshold(
        self, db: AsyncSession, tenant, user
    ):
        created = await service.create_scale(db, tenant.id, user.id, _payload(3))
        scale_id = uuid.UUID(str(created["id"]))

        detail = await service.get_scale(db, tenant.id, scale_id)
        assert detail["divergence_threshold"] == 3
        listed = next(
            s for s in await service.list_scales(db, tenant.id) if s["id"] == scale_id
        )
        assert listed["divergence_threshold"] == 3

    async def test_threshold_can_be_changed_after_creation(
        self, db: AsyncSession, tenant, user
    ):
        created = await service.create_scale(db, tenant.id, user.id, _payload(2))
        scale_id = uuid.UUID(str(created["id"]))

        updated = await service.update_scale(
            db, tenant.id, user.id, scale_id, ScaleUpdate(divergence_threshold=4)
        )
        assert updated["divergence_threshold"] == 4
        # Levels are untouched by a threshold-only edit — the page sends
        # nothing else, and a scale already in use must keep them.
        assert [lvl["value"] for lvl in updated["levels"]] == [1, 2, 3]

    async def test_an_archived_scale_stays_read_only(
        self, db: AsyncSession, tenant, user
    ):
        created = await service.create_scale(db, tenant.id, user.id, _payload(2))
        scale_id = uuid.UUID(str(created["id"]))
        await service.archive_scale(db, tenant.id, user.id, scale_id)

        with pytest.raises(AppError):
            await service.update_scale(
                db, tenant.id, user.id, scale_id, ScaleUpdate(divergence_threshold=5)
            )
