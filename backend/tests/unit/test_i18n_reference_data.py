"""i18n F5 (HRP-479): stable keys on origin reference data.

Origin rows (dictionary items, the default answer scale, scale levels)
expose a stable key the frontend resolves through the ``reference.*``
catalog; tenant-authored rows carry no key and render verbatim. These
tests pin the API surface (keys are read-only and reach the payloads)
and the backfill slugging of migration ``hrp479refdata01``.
"""

import uuid

from app.modules.assessment.answer_scale_service import (
    _load_scale_full,
    _scale_detail_dict,
    snapshot_scale_for_assessment,
)
from app.modules.assessment.models import (
    AnswerOption,
    AnswerScale,
    AnswerScaleLevel,
)
from app.modules.dictionary import service as dictionary_service
from app.modules.dictionary.models import DictionaryItem
from app.modules.dictionary.schemas import (
    DictionaryItemCreate,
    DictionaryItemUpdate,
)
from sqlalchemy import text


class TestDictionaryI18nKey:
    async def test_origin_item_exposes_i18n_key(self, db, tenant):
        # Unique title: the shared test DB keeps rows across tests, and a
        # look-alike origin "Junior" without a key (seeded elsewhere)
        # would shadow this row in the by-title lookup.
        db.add(
            DictionaryItem(
                type="grade",
                title="Origin Probe HRP479",
                i18n_key="origin_probe_hrp479",
                sort_index=0,
                tenant_id=None,
            )
        )
        await db.commit()

        items = await dictionary_service.list_items(db, tenant.id, "grade")
        by_title = {i["title"]: i for i in items}
        assert by_title["Origin Probe HRP479"]["i18n_key"] == "origin_probe_hrp479"

    async def test_tenant_item_has_no_i18n_key(self, db, tenant):
        created = await dictionary_service.create_item(
            db,
            tenant.id,
            "grade",
            DictionaryItemCreate(title="Guild Master"),
        )
        assert created["i18n_key"] is None

    def test_create_update_schemas_reject_i18n_key(self):
        # The key is system-owned: only seed migrations write it. If it
        # ever appears in the create/update schemas, clients could stamp
        # arbitrary catalog keys onto custom items.
        assert "i18n_key" not in DictionaryItemCreate.model_fields
        assert "i18n_key" not in DictionaryItemUpdate.model_fields

    def test_skill_level_schemas_reject_i18n_key(self):
        # Same invariant for skill levels — since F5 the key drives label
        # resolution, so a client-writable key would let a tenant admin
        # substitute a catalog string for their own title (review [F5]).
        from app.modules.competence.schemas import (
            SkillLevelCreate,
            SkillLevelRead,
            SkillLevelUpdate,
        )

        assert "i18n_key" not in SkillLevelCreate.model_fields
        assert "i18n_key" not in SkillLevelUpdate.model_fields
        assert "i18n_key" in SkillLevelRead.model_fields

    async def test_update_never_touches_i18n_key(self, db, tenant):
        created = await dictionary_service.create_item(
            db,
            tenant.id,
            "grade",
            DictionaryItemCreate(title="Archon"),
        )
        updated = await dictionary_service.update_item(
            db,
            tenant.id,
            uuid.UUID(str(created["id"])),
            DictionaryItemUpdate(title="Archon II"),
        )
        assert updated["i18n_key"] is None


