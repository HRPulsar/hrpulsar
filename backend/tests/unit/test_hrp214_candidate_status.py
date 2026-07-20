"""HRP-214: TalentCandidate.status reflects current match evaluation.

The Candidates table used to display ``nominated`` for every row the
auto-pool produced and for manual picks alike — recruiters couldn't
tell at a glance which candidates currently fit the card. HRP-214
splits the non-appointed bucket into ``matched`` and ``not_matched``
based on the same matcher that already drives the picker dialog.

Covered here:

* auto-pool stamps ``matched`` on qualifying employees, not ``nominated``;
* a manual pick added through the picker is ``matched`` when the
  employee qualifies and ``not_matched`` otherwise;
* an existing ``not_matched`` pick is promoted to ``matched`` when the
  threshold drops below the employee's score;
* ``appointed`` survives a recompute (terminal state).
"""

from __future__ import annotations

from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCandidate
from app.modules.talent_market.schemas import (
    CandidateAdd,
    RequiredCompetenceBulkCreate,
    RequiredCompetenceItem,
    TalentCardCreate,
    TalentCardUpdate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp129_auto_match import (
    _add_done_assessment,
    _make_competence,
    _make_employee,
    _make_skill_level,
)


async def test_auto_pool_stamps_matched_not_nominated(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="V", card_type="vacancy", match_percent=80),
    )
    sl = await _make_skill_level(db, tenant.id, sort_index=1)
    comp = await _make_competence(db, tenant.id, "C")
    emp = await _make_employee(db, tenant.id, name="A")
    await _add_done_assessment(
        db, tenant.id, emp.id, user.id, comp.id, sl.id, 90
    )

    await service.add_required_competences(
        db,
        tenant.id,
        card_dict["id"],
        RequiredCompetenceBulkCreate(
            items=[RequiredCompetenceItem(competence_id=comp.id, skill_level_id=sl.id)]
        ),
    )
    rows = (
        (
            await db.execute(
                select(TalentCandidate).where(
                    TalentCandidate.card_id == card_dict["id"]
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "matched"


async def test_manual_pick_non_qualifying_is_not_matched(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="V", card_type="vacancy", match_percent=80),
    )
    sl = await _make_skill_level(db, tenant.id, sort_index=1)
    comp = await _make_competence(db, tenant.id, "C")
    emp = await _make_employee(db, tenant.id, name="B")
    await _add_done_assessment(
        db, tenant.id, emp.id, user.id, comp.id, sl.id, 50
    )
    await service.add_required_competences(
        db,
        tenant.id,
        card_dict["id"],
        RequiredCompetenceBulkCreate(
            items=[RequiredCompetenceItem(competence_id=comp.id, skill_level_id=sl.id)]
        ),
    )

    # Auto-pool kicked out the low-scoring employee because they don't
    # qualify — manual pick re-attaches them as `not_matched`.
    cand = await service.add_candidate(
        db, tenant.id, card_dict["id"], CandidateAdd(employee_id=emp.id)
    )
    assert cand["status"] == "not_matched"


async def test_threshold_drop_promotes_not_matched_to_matched(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="V", card_type="vacancy", match_percent=80),
    )
    sl = await _make_skill_level(db, tenant.id, sort_index=1)
    comp = await _make_competence(db, tenant.id, "C")
    emp = await _make_employee(db, tenant.id, name="C")
    await _add_done_assessment(
        db, tenant.id, emp.id, user.id, comp.id, sl.id, 70
    )
    await service.add_required_competences(
        db,
        tenant.id,
        card_dict["id"],
        RequiredCompetenceBulkCreate(
            items=[RequiredCompetenceItem(competence_id=comp.id, skill_level_id=sl.id)]
        ),
    )
    cand = await service.add_candidate(
        db, tenant.id, card_dict["id"], CandidateAdd(employee_id=emp.id)
    )
    assert cand["status"] == "not_matched"

    # Lower the threshold below the actual score → the auto-recompute
    # promotes the employee to `matched` without re-creating the row.
    await service.update_card(
        db,
        tenant.id,
        card_dict["id"],
        TalentCardUpdate(match_percent=60),
    )
    rows = (
        (
            await db.execute(
                select(TalentCandidate).where(
                    TalentCandidate.card_id == card_dict["id"]
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "matched"


async def test_appointed_status_survives_recompute(
    db: AsyncSession, tenant, user
) -> None:
    card_dict = await service.create_card(
        db,
        tenant.id,
        user.id,
        TalentCardCreate(title="V", card_type="vacancy", match_percent=80),
    )
    sl = await _make_skill_level(db, tenant.id, sort_index=1)
    comp = await _make_competence(db, tenant.id, "C")
    emp = await _make_employee(db, tenant.id, name="D")
    await _add_done_assessment(
        db, tenant.id, emp.id, user.id, comp.id, sl.id, 90
    )
    await service.add_required_competences(
        db,
        tenant.id,
        card_dict["id"],
        RequiredCompetenceBulkCreate(
            items=[RequiredCompetenceItem(competence_id=comp.id, skill_level_id=sl.id)]
        ),
    )
    cand_row = (
        await db.execute(
            select(TalentCandidate).where(
                TalentCandidate.card_id == card_dict["id"]
            )
        )
    ).scalar_one()
    appointed = await service.appoint_candidate(
        db, tenant.id, card_dict["id"], cand_row.id
    )
    assert appointed["status"] == "appointed"

    # Raise the threshold so the employee no longer qualifies — the
    # recompute must NOT overwrite the appointed status.
    await service.update_card(
        db,
        tenant.id,
        card_dict["id"],
        TalentCardUpdate(match_percent=95),
    )
    rows = (
        (
            await db.execute(
                select(TalentCandidate).where(
                    TalentCandidate.card_id == card_dict["id"]
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "appointed"
