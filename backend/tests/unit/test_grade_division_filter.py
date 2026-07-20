"""Tests for GF7: Grade chains filtered by division specializations."""

from app.modules.company.models import Division, SpecializationDivision
from app.modules.dictionary.models import DictionaryItem
from app.modules.grade_system import service as grade_service
from app.modules.grade_system.models import GradeSpecialization
from sqlalchemy.ext.asyncio import AsyncSession


class TestGradeChainsByDivision:
    async def _setup(self, db, tenant):
        """Create specializations, a division, and grade chains."""
        # Specializations
        spec1 = DictionaryItem(
            type="specialization", title="Backend", tenant_id=tenant.id
        )
        spec2 = DictionaryItem(
            type="specialization", title="Frontend", tenant_id=tenant.id
        )
        grade1 = DictionaryItem(type="grade", title="Junior", tenant_id=tenant.id)
        grade2 = DictionaryItem(type="grade", title="Senior", tenant_id=tenant.id)
        db.add_all([spec1, spec2, grade1, grade2])
        await db.flush()

        # Division
        div = Division(tenant_id=tenant.id, name="Engineering")
        db.add(div)
        await db.flush()

        # Assign only spec1 to division
        db.add(
            SpecializationDivision(
                tenant_id=tenant.id,
                division_id=div.id,
                specialization_id=spec1.id,
            )
        )
        await db.flush()

        # Grade chains for both specializations
        gs1 = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade1.id,
            specialization_id=spec1.id,
            sort_index=0,
        )
        gs2 = GradeSpecialization(
            tenant_id=tenant.id,
            grade_id=grade2.id,
            specialization_id=spec2.id,
            sort_index=0,
        )
        db.add_all([gs1, gs2])
        await db.commit()
        return div, spec1, spec2

    async def test_returns_only_division_specialization_chains(
        self, db: AsyncSession, tenant
    ):
        div, spec1, spec2 = await self._setup(db, tenant)

        chains = await grade_service.list_by_division(db, tenant.id, div.id)
        assert len(chains) == 1
        assert chains[0]["specialization_id"] == spec1.id

    async def test_empty_when_no_specializations(self, db: AsyncSession, tenant):
        div = Division(tenant_id=tenant.id, name="Empty Div")
        db.add(div)
        await db.commit()

        chains = await grade_service.list_by_division(db, tenant.id, div.id)
        assert chains == []
