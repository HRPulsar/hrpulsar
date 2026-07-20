"""HRP-337: tenant deactivation of System (origin) dictionary items must be
respected everywhere ``is_active`` is read for a tenant — not only on the
Dictionaries page. ``effective_is_active_expr`` folds the per-tenant
override into SQL filters; ``origin_active_overrides`` does the same for
already-loaded rows (Specializations list/detail).
"""

from app.modules.assessment import service as assessment_service
from app.modules.company.models import Tenant
from app.modules.dictionary import service as dictionary_service
from app.modules.dictionary.models import DictionaryItem
from app.modules.dictionary.schemas import DictionaryItemUpdate
from app.modules.dictionary.service import effective_is_active_expr
from app.modules.specialization import service as specialization_service
from sqlalchemy import select


async def _make_origin_spec(db, title):
    item = DictionaryItem(
        type="specialization", title=title, sort_index=0, tenant_id=None
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _deactivate_for_tenant(db, tenant_id, item_id):
    await dictionary_service.update_item(
        db, tenant_id, item_id, DictionaryItemUpdate(is_active=False)
    )


class TestHRP337EffectiveActiveExpr:
    async def test_expression_folds_override_into_filter(self, db, tenant):
        origin_kept = await _make_origin_spec(db, "HRP337 Origin Kept")
        origin_dropped = await _make_origin_spec(db, "HRP337 Origin Dropped")
        custom = DictionaryItem(
            type="specialization",
            title="HRP337 Custom",
            sort_index=0,
            tenant_id=tenant.id,
        )
        db.add(custom)
        await db.commit()
        await db.refresh(custom)

        await _deactivate_for_tenant(db, tenant.id, origin_dropped.id)

        rows = await db.execute(
            select(DictionaryItem.id).where(
                DictionaryItem.type == "specialization",
                effective_is_active_expr(tenant.id).is_(True),
                (DictionaryItem.tenant_id == tenant.id)
                | DictionaryItem.tenant_id.is_(None),
            )
        )
        ids = {row for (row,) in rows.all()}
        assert origin_kept.id in ids
        assert custom.id in ids
        assert origin_dropped.id not in ids

    async def test_override_scoped_to_its_tenant(self, db, tenant):
        other = Tenant(name="Other Co HRP337", slug="other-co-hrp337")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        origin = await _make_origin_spec(db, "HRP337 Origin Scoped")
        await _deactivate_for_tenant(db, tenant.id, origin.id)

        for tid, expected in ((tenant.id, False), (other.id, True)):
            rows = await db.execute(
                select(DictionaryItem.id).where(
                    DictionaryItem.type == "specialization",
                    effective_is_active_expr(tid).is_(True),
                )
            )
            ids = {row for (row,) in rows.all()}
            assert (origin.id in ids) is expected


class TestHRP337EffectiveActiveDirections:
    async def test_override_true_resurrects_globally_inactive_origin(self, db, tenant):
        # Mirrors the Dictionaries page: a tenant's explicit override wins
        # over the origin flag in BOTH directions, including reactivating
        # an item that is globally inactive.
        origin = DictionaryItem(
            type="specialization",
            title="HRP337 Globally Off",
            sort_index=0,
            tenant_id=None,
            is_active=False,
        )
        db.add(origin)
        await db.commit()
        await db.refresh(origin)

        await dictionary_service.update_item(
            db, tenant.id, origin.id, DictionaryItemUpdate(is_active=True)
        )

        rows = await db.execute(
            select(DictionaryItem.id).where(
                DictionaryItem.type == "specialization",
                effective_is_active_expr(tenant.id).is_(True),
            )
        )
        assert origin.id in {row for (row,) in rows.all()}


class TestHRP337ConsumerSweep:
    async def test_join_shaped_consumer_respects_override(self, db, tenant):
        """Pin the correlated subquery inside a join-shaped query — the
        ai_materials linked-specializations resolver joins DictionaryItem
        through GradeSpecialization/GradeCompetenceLink."""
        from app.modules.competence.ai_materials import (
            _resolve_linked_specialization_ids,
        )
        from app.modules.competence.models import (
            Competence,
            CompetenceGroup,
            SkillLevel,
        )
        from app.modules.grade_system.models import (
            GradeCompetenceLink,
            GradeSpecialization,
        )

        origin = await _make_origin_spec(db, "HRP337 Join Spec")
        grade = DictionaryItem(
            type="grade", title="HRP337 Grade", sort_index=0, tenant_id=tenant.id
        )
        group = CompetenceGroup(
            title="HRP337 Group", tenant_id=tenant.id, sort_index=0, is_active=True
        )
        db.add_all([grade, group])
        await db.flush()
        comp = Competence(
            title="HRP337 Competence",
            tenant_id=tenant.id,
            group_id=group.id,
            is_active=True,
        )
        level = SkillLevel(title="HRP337 Basic", sort_index=0, tenant_id=None)
        db.add_all([comp, level])
        await db.flush()
        gs = GradeSpecialization(
            tenant_id=tenant.id, specialization_id=origin.id, grade_id=grade.id
        )
        db.add(gs)
        await db.flush()
        db.add(
            GradeCompetenceLink(
                grade_specialization_id=gs.id,
                competence_id=comp.id,
                skill_level_id=level.id,
            )
        )
        await db.commit()

        linked = await _resolve_linked_specialization_ids(
            db, tenant_id=tenant.id, competence_id=comp.id
        )
        assert origin.id in linked

        await _deactivate_for_tenant(db, tenant.id, origin.id)
        linked_after = await _resolve_linked_specialization_ids(
            db, tenant_id=tenant.id, competence_id=comp.id
        )
        assert origin.id not in linked_after

    async def test_criteria_picker_hides_tenant_deactivated_origin(self, db, tenant):
        origin = await _make_origin_spec(db, "HRP337 Criteria Spec")
        await _deactivate_for_tenant(db, tenant.id, origin.id)

        items = await assessment_service.list_criteria_specializations(db, tenant.id)
        assert origin.id not in {i["id"] for i in items}

    async def test_specializations_list_shows_effective_flag(self, db, tenant):
        origin = await _make_origin_spec(db, "HRP337 Page Spec")
        await _deactivate_for_tenant(db, tenant.id, origin.id)

        listed = await specialization_service.list_specializations(db, tenant.id)
        row = next(i for i in listed if i["id"] == origin.id)
        assert row["is_active"] is False

        detail = await specialization_service.get_specialization_detail(
            db, tenant.id, origin.id
        )
        assert detail["is_active"] is False

        # The shared origin row itself stays untouched.
        await db.refresh(origin)
        assert origin.is_active is True
