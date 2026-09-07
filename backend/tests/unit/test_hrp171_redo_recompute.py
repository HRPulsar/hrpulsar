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

HRP-709 covers the third case: the (spec, grade) pair left the grade
ladder before the card's spec row was deleted, so there are no keys to
delete by and the helper has to diff the whole set instead.
"""

from __future__ import annotations

import uuid

from app.modules.competence.models import Competence, CompetenceGroup, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system.models import (
    GradeCompetenceLink,
    GradeSpecialization,
)
from app.modules.position.models import Position
from app.modules.talent_market import service
from app.modules.talent_market.models import TalentCandidate, TalentCardCompetence
from app.modules.talent_market.schemas import (
    RequiredSpecializationCreate,
    RequiredSpecializationUpdate,
    TalentCardCreate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_hrp129_auto_match import _add_done_assessment


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
        RequiredSpecializationCreate(specialization_id=spec_a.id, grade_id=grade_a.id),
    )
    await service.add_required_specialization(
        db,
        tenant.id,
        card["id"],
        RequiredSpecializationCreate(specialization_id=spec_b.id, grade_id=grade_b.id),
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


async def _link_pair_to_competence(
    db: AsyncSession,
    tenant,
    spec: DictionaryItem,
    grade: DictionaryItem,
    comp: Competence,
    sl: SkillLevel,
) -> None:
    """Add one more competence link to an already configured pair."""
    gs = (
        await db.execute(
            select(GradeSpecialization).where(
                GradeSpecialization.tenant_id == tenant.id,
                GradeSpecialization.specialization_id == spec.id,
                GradeSpecialization.grade_id == grade.id,
            )
        )
    ).scalar_one()
    db.add(
        GradeCompetenceLink(
            grade_specialization_id=gs.id,
            competence_id=comp.id,
            skill_level_id=sl.id,
        )
    )
    await db.commit()


async def _drop_pair_from_ladder(
    db: AsyncSession, tenant, spec: DictionaryItem, grade: DictionaryItem
) -> None:
    """Remove the (spec, grade) pair from the grade ladder entirely."""
    gs = (
        await db.execute(
            select(GradeSpecialization).where(
                GradeSpecialization.tenant_id == tenant.id,
                GradeSpecialization.specialization_id == spec.id,
                GradeSpecialization.grade_id == grade.id,
            )
        )
    ).scalar_one()
    links = (
        (
            await db.execute(
                select(GradeCompetenceLink).where(
                    GradeCompetenceLink.grade_specialization_id == gs.id
                )
            )
        )
        .scalars()
        .all()
    )
    for link in links:
        await db.delete(link)
    await db.delete(gs)
    await db.commit()


async def _pool_employee_ids(db: AsyncSession, card_id) -> list:
    rows = (
        (
            await db.execute(
                select(TalentCandidate).where(TalentCandidate.card_id == card_id)
            )
        )
        .scalars()
        .all()
    )
    return [r.employee_id for r in rows]


async def test_delete_spec_clears_competences_of_a_pair_gone_from_the_ladder(
    db: AsyncSession, tenant, user, employee
) -> None:
    """HRP-709: the ladder can lose the pair before the card does.

    The targeted delete (HRP-683) deletes by the keys the dropped pair
    implies, and a pair removed from the ladder implies nothing — its
    derived rows used to stay on the card, invisible in the UI but still
    gating the matcher. A competence two pairs imply still survives.
    """
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="T", card_type="vacancy")
    )
    spec_a, grade_a, comp_a, sl_a = await _seed_pair_with_competence(
        db, tenant, grade_title="GA"
    )
    spec_b, grade_b, shared_comp, shared_sl = await _seed_pair_with_competence(
        db, tenant, grade_title="GB"
    )
    # The shared row is implied by both pairs — it must outlive the diff.
    await _link_pair_to_competence(db, tenant, spec_a, grade_a, shared_comp, shared_sl)

    link_a = await service.add_required_specialization(
        db,
        tenant.id,
        card["id"],
        RequiredSpecializationCreate(specialization_id=spec_a.id, grade_id=grade_a.id),
    )
    await service.add_required_specialization(
        db,
        tenant.id,
        card["id"],
        RequiredSpecializationCreate(specialization_id=spec_b.id, grade_id=grade_b.id),
    )
    detail = await service.get_card_detail(db, tenant.id, card["id"])
    assert {
        (c["competence_id"], c["skill_level_id"]) for c in detail["competences"]
    } == {
        (comp_a.id, sl_a.id),
        (shared_comp.id, shared_sl.id),
    }

    # The employee clears spec B by current position and is assessed on the
    # shared competence only. Against both rows they average 45% and stay
    # out of the pool; against the shared row alone they score 90% and pool
    # in — so the pool proves the stale row really left the card.
    position = await db.get(Position, employee.position_id)
    assert position is not None
    position.specialization_id = spec_b.id
    position.grade_id = grade_b.id
    await db.commit()
    await _add_done_assessment(
        db,
        tenant.id,
        employee.id,
        user.id,
        shared_comp.id,
        shared_sl.id,
        90,
    )
    await service.recompute_card_candidates(db, tenant.id, card["id"])
    assert await _pool_employee_ids(db, card["id"]) == []

    await _drop_pair_from_ladder(db, tenant, spec_a, grade_a)

    await service.delete_required_specialization(
        db, tenant.id, card["id"], link_a["id"]
    )

    detail = await service.get_card_detail(db, tenant.id, card["id"])
    assert {
        (c["competence_id"], c["skill_level_id"]) for c in detail["competences"]
    } == {
        (shared_comp.id, shared_sl.id),
    }
    assert await _pool_employee_ids(db, card["id"]) == [employee.id]


async def test_hand_added_competence_survives_a_pair_that_still_resolves(
    db: AsyncSession, tenant, user
) -> None:
    """HRP-683 stays intact: the fallback is only for the unresolvable pair.

    While the dropped pair still resolves, the delete stays targeted and
    a competence nobody derived (typed by hand, or copied off a vacancy)
    keeps its place on the card.
    """
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="T", card_type="vacancy")
    )
    spec_a, grade_a, comp_a, sl_a = await _seed_pair_with_competence(
        db, tenant, grade_title="GA"
    )
    spec_b, grade_b, comp_b, sl_b = await _seed_pair_with_competence(
        db, tenant, grade_title="GB"
    )
    _, _, loose_comp, loose_sl = await _seed_pair_with_competence(
        db, tenant, grade_title="GC"
    )

    link_a = await service.add_required_specialization(
        db,
        tenant.id,
        card["id"],
        RequiredSpecializationCreate(specialization_id=spec_a.id, grade_id=grade_a.id),
    )
    await service.add_required_specialization(
        db,
        tenant.id,
        card["id"],
        RequiredSpecializationCreate(specialization_id=spec_b.id, grade_id=grade_b.id),
    )
    db.add(
        TalentCardCompetence(
            card_id=card["id"],
            competence_id=loose_comp.id,
            skill_level_id=loose_sl.id,
        )
    )
    await db.commit()

    await service.delete_required_specialization(
        db, tenant.id, card["id"], link_a["id"]
    )

    detail = await service.get_card_detail(db, tenant.id, card["id"])
    assert {
        (c["competence_id"], c["skill_level_id"]) for c in detail["competences"]
    } == {
        (comp_b.id, sl_b.id),
        (loose_comp.id, loose_sl.id),
    }


async def test_pair_with_no_competence_links_keeps_the_targeted_delete(
    db: AsyncSession, tenant, user
) -> None:
    """HRP-709 review: a pair on the ladder with no links is not a gone pair.

    ``grade_system`` happily creates a (spec, grade) pair with an empty
    competence list, and such a pair implies nothing — same empty answer
    the helper used to give for a pair that had left the ladder entirely.
    Only the second case may fall back to the full diff; here the targeted
    delete stands and a row nobody derived stays on the card.
    """
    card = await service.create_card(
        db, tenant.id, user.id, TalentCardCreate(title="T", card_type="vacancy")
    )
    spec_a, grade_a, _, _ = await _seed_pair_with_competence(
        db, tenant, grade_title="GA"
    )
    _, _, loose_comp, loose_sl = await _seed_pair_with_competence(
        db, tenant, grade_title="GB"
    )
    # Strip pair A's links: the pair stays configured, it just implies nothing.
    gs = (
        await db.execute(
            select(GradeSpecialization).where(
                GradeSpecialization.tenant_id == tenant.id,
                GradeSpecialization.specialization_id == spec_a.id,
                GradeSpecialization.grade_id == grade_a.id,
            )
        )
    ).scalar_one()
    for link in (
        (
            await db.execute(
                select(GradeCompetenceLink).where(
                    GradeCompetenceLink.grade_specialization_id == gs.id
                )
            )
        )
        .scalars()
        .all()
    ):
        await db.delete(link)
    await db.commit()

    link_a = await service.add_required_specialization(
        db,
        tenant.id,
        card["id"],
        RequiredSpecializationCreate(specialization_id=spec_a.id, grade_id=grade_a.id),
    )
    db.add(
        TalentCardCompetence(
            card_id=card["id"],
            competence_id=loose_comp.id,
            skill_level_id=loose_sl.id,
        )
    )
    await db.commit()

    await service.delete_required_specialization(
        db, tenant.id, card["id"], link_a["id"]
    )

    detail = await service.get_card_detail(db, tenant.id, card["id"])
    assert {
        (c["competence_id"], c["skill_level_id"]) for c in detail["competences"]
    } == {
        (loose_comp.id, loose_sl.id),
    }
