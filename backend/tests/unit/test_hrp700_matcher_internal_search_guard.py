"""HRP-700: the internal-search switch freezes the candidate pool.

HRP-678 put the switch on the vacancy, but only the two recruitment-side
paths honoured it (the talent-market bridge and the competence sync).
Every Talent Market edit — a requirement block, the match threshold, the
explicit Recompute button — calls the matcher directly, so an excluded
vacancy's shortlist kept being rebuilt behind the switch. The guard now
lives in ``_auto_populate_candidates`` itself, which is the one place
all of those paths pass through.

The matcher never mailed anyone itself — the HRP-211 lifecycle mail goes
out from publish / add candidate / appoint / complete / cancel — so what
these tests pin is the pool: the rows the shortlist is made of, and the
set those later mails would be addressed to.
"""

from __future__ import annotations

import uuid

from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
from app.modules.recruitment import service as recruitment_service
from app.modules.recruitment.models import Vacancy, VacancyCompetence
from app.modules.recruitment.schemas import VacancyCreate
from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCandidate
from app.modules.talent_market.schemas import (
    RequiredCompetenceBulkCreate,
    RequiredCompetenceItem,
    TalentCardCreate,
    TalentCardUpdate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _competence(db: AsyncSession, tenant_id) -> tuple[Competence, SkillLevel]:
    group = CompetenceGroup(tenant_id=tenant_id, title=f"G-{uuid.uuid4().hex[:4]}")
    db.add(group)
    await db.flush()
    comp = Competence(
        tenant_id=tenant_id, group_id=group.id, title=f"C-{uuid.uuid4().hex[:4]}"
    )
    sl = SkillLevel(
        tenant_id=tenant_id, title=f"L-{uuid.uuid4().hex[:4]}", sort_index=0
    )
    db.add_all([comp, sl])
    await db.commit()
    return comp, sl


async def _posted_vacancy(db: AsyncSession, tenant_id, user_id) -> tuple:
    """A vacancy posted to the talent market, plus its card id."""
    await recruitment_service.seed_default_recruitment_stages(db, tenant_id)
    await db.commit()
    vacancy = await recruitment_service.create_vacancy(
        db, tenant_id, user_id, VacancyCreate(title=f"V-{uuid.uuid4().hex[:6]}")
    )
    comp, sl = await _competence(db, tenant_id)
    db.add(
        VacancyCompetence(
            tenant_id=tenant_id,
            vacancy_id=vacancy["id"],
            competence_id=comp.id,
            skill_level_ids=[],
        )
    )
    await db.commit()
    posted = await recruitment_service.post_vacancy_to_talent_market(
        db, tenant_id, vacancy["id"], user_id
    )
    return vacancy["id"], posted["talent_card_id"], comp, sl


async def _set_switch(db: AsyncSession, vacancy_id, value: bool) -> None:
    row = await db.get(Vacancy, vacancy_id)
    assert row is not None
    row.internal_search_allowed = value
    await db.commit()


async def _pool(db: AsyncSession, card_id) -> list[TalentCandidate]:
    return list(
        (
            await db.execute(
                select(TalentCandidate).where(TalentCandidate.card_id == card_id)
            )
        )
        .scalars()
        .all()
    )


async def test_switch_off_freezes_the_pool_on_every_talent_market_path(
    db: AsyncSession, tenant, user, employee
) -> None:
    """Requirement edits, the threshold and Recompute all leave the pool alone.

    The seeded row does not qualify (the employee has no assessment
    covering the card's competence), so a matcher that ran would prune
    it — surviving is the proof that it did not run.
    """
    vacancy_id, card_id, comp, sl = await _posted_vacancy(db, tenant.id, user.id)
    await _set_switch(db, vacancy_id, False)
    db.add(TalentCandidate(card_id=card_id, employee_id=employee.id, status="matched"))
    await db.commit()

    await service.recompute_card_candidates(db, tenant.id, card_id)
    await service.add_required_competences(
        db,
        tenant.id,
        card_id,
        RequiredCompetenceBulkCreate(
            items=[RequiredCompetenceItem(competence_id=comp.id, skill_level_id=sl.id)]
        ),
    )
    await service.update_card(
        db, tenant.id, card_id, TalentCardUpdate(match_percent=55)
    )

    assert [r.employee_id for r in await _pool(db, card_id)] == [employee.id]


async def test_switch_back_on_lets_the_recompute_through(
    db: AsyncSession, tenant, user, employee
) -> None:
    vacancy_id, card_id, _, _ = await _posted_vacancy(db, tenant.id, user.id)
    await _set_switch(db, vacancy_id, False)
    db.add(TalentCandidate(card_id=card_id, employee_id=employee.id, status="matched"))
    await db.commit()
    await service.recompute_card_candidates(db, tenant.id, card_id)
    assert len(await _pool(db, card_id)) == 1

    await _set_switch(db, vacancy_id, True)
    await service.recompute_card_candidates(db, tenant.id, card_id)
    assert await _pool(db, card_id) == []


async def test_a_card_without_a_vacancy_is_untouched(
    db: AsyncSession, tenant, user, employee
) -> None:
    """A plain Talent Market card has no switch behind it — nothing changes."""
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="T", card_type="talent")
    )
    db.add(
        TalentCandidate(card_id=card["id"], employee_id=employee.id, status="matched")
    )
    await db.commit()

    await service.recompute_card_candidates(db, tenant.id, card["id"])
    assert await _pool(db, card["id"]) == []
