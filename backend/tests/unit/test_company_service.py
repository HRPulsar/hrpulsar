import uuid

import pytest
from app.modules.company import service
from app.modules.company.schemas import DivisionCreate, DivisionUpdate, TenantUpdate
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class TestTenant:
    async def test_get_tenant(self, db: AsyncSession, tenant):
        result = await service.get_tenant(db, tenant.id)
        assert result.name == tenant.name

    async def test_get_tenant_not_found(self, db: AsyncSession):
        with pytest.raises(Exception) as exc:
            await service.get_tenant(db, uuid.uuid4())
        assert "404" in str(exc.value.status_code)

    async def test_update_tenant(self, db: AsyncSession, tenant):
        data = TenantUpdate(name="Updated Corp")
        result = await service.update_tenant(db, tenant.id, data)
        assert result.name == "Updated Corp"


class TestDivisions:
    async def test_create_division(self, db: AsyncSession, tenant):
        data = DivisionCreate(name="Engineering", description="Engineering dept")
        div = await service.create_division(db, tenant.id, data)
        assert div["name"] == "Engineering"
        assert div["tenant_id"] == tenant.id

    async def test_create_child_division(self, db: AsyncSession, tenant):
        parent_data = DivisionCreate(name="Engineering")
        parent = await service.create_division(db, tenant.id, parent_data)

        child_data = DivisionCreate(name="Backend", parent_id=parent["id"])
        child = await service.create_division(db, tenant.id, child_data)
        assert child["parent_id"] == parent["id"]

    async def test_get_division(self, db: AsyncSession, tenant):
        data = DivisionCreate(name="HR")
        div = await service.create_division(db, tenant.id, data)
        result = await service.get_division(db, tenant.id, div["id"])
        assert result["name"] == "HR"

    async def test_get_division_wrong_tenant(self, db: AsyncSession, tenant):
        data = DivisionCreate(name="Secret")
        div = await service.create_division(db, tenant.id, data)

        with pytest.raises(Exception) as exc:
            await service.get_division(db, uuid.uuid4(), div["id"])
        assert "404" in str(exc.value.status_code)

    async def test_get_division_tree(self, db: AsyncSession, tenant):
        parent = await service.create_division(
            db, tenant.id, DivisionCreate(name="Root")
        )
        await service.create_division(
            db, tenant.id, DivisionCreate(name="Child", parent_id=parent["id"])
        )

        tree = await service.get_division_tree(db, tenant.id)
        assert len(tree) >= 1
        root = next((t for t in tree if t.name == "Root"), None)
        assert root is not None
        assert len(root.children) == 1
        assert root.children[0].name == "Child"

    async def test_update_division(self, db: AsyncSession, tenant):
        div = await service.create_division(db, tenant.id, DivisionCreate(name="Old"))
        result = await service.update_division(
            db, tenant.id, div["id"], DivisionUpdate(name="New")
        )
        assert result["name"] == "New"

    async def test_delete_division(self, db: AsyncSession, tenant):
        div = await service.create_division(
            db, tenant.id, DivisionCreate(name="ToDelete")
        )
        await service.delete_division(db, tenant.id, div["id"])

        with pytest.raises(HTTPException):
            await service.get_division(db, tenant.id, div["id"])
