"""HRP-288: specialization grades carry the effective tenant-scoped
``grade_is_active`` so the spec detail page and matrix can render an
Inactive chip when the underlying dictionary grade has been
deactivated — either as a tenant-custom row (its own ``is_active``) or
as an origin row turned off via the HRP-285 override.
"""

from app.modules.dictionary import service as dict_service
from app.modules.dictionary.models import (
    DictionaryItem,
    DictionaryItemTenantOverride,
)
from app.modules.dictionary.schemas import (
    DictionaryItemCreate,
    DictionaryItemUpdate,
)
from app.modules.grade_system import service as grade_service
from app.modules.grade_system.schemas import GradeSpecializationCreate
from app.modules.specialization import service as spec_service


class TestHRP288InactiveChainExposure:
    async def _spec_id(self, db, tenant, title="HRP288 Spec"):
        return (
            await dict_service.create_item(
                db, tenant.id, "specialization", DictionaryItemCreate(title=title)
            )
        )["id"]

    async def test_custom_grade_active_default(self, db, tenant):
        spec_id = await self._spec_id(db, tenant)
        grade = await dict_service.create_item(
            db, tenant.id, "grade", DictionaryItemCreate(title="CustomActive")
        )
        await grade_service.create_chain(
            db,
            tenant.id,
            GradeSpecializationCreate(
                grade_id=grade["id"], specialization_id=spec_id
            ),
        )
        rows = await spec_service.get_grades_with_attrs(db, tenant.id, spec_id)
        assert rows[0]["grade_is_active"] is True

    async def test_deactivated_custom_grade_reflected(self, db, tenant):
        spec_id = await self._spec_id(db, tenant, title="HRP288 Spec 2")
        grade = await dict_service.create_item(
            db,
            tenant.id,
            "grade",
            DictionaryItemCreate(title="CustomGoesDormant"),
        )
        await grade_service.create_chain(
            db,
            tenant.id,
            GradeSpecializationCreate(
                grade_id=grade["id"], specialization_id=spec_id
            ),
        )
        await dict_service.update_item(
            db, tenant.id, grade["id"], DictionaryItemUpdate(is_active=False)
        )
        rows = await spec_service.get_grades_with_attrs(db, tenant.id, spec_id)
        assert rows[0]["grade_is_active"] is False

    async def test_origin_grade_override_reflected_per_tenant(
        self, db, tenant
    ):
        from app.modules.company.models import Tenant

        other = Tenant(
            name="Other HRP288 Co", slug="other-co-hrp288"
        )
        db.add(other)
        await db.commit()
        await db.refresh(other)

        # origin grade shared between tenants
        origin = DictionaryItem(
            type="grade", title="HRP288 Origin", tenant_id=None
        )
        db.add(origin)
        await db.commit()
        await db.refresh(origin)

        # spec + chain in tenant A
        spec_a = await self._spec_id(db, tenant, title="HRP288 SpecA")
        await grade_service.create_chain(
            db,
            tenant.id,
            GradeSpecializationCreate(
                grade_id=origin.id, specialization_id=spec_a
            ),
        )

        # spec + chain in tenant B (uses the same origin grade)
        spec_b = await self._spec_id(db, other, title="HRP288 SpecB")
        await grade_service.create_chain(
            db,
            other.id,
            GradeSpecializationCreate(
                grade_id=origin.id, specialization_id=spec_b
            ),
        )

        # tenant A deactivates the origin grade via override
        db.add(
            DictionaryItemTenantOverride(
                item_id=origin.id, tenant_id=tenant.id, is_active=False
            )
        )
        await db.commit()

        a_rows = await spec_service.get_grades_with_attrs(
            db, tenant.id, spec_a
        )
        b_rows = await spec_service.get_grades_with_attrs(
            db, other.id, spec_b
        )
        assert a_rows[0]["grade_is_active"] is False
        assert b_rows[0]["grade_is_active"] is True
