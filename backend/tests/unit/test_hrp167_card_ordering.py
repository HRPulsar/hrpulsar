"""HRP-167: Talent Market list ordering.

Active cards (Draft / Published) come first sorted by created_at desc,
then Completed by completed_at desc, then Cancelled by cancelled_at
desc. The detail-page overdue highlight is covered in the frontend; the
backend half pins the ordering contract.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCard
from app.modules.talent_market.schemas import SearchRequest, TalentCardCreate
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def cards_across_statuses(
    db: AsyncSession, tenant, user
) -> dict[str, uuid.UUID]:
    """Cards: 2 active (newer first), 2 completed (newer first), 2 cancelled."""
    now = datetime.now(timezone.utc)

    async def _mk(title: str) -> TalentCard:
        c = await service.create_card(
            db,
            tenant.id,
            user.id,
            TalentCardCreate(title=title, card_type="vacancy"),
        )
        row = await db.get(TalentCard, c["id"])
        assert row is not None
        return row

    active_old = await _mk("active-old")
    active_old.created_at = now - timedelta(days=10)
    active_new = await _mk("active-new")
    active_new.created_at = now - timedelta(days=1)

    completed_old = await _mk("completed-old")
    completed_old.status = "completed"
    completed_old.completed_at = now - timedelta(days=5)
    completed_new = await _mk("completed-new")
    completed_new.status = "completed"
    completed_new.completed_at = now - timedelta(hours=1)

    cancelled_old = await _mk("cancelled-old")
    cancelled_old.status = "cancelled"
    cancelled_old.cancelled_at = now - timedelta(days=20)
    cancelled_new = await _mk("cancelled-new")
    cancelled_new.status = "cancelled"
    cancelled_new.cancelled_at = now - timedelta(days=2)

    await db.commit()
    return {
        "active_old": active_old.id,
        "active_new": active_new.id,
        "completed_old": completed_old.id,
        "completed_new": completed_new.id,
        "cancelled_old": cancelled_old.id,
        "cancelled_new": cancelled_new.id,
    }


class TestCardOrdering:
    async def test_active_first_then_completed_then_cancelled(
        self, db: AsyncSession, tenant, cards_across_statuses
    ) -> None:
        items, total = await service.search_cards(
            db, tenant.id, SearchRequest(limit=50)
        )
        # All six cards land in the response.
        assert total == 6
        order = [c["title"] for c in items]
        # Active (newer first), then completed (newer first), then cancelled.
        assert order == [
            "active-new",
            "active-old",
            "completed-new",
            "completed-old",
            "cancelled-new",
            "cancelled-old",
        ]
