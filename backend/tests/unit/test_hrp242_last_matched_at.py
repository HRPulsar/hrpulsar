"""HRP-242: ``talent_cards.last_matched_at`` + explicit recompute.

Verifies the stamp on the auto-pool path, the manual picker path, and the
new POST /talent-market/{card_id}/recompute endpoint.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCandidate, TalentCard
from app.modules.talent_market.schemas import (
    CandidateBulkAdd,
    RequiredCompetenceBulkCreate,
    RequiredCompetenceItem,
    TalentCardCreate,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp129_auto_match import (
    _make_competence,
    _make_employee,
    _make_skill_level,
)


async def _make_card(db: AsyncSession, tenant_id, user_id) -> dict:
    return await service.create_card(
        db,
        tenant_id,
        user_id,
        TalentCardCreate(title="TM", card_type="vacancy", match_percent=80),
    )


async def test_auto_populate_stamps_last_matched_at(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await _make_card(db, tenant.id, user.id)
    comp = await _make_competence(db, tenant.id, "C")
    sl = await _make_skill_level(db, tenant.id, sort_index=1)
    before = datetime.now(timezone.utc)
    await service.add_required_competences(
        db,
        tenant.id,
        card_dict["id"],
        RequiredCompetenceBulkCreate(
            items=[
                RequiredCompetenceItem(
                    competence_id=comp.id, skill_level_id=sl.id
                )
            ]
        ),
    )
    card = await db.get(TalentCard, card_dict["id"])
    assert card is not None and card.last_matched_at is not None
    assert card.last_matched_at >= before - timedelta(seconds=5)


async def test_bulk_picker_save_stamps_last_matched_at(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await _make_card(db, tenant.id, user.id)
    emp = await _make_employee(db, tenant.id, name="EmpA")
    before = datetime.now(timezone.utc)
    await service.add_candidates_bulk(
        db,
        tenant.id,
        card_dict["id"],
        CandidateBulkAdd(employee_ids=[emp.id]),
    )
    card = await db.get(TalentCard, card_dict["id"])
    assert card is not None and card.last_matched_at is not None
    assert card.last_matched_at >= before - timedelta(seconds=5)


async def test_recompute_card_candidates_refreshes_stamp(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await _make_card(db, tenant.id, user.id)
    # Pre-stamp at the auto-populate path by adding a Required Competence.
    comp = await _make_competence(db, tenant.id, "C")
    sl = await _make_skill_level(db, tenant.id, sort_index=1)
    await service.add_required_competences(
        db,
        tenant.id,
        card_dict["id"],
        RequiredCompetenceBulkCreate(
            items=[
                RequiredCompetenceItem(
                    competence_id=comp.id, skill_level_id=sl.id
                )
            ]
        ),
    )
    card = await db.get(TalentCard, card_dict["id"])
    assert card is not None
    initial = card.last_matched_at
    assert initial is not None
    # Refresh and confirm the stamp advances.
    import asyncio

    await asyncio.sleep(0.05)
    refreshed = await service.recompute_card_candidates(
        db, tenant.id, card_dict["id"]
    )
    assert refreshed["last_matched_at"] is not None
    assert refreshed["last_matched_at"] > initial


async def test_recompute_rejects_terminal_card(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await _make_card(db, tenant.id, user.id)
    card = await db.get(TalentCard, card_dict["id"])
    assert card is not None
    card.status = "completed"
    await db.commit()
    with pytest.raises(HTTPException) as ex:
        await service.recompute_card_candidates(
            db, tenant.id, card_dict["id"]
        )
    assert ex.value.status_code == 409


async def test_recompute_preserves_appointed_candidates(
    db: AsyncSession, tenant, user
) -> None:
    """Appointed rows must survive the recompute (same rule the silent
    auto-pool already follows for the matched bucket)."""
    card_dict = await _make_card(db, tenant.id, user.id)
    emp = await _make_employee(db, tenant.id, name="App")
    # Attach + appoint
    await service.add_candidates_bulk(
        db,
        tenant.id,
        card_dict["id"],
        CandidateBulkAdd(employee_ids=[emp.id]),
    )
    cand_row = (
        await db.execute(
            select(TalentCandidate).where(
                TalentCandidate.card_id == card_dict["id"],
                TalentCandidate.employee_id == emp.id,
            )
        )
    ).scalar_one()
    cand_row.status = "appointed"
    await db.commit()
    await service.recompute_card_candidates(
        db, tenant.id, card_dict["id"]
    )
    surviving = (
        await db.execute(
            select(TalentCandidate).where(
                TalentCandidate.card_id == card_dict["id"],
                TalentCandidate.employee_id == emp.id,
            )
        )
    ).scalar_one_or_none()
    assert surviving is not None
    assert surviving.status == "appointed"
