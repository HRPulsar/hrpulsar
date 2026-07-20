"""Tests for GF10: Company Profile & Activity Fields."""

import uuid

import pytest
from app.modules.company import service
from app.modules.company.schemas import CompanyProfileUpdate
from app.modules.dictionary.models import DictionaryItem
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class TestCompanyProfile:
    async def test_get_profile(self, db: AsyncSession, tenant):
        result = await service.get_company_profile(db, tenant.id)
        assert result["id"] == tenant.id
        assert result["name"] == tenant.name
        assert result["industry"] is None
        assert result["company_size"] is None
        assert result["website"] is None
        assert result["description"] is None
        assert result["activity_fields"] == []

    async def test_update_profile(self, db: AsyncSession, tenant):
        data = CompanyProfileUpdate(
            industry="Technology",
            company_size="51-200",
            website="https://example.com",
            description="A great company",
        )
        result = await service.update_company_profile(db, tenant.id, data)
        assert result["industry"] == "Technology"
        assert result["company_size"] == "51-200"
        assert result["website"] == "https://example.com"
        assert result["description"] == "A great company"

    async def test_update_profile_partial(self, db: AsyncSession, tenant):
        data = CompanyProfileUpdate(industry="Finance")
        result = await service.update_company_profile(db, tenant.id, data)
        assert result["industry"] == "Finance"
        assert result["website"] is None  # unchanged

    async def test_add_activity_field(self, db: AsyncSession, tenant):
        # Create an activity_field dictionary item
        item = DictionaryItem(
            title="Information Technology",
            type="activity_field",
            tenant_id=None,  # origin
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)

        result = await service.add_activity_field(db, tenant.id, item.id)
        assert result["activity_field_id"] == item.id
        assert result["title"] == "Information Technology"
        assert result["tenant_id"] == tenant.id

    async def test_add_activity_field_duplicate(self, db: AsyncSession, tenant):
        item = DictionaryItem(title="Healthcare", type="activity_field", tenant_id=None)
        db.add(item)
        await db.commit()
        await db.refresh(item)

        await service.add_activity_field(db, tenant.id, item.id)
        with pytest.raises(HTTPException) as exc:
            await service.add_activity_field(db, tenant.id, item.id)
        assert exc.value.status_code == 409

    async def test_add_activity_field_invalid_type(self, db: AsyncSession, tenant):
        item = DictionaryItem(title="Backend", type="specialization", tenant_id=None)
        db.add(item)
        await db.commit()
        await db.refresh(item)

        with pytest.raises(HTTPException) as exc:
            await service.add_activity_field(db, tenant.id, item.id)
        assert exc.value.status_code == 400

    async def test_remove_activity_field(self, db: AsyncSession, tenant):
        item = DictionaryItem(title="Education", type="activity_field", tenant_id=None)
        db.add(item)
        await db.commit()
        await db.refresh(item)

        await service.add_activity_field(db, tenant.id, item.id)
        result = await service.remove_activity_field(db, tenant.id, item.id)
        assert result["activity_field_id"] == item.id

        # Should be gone now
        with pytest.raises(HTTPException) as exc:
            await service.remove_activity_field(db, tenant.id, item.id)
        assert exc.value.status_code == 404

    async def test_profile_includes_activity_fields(self, db: AsyncSession, tenant):
        item1 = DictionaryItem(title="Tech", type="activity_field", tenant_id=None)
        item2 = DictionaryItem(title="Finance", type="activity_field", tenant_id=None)
        db.add_all([item1, item2])
        await db.commit()

        await service.add_activity_field(db, tenant.id, item1.id)
        await service.add_activity_field(db, tenant.id, item2.id)

        profile = await service.get_company_profile(db, tenant.id)
        assert len(profile["activity_fields"]) == 2
        titles = {af["title"] for af in profile["activity_fields"]}
        assert titles == {"Tech", "Finance"}

    async def test_tenant_isolation(self, db: AsyncSession, tenant):
        """Activity field from another tenant's custom item should be rejected."""
        from app.modules.company.models import Tenant

        other = Tenant(name="Other Corp", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.commit()
        await db.refresh(other)

        item = DictionaryItem(
            title="Custom Field", type="activity_field", tenant_id=other.id
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)

        with pytest.raises(HTTPException) as exc:
            await service.add_activity_field(db, tenant.id, item.id)
        assert exc.value.status_code == 400
