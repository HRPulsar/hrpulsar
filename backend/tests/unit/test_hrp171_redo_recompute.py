"""HRP-171 REDO: Required Competences recompute on spec PATCH / DELETE.

Reporter (2026-06-02) hit two cases the original HRP-171 ship
missed:

* 2.1 — editing the grade of an existing Required Specialization leaves
  the Required Competences block tied to the old grade.
* 2.2 — deleting a Required Specialization leaves its derived
  competences on the card.

The recompute helper rebuilds the block from the union of every
current spec's ``GradeSpecialization.competence_links``, so either path
ends up with the right competence set.
"""

from __future__ import annotations

import uuid

from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system.models import (
    GradeCompetenceLink,
    GradeSpecialization,
)
from app.modules.talent_market import service
from app.modules.talent_market.schemas import (
    RequiredSpecializationCreate,
    RequiredSpecializationUpdate,
    TalentCardCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_pair_with_competence(
    db: AsyncSession,
    tenant,
    *,
    grade_title: str,
) -> tuple[DictionaryItem, DictionaryItem, Competence, SkillLevel]:
    """Build a (spec, grade) pair wired to one (competence, skill level).

    Returns the dictionary items so the test can stitch new specs onto
    the card and compare against the expected competence ids.
    """
    spec = DictionaryItem(
        type="specialization",
        tenant_id=tenant.id,
        title=f"Spec-{uuid.uuid4().hex[:4]}",
        is_active=True,
    )
    grade = DictionaryItem(
        type="grade",
        tenant_id=tenant.id,
        title=grade_title,
        is_active=True,
    )
    db.add_all([spec, grade])
    await db.flush()

    gs = GradeSpecialization(
        tenant_id=tenant.id, grade_id=grade.id, specialization_id=spec.id
    )
    db.add(gs)
    await db.flush()

    group = CompetenceGroup(tenant_id=tenant.id, title=f"G-{uuid.uuid4().hex[:4]}")
    db.add(group)
    await db.flush()
    comp = Competence(
        tenant_id=tenant.id, group_id=group.id, title=f"C-{uuid.uuid4().hex[:4]}"
    )
    db.add(comp)
    sl = SkillLevel(
        tenant_id=tenant.id, title=f"L-{uuid.uuid4().hex[:4]}", sort_index=0
    )
    db.add(sl)
    await db.flush()

    db.add(
        GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=comp.id,
            skill_level_id=sl.id,
        )
    )
    await db.commit()
    return spec, grade, comp, sl


async def _seed_extra_grade_for_spec(
    db: AsyncSession,
    tenant,
    spec: DictionaryItem,
    *,
    grade_title: str,
) -> tuple[DictionaryItem, Competence, SkillLevel]:
    """Wire a new grade for an existing spec, with its own competence link."""
    grade = DictionaryItem(
        type="grade",
        tenant_id=tenant.id,
        title=grade_title,
        is_active=True,
    )
    db.add(grade)
    await db.flush()

    gs = GradeSpecialization(
        tenant_id=tenant.id, grade_id=grade.id, specialization_id=spec.id
    )
    db.add(gs)
    await db.flush()

    group = CompetenceGroup(tenant_id=tenant.id, title=f"G-{uuid.uuid4().hex[:4]}")
    db.add(group)
    await db.flush()
    comp = Competence(
        tenant_id=tenant.id, group_id=group.id, title=f"C-{uuid.uuid4().hex[:4]}"
    )
    db.add(comp)
    sl = SkillLevel(
        tenant_id=tenant.id, title=f"L-{uuid.uuid4().hex[:4]}", sort_index=0
    )
    db.add(sl)
    await db.flush()

    db.add(
        GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=comp.id,
            skill_level_id=sl.id,
        )
    )
    await db.commit()
    return grade, comp, sl


async def test_update_required_spec_recomputes_competences(
    db: AsyncSession, tenant, user
) -> None:
    """REDO case 2.1: PATCH grade rewires the auto-derived competences."""
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="T", card_type="vacancy")
    )
    spec, middle_grade, mid_comp, mid_sl = await _seed_pair_with_competence(
        db, tenant, grade_title="Middle"
    )
    senior_grade, sr_comp, sr_sl = await _seed_extra_grade_for_spec(
        db, tenant, spec, grade_title="Senior"
    )

    link = await service.add_required_specialization(
        db,
        tenant.id,
        card["id"],
        RequiredSpecializationCreate(
            specialization_id=spec.id, grade_id=middle_grade.id
        ),
    )
    detail = await service.get_card_detail(db, tenant.id, card["id"])
    middle_pairs = {
        (c["competence_id"], c["skill_level_id"]) for c in detail["competences"]
    }
    assert middle_pairs == {(mid_comp.id, mid_sl.id)}

    await service.update_required_specialization(
        db,
        tenant.id,
        card["id"],
        link["id"],
        RequiredSpecializationUpdate(
            specialization_id=spec.id, grade_id=senior_grade.id
        ),
    )
    detail = await service.get_card_detail(db, tenant.id, card["id"])
    senior_pairs = {
        (c["competence_id"], c["skill_level_id"]) for c in detail["competences"]
    }
    assert senior_pairs == {(sr_comp.id, sr_sl.id)}


async def test_delete_required_spec_recomputes_competences(
    db: AsyncSession, tenant, user
) -> None:
    """REDO case 2.2: DELETE spec drops its derived competences."""
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="T", card_type="vacancy")
    )
    spec_a, grade_a, comp_a, sl_a = await _seed_pair_with_competence(
        db, tenant, grade_title="GA"
    )
    spec_b, grade_b, comp_b, sl_b = await _seed_pair_with_competence(
        db, tenant, grade_title="GB"
    )

    link_a = await service.add_required_specialization(
        db,
        tenant.id,
        card["id"],
        RequiredSpecializationCreate(
            specialization_id=spec_a.id, grade_id=grade_a.id
        ),
    )
    await service.add_required_specialization(
        db,
        tenant.id,
        card["id"],
        RequiredSpecializationCreate(
            specialization_id=spec_b.id, grade_id=grade_b.id
        ),
    )

    detail = await service.get_card_detail(db, tenant.id, card["id"])
    union_pairs = {
        (c["competence_id"], c["skill_level_id"]) for c in detail["competences"]
    }
    assert union_pairs == {(comp_a.id, sl_a.id), (comp_b.id, sl_b.id)}

    await service.delete_required_specialization(
        db, tenant.id, card["id"], link_a["id"]
    )
    detail = await service.get_card_detail(db, tenant.id, card["id"])
    remaining_pairs = {
        (c["competence_id"], c["skill_level_id"]) for c in detail["competences"]
    }
    assert remaining_pairs == {(comp_b.id, sl_b.id)}
