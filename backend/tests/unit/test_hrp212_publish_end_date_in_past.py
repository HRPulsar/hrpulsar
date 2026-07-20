"""HRP-212: publish is blocked when End date already slipped.

The Draft → Published transition checks ``end_date`` against today.
Today still counts as the future. The card stays in Draft and the
service raises 422 with a clear message — the UI surfaces it as the
existing toast pattern.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCard
from app.modules.talent_market.schemas import TalentCardCreate
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_talent_market_service import (
    _attach_min_candidate,
    _attach_min_competence,
)


async def _draft_card_with_end(
    db: AsyncSession,
    tenant,
    user,
    *,
    end: date | None,
) -> str:
    card = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(
            title="T",
            card_type="vacancy",
            start_date=date.today() - timedelta(days=30),
            end_date=end,
        ),
    )
    return card["id"]


async def test_publish_rejected_when_end_date_in_past(
    db: AsyncSession, tenant, user, employee
) -> None:
    card_id = await _draft_card_with_end(
        db, tenant, user, end=date.today() - timedelta(days=1)
    )
    await _attach_min_competence(db, tenant.id, card_id)
    await _attach_min_candidate(db, tenant.id, card_id, employee.id)

    with pytest.raises(HTTPException) as exc:
        await service.publish_card(db, tenant.id, card_id)
    assert exc.value.status_code == 422
    assert "End date is in the past" in str(exc.value.detail)

    refreshed = await db.get(TalentCard, card_id)
    assert refreshed is not None
    assert refreshed.status == "draft"
    assert refreshed.is_published is False


async def test_publish_allows_end_date_today(
    db: AsyncSession, tenant, user, employee
) -> None:
    card_id = await _draft_card_with_end(db, tenant, user, end=date.today())
    await _attach_min_competence(db, tenant.id, card_id)
    await _attach_min_candidate(db, tenant.id, card_id, employee.id)

    result = await service.publish_card(db, tenant.id, card_id)
    assert result["status"] == "published"


async def test_publish_allows_no_end_date(
    db: AsyncSession, tenant, user, employee
) -> None:
    card_id = await _draft_card_with_end(db, tenant, user, end=None)
    await _attach_min_competence(db, tenant.id, card_id)
    await _attach_min_candidate(db, tenant.id, card_id, employee.id)

    result = await service.publish_card(db, tenant.id, card_id)
    assert result["status"] == "published"
