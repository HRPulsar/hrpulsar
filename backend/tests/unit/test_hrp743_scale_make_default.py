"""HRP-743: "Make default" on the assessment-scales settings page must not 500.

Regression coverage only: the defect itself was fixed on main by HRP-811
(the cleared default is flushed before the new one is written).

The reporter's flow, in both orders it was filed: the seeded default scale
plus one created by hand; Make default on the new one, then on the seeded
one again. A partial unique index allows one default per workspace, and
the unit of work emits same-table UPDATEs in primary-key order — so
whichever scale sorted first could reach the index before the other was
cleared. The ids are pinned here so the failing order is deterministic
rather than a coin toss on uuid4.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.recruitment import manager_assessment_service as service
from app.modules.recruitment.manager_assessment_models import AssessmentScale
from app.modules.recruitment.manager_assessment_schemas import ScaleUpdate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _defaults(db: AsyncSession, tenant_id) -> list[uuid.UUID]:
    rows = await db.execute(
        select(AssessmentScale.id).where(
            AssessmentScale.tenant_id == tenant_id,
            AssessmentScale.is_default.is_(True),
            AssessmentScale.archived_at.is_(None),
        )
    )
    return list(rows.scalars().all())


async def _seed_two_scales(
    db: AsyncSession, tenant, user
) -> tuple[uuid.UUID, uuid.UUID]:
    """The seeded default and a hand-made scale, with the hand-made one
    sorting *first* by primary key — the order that used to break."""
    low, high = sorted([uuid.uuid4(), uuid.uuid4()])
    db.add_all(
        [
            AssessmentScale(
                id=high,
                tenant_id=tenant.id,
                name="Seeded default",
                is_default=True,
                divergence_threshold=2,
                version=1,
            ),
            AssessmentScale(
                id=low,
                tenant_id=tenant.id,
                name="Mine",
                is_default=False,
                divergence_threshold=2,
                version=1,
            ),
        ]
    )
    await db.commit()
    return low, high


async def test_make_default_in_the_reporters_order(db: AsyncSession, tenant, user):
    mine, seeded = await _seed_two_scales(db, tenant, user)

    made = await service.update_scale(
        db, tenant.id, user.id, mine, ScaleUpdate(is_default=True)
    )
    assert made["is_default"] is True
    assert await _defaults(db, tenant.id) == [mine]

    back = await service.update_scale(
        db, tenant.id, user.id, seeded, ScaleUpdate(is_default=True)
    )
    assert back["is_default"] is True
    assert await _defaults(db, tenant.id) == [seeded]


async def test_make_default_on_the_default_is_harmless(db: AsyncSession, tenant, user):
    mine, seeded = await _seed_two_scales(db, tenant, user)

    again = await service.update_scale(
        db, tenant.id, user.id, seeded, ScaleUpdate(is_default=True)
    )

    assert again["is_default"] is True
    assert await _defaults(db, tenant.id) == [seeded]
