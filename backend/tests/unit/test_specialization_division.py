"""Tests for GF7: Specialization-Division Mapping."""

import uuid

import pytest
from app.modules.company import service as company_service
from app.modules.company.schemas import DivisionCreate, SpecializationDivisionCreate
from app.modules.dictionary.models import DictionaryItem
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class TestSpecializationDivision:
    async def _make_specialization(
        self, db: AsyncSession, tenant_id: uuid.UUID, title: str
    ) -> DictionaryItem:
        spec = DictionaryItem(
            type="specialization",
            title=title,
            tenant_id=tenant_id,
        )
        db.add(spec)
        await db.commit()
        await db.refresh(spec)
        return spec

    async def test_add_specialization(self, db: AsyncSession, tenant):
        div = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Engineering")
        )
        spec = await self._make_specialization(db, tenant.id, "Backend Developer")
        result = await company_service.add_division_specialization(
            db,
            tenant.id,
            div["id"],
            SpecializationDivisionCreate(specialization_id=spec.id),
        )
        assert result["division_id"] == div["id"]
        assert result["specialization_id"] == spec.id
        assert result["specialization_title"] == "Backend Developer"

    async def test_list_specializations(self, db: AsyncSession, tenant):
        div = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Product")
        )
        for title in ["Frontend", "Backend", "DevOps"]:
            spec = await self._make_specialization(db, tenant.id, title)
            await company_service.add_division_specialization(
                db,
                tenant.id,
                div["id"],
                SpecializationDivisionCreate(specialization_id=spec.id),
            )
        items = await company_service.list_division_specializations(
            db, tenant.id, div["id"]
        )
        assert len(items) == 3

    async def test_remove_specialization(self, db: AsyncSession, tenant):
        div = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="QA")
        )
        spec = await self._make_specialization(db, tenant.id, "Tester")
        await company_service.add_division_specialization(
            db,
            tenant.id,
            div["id"],
            SpecializationDivisionCreate(specialization_id=spec.id),
        )
        result = await company_service.remove_division_specialization(
            db, tenant.id, div["id"], spec.id
        )
        assert result["specialization_id"] == spec.id

        # Verify it's gone
        items = await company_service.list_division_specializations(
            db, tenant.id, div["id"]
        )
        assert len(items) == 0

    async def test_duplicate_mapping(self, db: AsyncSession, tenant):
        div = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Design")
        )
        spec = await self._make_specialization(db, tenant.id, "UI Designer")
        await company_service.add_division_specialization(
            db,
            tenant.id,
            div["id"],
            SpecializationDivisionCreate(specialization_id=spec.id),
        )
        with pytest.raises(HTTPException) as exc:
            await company_service.add_division_specialization(
                db,
                tenant.id,
                div["id"],
                SpecializationDivisionCreate(specialization_id=spec.id),
            )
        assert exc.value.status_code == 409

    async def test_invalid_specialization(self, db: AsyncSession, tenant):
        div = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Research")
        )
        with pytest.raises(HTTPException) as exc:
            await company_service.add_division_specialization(
                db,
                tenant.id,
                div["id"],
                SpecializationDivisionCreate(specialization_id=uuid.uuid4()),
            )
        assert exc.value.status_code == 400

    async def test_invalid_division(self, db: AsyncSession, tenant):
        spec = await self._make_specialization(db, tenant.id, "Analyst")
        with pytest.raises(HTTPException) as exc:
            await company_service.add_division_specialization(
                db,
                tenant.id,
                uuid.uuid4(),
                SpecializationDivisionCreate(specialization_id=spec.id),
            )
        assert exc.value.status_code == 404

    async def test_remove_nonexistent(self, db: AsyncSession, tenant):
        div = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Legal")
        )
        with pytest.raises(HTTPException) as exc:
            await company_service.remove_division_specialization(
                db, tenant.id, div["id"], uuid.uuid4()
            )
        assert exc.value.status_code == 404

    async def test_origin_specialization(self, db: AsyncSession, tenant):
        """Origin specializations (tenant_id=NULL) should be assignable."""
        spec = DictionaryItem(
            type="specialization",
            title="System Analyst",
            tenant_id=None,
        )
        db.add(spec)
        await db.commit()
        await db.refresh(spec)

        div = await company_service.create_division(
            db, tenant.id, DivisionCreate(name="Systems")
        )
        result = await company_service.add_division_specialization(
            db,
            tenant.id,
            div["id"],
            SpecializationDivisionCreate(specialization_id=spec.id),
        )
        assert result["specialization_title"] == "System Analyst"
