"""HRP-1087: a vacancy's library competences carry the proficiency level.

Seeded from the specialization x grade matrix, a competence holds the levels
its grades ask, lowest first - the one the vacancy shows and the one its
talent-market twin matches on. Picked in the dialog, it carries the chosen
level to the card the same way.
"""

from __future__ import annotations

import uuid

from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system.models import GradeCompetenceLink, GradeSpecialization
from app.modules.recruitment import service
from app.modules.recruitment.schemas import (
    SpecializationGradePair,
    VacancyCompetenceSpec,
    VacancyCompetencesUpdate,
    VacancyCreate,
    VacancyLibraryRefs,
)
from app.modules.talent_market.models import TalentCardCompetence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _matrix(db: AsyncSession, tenant):
    spec = DictionaryItem(type="specialization", title="Backend", tenant_id=tenant.id)
    middle = DictionaryItem(type="grade", title="Middle", tenant_id=tenant.id)
    senior = DictionaryItem(type="grade", title="Senior", tenant_id=tenant.id)
    group = CompetenceGroup(tenant_id=tenant.id, title="Eng")
    db.add_all([spec, middle, senior, group])
    await db.commit()
    comp = Competence(tenant_id=tenant.id, group_id=group.id, title="Python")
    # Created high first, so insertion order is not ladder order.
    high = SkillLevel(tenant_id=tenant.id, title="Expert", sort_index=3)
    low = SkillLevel(tenant_id=tenant.id, title="Advanced", sort_index=2)
    db.add_all([comp, high, low])
    await db.commit()
    for grade, level in ((senior, high), (middle, low)):
        gs = GradeSpecialization(
            tenant_id=tenant.id, specialization_id=spec.id, grade_id=grade.id
        )
        db.add(gs)
        await db.commit()
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=comp.id,
                skill_level_id=level.id,
            )
        )
    await db.commit()
    return spec, (middle, senior), comp, low, high


async def _card_levels(db: AsyncSession, card_id) -> list:
    rows = await db.execute(
        select(TalentCardCompetence).where(TalentCardCompetence.card_id == card_id)
    )
    return [(r.competence_id, r.skill_level_id) for r in rows.scalars()]


async def test_a_seeded_competence_carries_its_grades_level_to_the_card(
    db: AsyncSession, tenant, user
):
    spec, grades, comp, low, high = await _matrix(db, tenant)
    vacancy = await service.create_vacancy(
        db,
        tenant.id,
        user.id,
        VacancyCreate(
            title=f"V {uuid.uuid4().hex[:6]}",
            library_refs=VacancyLibraryRefs(
                specialization_grade_pairs=[
                    SpecializationGradePair(
                        specialization_id=spec.id,
                        grade_ids=[g.id for g in reversed(grades)],
                    )
                ]
            ),
        ),
    )
    rows = await service.list_vacancy_competences(db, tenant.id, vacancy["id"])
    assert [(r["competence_id"], r["skill_level_ids"]) for r in rows] == [
        (comp.id, [str(low.id), str(high.id)])
    ]
    posted = await service.post_vacancy_to_talent_market(
        db, tenant.id, vacancy["id"], user.id
    )
    assert await _card_levels(db, posted["talent_card_id"]) == [(comp.id, low.id)]


async def test_a_level_picked_in_the_dialog_reaches_the_card(
    db: AsyncSession, tenant, user
):
    _, _, comp, _, high = await _matrix(db, tenant)
    vacancy = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title="Picked")
    )
    await service.set_vacancy_competences(
        db,
        tenant.id,
        vacancy["id"],
        VacancyCompetencesUpdate(
            competences=[
                VacancyCompetenceSpec(
                    competence_id=comp.id, skill_level_ids=[high.id], source="library"
                )
            ]
        ),
    )
    posted = await service.post_vacancy_to_talent_market(
        db, tenant.id, vacancy["id"], user.id
    )
    assert await _card_levels(db, posted["talent_card_id"]) == [(comp.id, high.id)]
