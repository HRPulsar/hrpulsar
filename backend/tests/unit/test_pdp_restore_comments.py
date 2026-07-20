"""Tests for GF12: PDP version restore + material-level comments."""

import uuid

import pytest
from app.modules.assessment import pdp_service
from app.modules.assessment.schemas import (
    PDPCommentCreate,
    PDPCreate,
    PDPItemCreate,
    PDPMaterialCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class TestPDPRestore:
    async def _create_pdp_with_items(self, db, tenant, user, employee):
        data = PDPCreate(title="Plan", employee_id=employee.id)
        pdp = await pdp_service.create_pdp(db, tenant.id, user.id, data)

        item = await pdp_service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Task A")
        )
        await pdp_service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(
                title="Article", format="web", link="https://example.com"
            ),
        )

        # Create version
        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "sent")

        # Modify PDP (add another item)
        await pdp_service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Task B")
        )

        return pdp

    async def test_restore_from_version(self, db: AsyncSession, tenant, user, employee):
        pdp = await self._create_pdp_with_items(db, tenant, user, employee)

        # Before restore: 2 items
        detail = await pdp_service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert len(detail["items"]) == 2

        # Get version (should have 1 item)
        versions = await pdp_service.list_versions(db, tenant.id, pdp["id"])
        assert len(versions) == 1

        # Restore
        restored = await pdp_service.restore_version(
            db, tenant.id, pdp["id"], versions[0]["id"]
        )
        assert len(restored["items"]) == 1
        assert restored["items"][0]["title"] == "Task A"
        assert len(restored["items"][0]["materials"]) == 1
        assert restored["items"][0]["materials"][0]["title"] == "Article"

    async def test_restore_preserves_progress(
        self, db: AsyncSession, tenant, user, employee
    ):
        data = PDPCreate(title="Plan", employee_id=employee.id)
        pdp = await pdp_service.create_pdp(db, tenant.id, user.id, data)

        item = await pdp_service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Done")
        )
        await pdp_service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Mat", link="https://example.com"),
        )
        # HRP-13/HRP-20: marking is now status-gated. Toggle is_passed
        # directly so this test keeps measuring snapshot fidelity rather
        # than the transition machinery.
        from app.modules.assessment.models import PDPItem

        item_obj = await db.get(PDPItem, item["id"])
        assert item_obj is not None
        item_obj.is_passed = True
        await db.commit()
        await pdp_service._recompute_progress(db, pdp["id"])
        await db.commit()

        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "sent")

        versions = await pdp_service.list_versions(db, tenant.id, pdp["id"])
        restored = await pdp_service.restore_version(
            db, tenant.id, pdp["id"], versions[0]["id"]
        )
        assert restored["total_progress"] == 100
        assert restored["items"][0]["is_passed"] is True

    async def test_restore_invalid_version(
        self, db: AsyncSession, tenant, user, employee
    ):
        data = PDPCreate(title="Plan", employee_id=employee.id)
        pdp = await pdp_service.create_pdp(db, tenant.id, user.id, data)

        with pytest.raises(HTTPException) as exc:
            await pdp_service.restore_version(db, tenant.id, pdp["id"], uuid.uuid4())
        assert exc.value.status_code == 404


class TestMaterialLevelComments:
    async def test_comment_on_material(self, db: AsyncSession, tenant, user, employee):
        data = PDPCreate(title="Plan", employee_id=employee.id)
        pdp = await pdp_service.create_pdp(db, tenant.id, user.id, data)

        item = await pdp_service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Item 1")
        )
        mat = await pdp_service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Video Lecture"),
        )

        comment_data = PDPCommentCreate(
            item_id=item["id"],
            material_id=mat["id"],
            text="Good material",
        )
        comment = await pdp_service.add_comment(
            db, tenant.id, pdp["id"], user.id, comment_data
        )
        assert comment["material_id"] == mat["id"]
        assert comment["item_id"] == item["id"]
        assert comment["text"] == "Good material"

    async def test_comment_without_material(
        self, db: AsyncSession, tenant, user, employee
    ):
        """Regular item-level comment still works."""
        data = PDPCreate(title="Plan", employee_id=employee.id)
        pdp = await pdp_service.create_pdp(db, tenant.id, user.id, data)

        item = await pdp_service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Item")
        )
        comment_data = PDPCommentCreate(item_id=item["id"], text="Good")
        comment = await pdp_service.add_comment(
            db, tenant.id, pdp["id"], user.id, comment_data
        )
        assert comment["material_id"] is None
        assert comment["item_id"] == item["id"]

    async def test_material_comment_in_detail(
        self, db: AsyncSession, tenant, user, employee
    ):
        """material_id appears in PDP detail view."""
        data = PDPCreate(title="Plan", employee_id=employee.id)
        pdp = await pdp_service.create_pdp(db, tenant.id, user.id, data)

        item = await pdp_service.add_item(
            db, tenant.id, pdp["id"], PDPItemCreate(title="Item")
        )
        mat = await pdp_service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Doc"),
        )

        comment_data = PDPCommentCreate(material_id=mat["id"], text="Review this")
        await pdp_service.add_comment(db, tenant.id, pdp["id"], user.id, comment_data)

        detail = await pdp_service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert len(detail["comments"]) == 1
        assert detail["comments"][0]["material_id"] == mat["id"]
