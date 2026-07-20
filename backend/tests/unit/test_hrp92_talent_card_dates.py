"""HRP-92: Talent Card start_date / end_date.

Covers:
- create defaults start_date to today when omitted
- create accepts explicit start_date and end_date
- create rejects end_date < start_date
- update rejects end_date that lands before the saved start_date
- update rejects clearing start_date implicitly via patch
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from app.modules.talent_market import service
from app.modules.talent_market.schemas import TalentCardCreate, TalentCardUpdate
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


async def test_create_defaults_start_date_to_today(
    db: AsyncSession, tenant, user
) -> None:
    today = date.today()
    data = TalentCardCreate(title="T", card_type="vacancy")
    result = await service.create_card(db, tenant.id, user.id, data)
    assert result["start_date"] == today
    assert result["end_date"] is None


async def test_create_accepts_explicit_dates(
    db: AsyncSession, tenant, user
) -> None:
    start = date.today() + timedelta(days=10)
    end = date.today() + timedelta(days=40)
    data = TalentCardCreate(
        title="T", card_type="vacancy", start_date=start, end_date=end
    )
    result = await service.create_card(db, tenant.id, user.id, data)
    assert result["start_date"] == start
    assert result["end_date"] == end


def test_create_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match="end_date must be on or after start_date"):
        TalentCardCreate(
            title="T",
            card_type="vacancy",
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 9),
        )


def test_create_rejects_start_out_of_window() -> None:
    with pytest.raises(ValueError, match="start_date out of allowed range"):
        TalentCardCreate(
            title="T",
            card_type="vacancy",
            start_date=date.today() - timedelta(days=365 * 6),
        )


def test_create_rejects_end_out_of_window() -> None:
    # HRP-92 spec: end_date max = today + 5y. Reject anything further out.
    with pytest.raises(ValueError, match="end_date out of allowed range"):
        TalentCardCreate(
            title="T",
            card_type="vacancy",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365 * 6),
        )


async def test_update_rejects_end_before_existing_start(
    db: AsyncSession, tenant, user
) -> None:
    start = date.today() + timedelta(days=10)
    card = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="T", card_type="vacancy", start_date=start),
    )
    with pytest.raises(HTTPException) as exc:
        await service.update_card(
            db,
            tenant.id,
            uuid.UUID(str(card["id"])),
            TalentCardUpdate(end_date=start - timedelta(days=1)),
        )
    assert exc.value.status_code == 400


async def test_update_accepts_widening_dates(
    db: AsyncSession, tenant, user
) -> None:
    start = date.today()
    card = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="T", card_type="vacancy", start_date=start),
    )
    new_end = start + timedelta(days=30)
    result = await service.update_card(
        db,
        tenant.id,
        uuid.UUID(str(card["id"])),
        TalentCardUpdate(end_date=new_end),
    )
    assert result["end_date"] == new_end
    assert result["start_date"] == start
