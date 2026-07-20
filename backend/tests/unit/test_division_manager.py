"""Tests for GF6: Division Manager."""

import uuid

import pytest
from app.modules.company import service as company_service
from app.modules.company.schemas import DivisionCreate, DivisionUpdate
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class TestDivisionManager:
    async def test_create_division_with_manager(
        self, db: AsyncSession, employee, tenant
    ):
        data = DivisionCreate(name="Engineering", manager_id=employee.id)
        result = await company_service.create_division(db, tenant.id, data)
        assert result["name"] == "Engineering"
        assert result["manager_id"] == employee.id
        assert result["manager_name"] is not None

    async def test_create_division_without_manager(self, db: AsyncSession, tenant):
        data = DivisionCreate(name="Marketing")
        result = await company_service.create_division(db, tenant.id, data)
        assert result["manager_id"] is None
        assert result["manager_name"] is None

    async def test_set_manager(self, db: AsyncSession, employee, tenant):
        data = DivisionCreate(name="Sales")
        created = await company_service.create_division(db, tenant.id, data)
        updated = await company_service.update_division(
            db,
            tenant.id,
            created["id"],
            DivisionUpdate(manager_id=employee.id),
        )
        assert updated["manager_id"] == employee.id
        assert updated["manager_name"] is not None

    async def test_clear_manager(self, db: AsyncSession, employee, tenant):
        data = DivisionCreate(name="HR", manager_id=employee.id)
        created = await company_service.create_division(db, tenant.id, data)
        updated = await company_service.update_division(
            db,
            tenant.id,
            created["id"],
            DivisionUpdate(manager_id=None),
        )
        assert updated["manager_id"] is None
        assert updated["manager_name"] is None

    async def test_invalid_manager(self, db: AsyncSession, tenant):
        data = DivisionCreate(name="Ghost Division", manager_id=uuid.uuid4())
        with pytest.raises(HTTPException) as exc:
            await company_service.create_division(db, tenant.id, data)
        assert exc.value.status_code == 400

    async def test_manager_in_tree(self, db: AsyncSession, employee, tenant):
        data = DivisionCreate(name="Dev", manager_id=employee.id)
        await company_service.create_division(db, tenant.id, data)
        tree = await company_service.get_division_tree(db, tenant.id)
        dev_nodes = [n for n in tree if n.name == "Dev"]
        assert len(dev_nodes) == 1
        assert dev_nodes[0].manager_id == employee.id
        assert dev_nodes[0].manager_name is not None

    async def test_get_division_with_manager(self, db: AsyncSession, employee, tenant):
        data = DivisionCreate(name="Support", manager_id=employee.id)
        created = await company_service.create_division(db, tenant.id, data)
        result = await company_service.get_division(db, tenant.id, created["id"])
        assert result["manager_id"] == employee.id
        assert result["manager_name"] is not None