class TestBackfillSlug:
    # Mirrors the UPDATE in migrations/versions/hrp479refdata01 — keep in
    # sync. Pins that the slug expression reproduces the catalog keys in
    # frontend/messages/en.json (reference.dictionary.*) for every seeded
    # origin title, and that tenant rows are left alone.
    BACKFILL_SQL = text(
        "UPDATE dictionary_items "
        "SET i18n_key = trim(both '_' from "
        "lower(regexp_replace(title, '[^a-zA-Z0-9]+', '_', 'g'))) "
        "WHERE tenant_id IS NULL AND i18n_key IS NULL"
    )

    SEEDED = {
        "grade": {
            "Junior": "junior",
            "Middle": "middle",
            "Senior": "senior",
            "Lead": "lead",
            "Principal": "principal",
        },
        "specialization": {
            "Backend Developer": "backend_developer",
            "Frontend Developer": "frontend_developer",
            "QA Engineer": "qa_engineer",
            "Product Manager": "product_manager",
            "Designer": "designer",
            "Data Scientist": "data_scientist",
            "DevOps Engineer": "devops_engineer",
        },
        "competence_type": {
            "Hard skill": "hard_skill",
            "Soft skill": "soft_skill",
            "Unique skill": "unique_skill",
        },
    }

    async def test_backfill_produces_catalog_slugs(self, db, tenant):
        for item_type, titles in self.SEEDED.items():
            for idx, title in enumerate(titles):
                db.add(
                    DictionaryItem(
                        type=item_type,
                        title=title,
                        sort_index=idx,
                        tenant_id=None,
                    )
                )
        tenant_item = DictionaryItem(
            type="grade", title="Backend Developer", sort_index=99, tenant_id=tenant.id
        )
        db.add(tenant_item)
        await db.commit()

        await db.execute(self.BACKFILL_SQL)
        await db.commit()

        for item_type, titles in self.SEEDED.items():
            items = await dictionary_service.list_items(db, tenant.id, item_type)
            keys = {i["title"]: i["i18n_key"] for i in items}
            for title, slug in titles.items():
                assert keys[title] == slug, (item_type, title)

        await db.refresh(tenant_item)
        assert tenant_item.i18n_key is None


class TestAnswerScaleI18nKey:
    async def _make_origin_scale(self, db) -> AnswerScale:
        # Deliberately NOT is_default=True: the partial unique index
        # allows a single default row and the shared test DB keeps state
        # across tests. Origin-ness (tenant_id NULL + i18n_key) is what
        # the assertions exercise.
        scale = AnswerScale(
            tenant_id=None,
            title="Standard 5-Point Scale",
            description="Default assessment scoring scale",
            i18n_key="standard_5point",
            is_default=False,
        )
        scale.options = [
            AnswerOption(
                title="N/A", code="na", weight=0, sort_index=0, is_neutral=True
            ),
            AnswerOption(
                title="Meets Expectations", code="meets", weight=2, sort_index=1
            ),
        ]
        scale.levels = [
            AnswerScaleLevel(
                percent_from=0,
                percent_to=100,
                system_code="fully_meets",
                system_title=None,
                sort_index=0,
            ),
        ]
        db.add(scale)
        await db.commit()
        # Reload with options/levels eagerly loaded — the ORM instance's
        # collections expire on commit and lazy loads raise in async.
        full = await _load_scale_full(db, scale.id)
        assert full is not None
        return full

    async def test_detail_dict_exposes_key_and_level_system_code(self, db):
        scale = await self._make_origin_scale(db)

        detail = await _scale_detail_dict(db, scale)
        assert detail["i18n_key"] == "standard_5point"
        # Regression: system_code used to be dropped here, collapsing
        # origin levels (system_title IS NULL) to an empty label.
        assert detail["levels"][0]["system_code"] == "fully_meets"
        assert detail["levels"][0]["system_title"] is None
        assert {o["code"] for o in detail["options"]} == {"na", "meets"}

    async def test_snapshot_carries_i18n_key_and_codes(
        self, db, tenant, employee, user, assessment_statuses, assessment_types
    ):
        from app.modules.assessment.models import Assessment

        scale = await self._make_origin_scale(db)
        assessment = Assessment(
            tenant_id=tenant.id,
            title="Snapshot probe",
            employee_id=employee.id,
            type_id=assessment_types["self"].id,
            status_id=assessment_statuses["draft"].id,
            initiator_id=user.id,
            scale_id=scale.id,
        )
        db.add(assessment)
        await db.commit()

        created = await snapshot_scale_for_assessment(db, assessment)
        assert created is not None
        await db.commit()

        copy = await _load_scale_full(db, created.id)
        assert copy is not None
        assert copy.is_snapshot is True
        assert copy.is_default is False
        # The flag flips on snapshots — the carried key is what keeps the
        # seeded scale localizable on finished assessments.
        assert copy.i18n_key == "standard_5point"
        assert {o.code for o in copy.options} == {"na", "meets"}
        assert copy.levels[0].system_code == "fully_meets"
