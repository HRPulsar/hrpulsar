"""HRP-293: grade options for the Development plan pickers.

``list_grades_for_specialization`` returns grades configured for the
specialization (any chain, competence links not required), minus grades
deactivated on the Dictionaries → Grades level (tenant-effective,
HRP-285/337); ``include_id`` keeps an already-saved grade selectable.
"""

import uuid

from app.modules.dictionary import service as dictionary_service
from app.modules.dictionary.models import DictionaryItem
from app.modules.dictionary.schemas import DictionaryItemUpdate
from app.modules.grade_system.models import GradeSpecialization
from app.modules.grade_system.service import list_grades_for_specialization


async def _make_item(db, item_type, title, tenant_id=None, is_active=True):
    item = DictionaryItem(
        type=item_type,
        title=title,
        sort_index=0,
        tenant_id=tenant_id,
        is_active=is_active,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _make_chain(db, tenant_id, specialization_id, grade_id):
    gs = GradeSpecialization(
        tenant_id=tenant_id,
        specialization_id=specialization_id,
        grade_id=grade_id,
    )
    db.add(gs)
    await db.commit()
    return gs


class TestHRP293GradesForSpecialization:
    async def test_only_chained_grades_returned(self, db, tenant):
        spec = await _make_item(db, "specialization", "HRP293 Spec A")
        chained = await _make_item(db, "grade", "HRP293 Chained")
        unchained = await _make_item(db, "grade", "HRP293 Unchained")
        await _make_chain(db, tenant.id, spec.id, chained.id)

        options = await list_grades_for_specialization(db, tenant.id, spec.id)
        ids = {o["id"] for o in options}
        assert chained.id in ids
        assert unchained.id not in ids

    async def test_chain_without_competence_links_qualifies(self, db, tenant):
        # The assessment criteria picker requires a competence link; the
        # Development picker must not — a bare chain is enough.
        spec = await _make_item(db, "specialization", "HRP293 Spec Bare")
        grade = await _make_item(db, "grade", "HRP293 Bare Grade")
        await _make_chain(db, tenant.id, spec.id, grade.id)

        options = await list_grades_for_specialization(db, tenant.id, spec.id)
        assert grade.id in {o["id"] for o in options}

    async def test_tenant_deactivated_grade_dropped(self, db, tenant):
        spec = await _make_item(db, "specialization", "HRP293 Spec Deact")
        kept = await _make_item(db, "grade", "HRP293 Kept")
        dropped = await _make_item(db, "grade", "HRP293 Dropped")
        await _make_chain(db, tenant.id, spec.id, kept.id)
        await _make_chain(db, tenant.id, spec.id, dropped.id)
        await dictionary_service.update_item(
            db, tenant.id, dropped.id, DictionaryItemUpdate(is_active=False)
        )

        options = await list_grades_for_specialization(db, tenant.id, spec.id)
        ids = {o["id"] for o in options}
        assert kept.id in ids
        assert dropped.id not in ids

        # The shared origin row itself stays untouched.
        await db.refresh(dropped)
        assert dropped.is_active is True

    async def test_include_id_keeps_saved_deactivated_grade(self, db, tenant):
        spec = await _make_item(db, "specialization", "HRP293 Spec Saved")
        saved = await _make_item(db, "grade", "HRP293 Saved Grade")
        await _make_chain(db, tenant.id, spec.id, saved.id)
        await dictionary_service.update_item(
            db, tenant.id, saved.id, DictionaryItemUpdate(is_active=False)
        )

        without = await list_grades_for_specialization(db, tenant.id, spec.id)
        assert saved.id not in {o["id"] for o in without}

        with_saved = await list_grades_for_specialization(
            db, tenant.id, spec.id, include_id=saved.id
        )
        assert saved.id in {o["id"] for o in with_saved}

    async def test_include_id_does_not_bypass_chain_filter(self, db, tenant):
        # include_id only rescues a chained-but-deactivated grade (HRP-292
        # semantics); an unchained grade is never returned — a legacy saved
        # value is injected client-side from the stored title instead.
        spec = await _make_item(db, "specialization", "HRP293 Spec Legacy")
        legacy = await _make_item(db, "grade", "HRP293 Legacy Grade")

        with_legacy = await list_grades_for_specialization(
            db, tenant.id, spec.id, include_id=legacy.id
        )
        assert legacy.id not in {o["id"] for o in with_legacy}

    async def test_other_tenant_chains_excluded(self, db, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(
            name=f"Other Co HRP293 {uuid.uuid4().hex[:6]}",
            slug=f"other-hrp293-{uuid.uuid4().hex[:8]}",
        )
        db.add(other)
        await db.commit()
        await db.refresh(other)

        spec = await _make_item(db, "specialization", "HRP293 Spec Foreign")
        foreign_grade = await _make_item(db, "grade", "HRP293 Foreign Grade")
        await _make_chain(db, other.id, spec.id, foreign_grade.id)

        options = await list_grades_for_specialization(db, tenant.id, spec.id)
        assert foreign_grade.id not in {o["id"] for o in options}

    async def test_other_specialization_chains_excluded(self, db, tenant):
        spec_a = await _make_item(db, "specialization", "HRP293 Spec X")
        spec_b = await _make_item(db, "specialization", "HRP293 Spec Y")
        grade_b = await _make_item(db, "grade", "HRP293 Grade Of Y")
        await _make_chain(db, tenant.id, spec_b.id, grade_b.id)

        options = await list_grades_for_specialization(db, tenant.id, spec_a.id)
        assert grade_b.id not in {o["id"] for o in options}
