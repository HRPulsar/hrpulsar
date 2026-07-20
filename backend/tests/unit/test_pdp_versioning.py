"""Tests for GF12: PDP History & Versioning."""

import uuid

import pytest
from app.modules.assessment import pdp_service
from app.modules.assessment.schemas import (
    PDPCreate,
    PDPItemCreate,
    PDPMaterialCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_sendable_item(db, tenant_id, pdp_id):
    """HRP-12: every plan must carry at least one item+material before
    it can be moved out of ``draft``. Tests that don't care about content
    use this minimal seed to satisfy the validator."""
    item = await pdp_service.add_item(
        db, tenant_id, pdp_id, PDPItemCreate(title="Seed item")
    )
    await pdp_service.add_material(
        db,
        tenant_id,
        pdp_id,
        item["id"],
        PDPMaterialCreate(title="Seed material", link="https://example.com"),
    )
    return item


class TestPDPVersioning:
    async def _create_pdp(self, db, tenant, user, employee, *, seed: bool = True):
        data = PDPCreate(title="Plan", employee_id=employee.id)
        pdp = await pdp_service.create_pdp(db, tenant.id, user.id, data)
        if seed:
            await _seed_sendable_item(db, tenant.id, pdp["id"])
        return pdp

    async def test_no_version_on_draft(self, db: AsyncSession, tenant, user, employee):
        # Plan never leaves draft → no seed needed (and tests stay strict).
        pdp = await self._create_pdp(db, tenant, user, employee, seed=False)
        versions = await pdp_service.list_versions(db, tenant.id, pdp["id"])
        assert versions == []

    async def test_version_created_on_sent(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await self._create_pdp(db, tenant, user, employee)
        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "sent")

        versions = await pdp_service.list_versions(db, tenant.id, pdp["id"])
        assert len(versions) == 1
        assert versions[0]["version_number"] == 1
        assert versions[0]["status"] == "sent"

    async def test_version_created_on_returned(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-198: ``returned`` now only follows ``review`` — walk the
        # plan through the full state machine before bouncing it back.
        # HRP-21: ``review`` also snapshots, so this lifecycle records
        # sent → review → returned.
        pdp = await self._create_pdp(db, tenant, user, employee)
        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await pdp_service.change_pdp_status(
            db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
        )
        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "review")
        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "returned")

        versions = await pdp_service.list_versions(db, tenant.id, pdp["id"])
        assert [v["status"] for v in versions] == ["sent", "review", "returned"]

    async def test_version_snapshot_contains_items(
        self, db: AsyncSession, tenant, user, employee
    ):
        # Use the seed item; just verify it appears in the snapshot.
        pdp = await self._create_pdp(db, tenant, user, employee)

        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "sent")

        versions = await pdp_service.list_versions(db, tenant.id, pdp["id"])
        assert len(versions) == 1

        detail = await pdp_service.get_version(
            db, tenant.id, pdp["id"], versions[0]["id"]
        )
        assert "snapshot" in detail
        assert len(detail["snapshot"]["items"]) == 1
        assert detail["snapshot"]["items"][0]["title"] == "Seed item"

    async def test_version_snapshot_contains_materials(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await self._create_pdp(db, tenant, user, employee, seed=False)

        item_data = PDPItemCreate(title="Learn FastAPI")
        item = await pdp_service.add_item(db, tenant.id, pdp["id"], item_data)

        mat_data = PDPMaterialCreate(
            title="FastAPI Docs", format="web", link="https://fastapi.tiangolo.com"
        )
        await pdp_service.add_material(db, tenant.id, pdp["id"], item["id"], mat_data)

        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "sent")

        versions = await pdp_service.list_versions(db, tenant.id, pdp["id"])
        detail = await pdp_service.get_version(
            db, tenant.id, pdp["id"], versions[0]["id"]
        )
        materials = detail["snapshot"]["items"][0]["materials"]
        assert len(materials) == 1
        assert materials[0]["title"] == "FastAPI Docs"

    async def test_version_created_on_review(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-21: the owner submitting for review now also captures a
        # snapshot so the Progress Timeline shows the state the reviewer
        # is about to evaluate.
        pdp = await self._create_pdp(db, tenant, user, employee)
        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        await pdp_service.change_pdp_status(
            db, tenant.id, pdp["id"], "in_progress", bypass_transition_check=True
        )
        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "review")

        versions = await pdp_service.list_versions(db, tenant.id, pdp["id"])
        assert [v["status"] for v in versions] == ["sent", "review"]

    async def test_full_lifecycle_versions(
        self, db: AsyncSession, tenant, user, employee
    ):
        """HRP-16 + HRP-21: sent → in_progress → review → done creates
        3 versions (``sent``, ``review``, ``done``); ``in_progress`` still
        doesn't snapshot."""
        pdp = await self._create_pdp(db, tenant, user, employee)
        pdp_id = pdp["id"]

        await pdp_service.change_pdp_status(db, tenant.id, pdp_id, "sent")  # v1
        # HRP-197: ``sent → in_progress`` is owner-only via auto-promote;
        # the test still cares about the version side-effects, so bypass.
        await pdp_service.change_pdp_status(
            db, tenant.id, pdp_id, "in_progress", bypass_transition_check=True
        )  # no version
        await pdp_service.change_pdp_status(db, tenant.id, pdp_id, "review")  # v2
        await pdp_service.change_pdp_status(db, tenant.id, pdp_id, "done")  # v3

        versions = await pdp_service.list_versions(db, tenant.id, pdp_id)
        assert len(versions) == 3
        assert [v["status"] for v in versions] == ["sent", "review", "done"]

    async def test_get_version_not_found(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp = await self._create_pdp(db, tenant, user, employee)
        with pytest.raises(HTTPException) as exc:
            await pdp_service.get_version(db, tenant.id, pdp["id"], uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_version_preserves_progress(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-13/HRP-20: mark_item_passed now requires sent/in_progress/
        # returned. Toggle the flag via the ORM to keep this test focused
        # on snapshot fidelity rather than the new transition machinery.
        from app.modules.assessment.models import PDPItem

        pdp = await self._create_pdp(db, tenant, user, employee, seed=False)
        pdp_id = pdp["id"]

        item_data = PDPItemCreate(title="Task 1")
        item = await pdp_service.add_item(db, tenant.id, pdp_id, item_data)
        await pdp_service.add_material(
            db,
            tenant.id,
            pdp_id,
            item["id"],
            PDPMaterialCreate(title="Mat", link="https://example.com"),
        )
        item_obj = await db.get(PDPItem, item["id"])
        assert item_obj is not None
        item_obj.is_passed = True
        await db.commit()
        await pdp_service._recompute_progress(db, pdp_id)
        await db.commit()

        await pdp_service.change_pdp_status(db, tenant.id, pdp_id, "sent")

        versions = await pdp_service.list_versions(db, tenant.id, pdp_id)
        detail = await pdp_service.get_version(db, tenant.id, pdp_id, versions[0]["id"])
        assert detail["snapshot"]["total_progress"] == 100
        assert detail["snapshot"]["items"][0]["is_passed"] is True
