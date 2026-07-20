"""HRP-24: PDP on-review items snapshot.

Verifies that:
- entering ``review`` freezes the items+materials block into
  ``pdps.on_review_items_snapshot``;
- the assigned employee sees the snapshot (not live items) while the plan
  stays in ``review``;
- other viewers (admin/manager) keep seeing live items;
- exiting ``review`` (to ``returned``/``done``/``cancelled``) clears
  the snapshot, so the employee sees the updated block;
- ``mark_item_passed`` is rejected while the plan is under review.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.assessment import pdp_service as service
from app.modules.assessment.models import PDP
from app.modules.assessment.schemas import (
    PDPCreate,
    PDPItemCreate,
    PDPMaterialCreate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_plan_in_review(db, tenant, user, employee):
    pdp = await service.create_pdp(
        db, tenant.id, user.id, PDPCreate(title="Plan", employee_id=employee.id)
    )
    pdp_id = pdp["id"]

    item_a = await service.add_item(
        db,
        tenant.id,
        pdp_id,
        PDPItemCreate(title="Item A", entity_type="custom", sort_index=0),
    )
    await service.add_material(
        db,
        tenant.id,
        pdp_id,
        item_a["id"],
        PDPMaterialCreate(title="Mat A1", link="https://example.com/a1"),
    )

    # HRP-197: ``sent → in_progress`` is no longer a manual admin step; use
    # ``bypass_transition_check`` so the helper can still land the plan in
    # the review state for these focused tests.
    await service.change_pdp_status(db, tenant.id, pdp_id, "sent")
    await service.change_pdp_status(
        db, tenant.id, pdp_id, "in_progress", bypass_transition_check=True
    )
    await service.change_pdp_status(db, tenant.id, pdp_id, "review")
    return pdp_id, item_a["id"]


class TestOnReviewSnapshotLifecycle:
    async def test_snapshot_captured_on_entry(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp_id, _ = await _make_plan_in_review(db, tenant, user, employee)

        p = await db.get(PDP, pdp_id)
        assert p is not None
        assert p.on_review_items_snapshot is not None
        assert len(p.on_review_items_snapshot) == 1
        snap_item = p.on_review_items_snapshot[0]
        assert snap_item["title"] == "Item A"
        assert len(snap_item["materials"]) == 1
        assert snap_item["materials"][0]["link"] == "https://example.com/a1"

    async def test_snapshot_cleared_on_returned(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp_id, _ = await _make_plan_in_review(db, tenant, user, employee)

        await service.change_pdp_status(db, tenant.id, pdp_id, "returned")
        p = await db.get(PDP, pdp_id)
        assert p is not None
        assert p.on_review_items_snapshot is None

    async def test_snapshot_cleared_on_done(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp_id, _ = await _make_plan_in_review(db, tenant, user, employee)

        await service.change_pdp_status(db, tenant.id, pdp_id, "done")
        p = await db.get(PDP, pdp_id)
        assert p is not None
        assert p.on_review_items_snapshot is None


class TestOnReviewSnapshotServing:
    async def test_employee_sees_snapshot_during_review(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp_id, item_a_id = await _make_plan_in_review(db, tenant, user, employee)

        # Admin adds a brand new item + material *while* the plan is in review.
        new_item = await service.add_item(
            db,
            tenant.id,
            pdp_id,
            PDPItemCreate(title="Item B (added during review)", entity_type="custom", sort_index=1),
        )
        await service.add_material(
            db,
            tenant.id,
            pdp_id,
            new_item["id"],
            PDPMaterialCreate(title="Mat B1", link="https://example.com/b1"),
        )

        # Employee viewing the plan must still see only Item A from the snapshot.
        detail_for_employee = await service.get_pdp_detail(
            db, tenant.id, pdp_id, viewer_user_id=user.id
        )
        titles = [i["title"] for i in detail_for_employee["items"]]
        assert titles == ["Item A"]
        assert detail_for_employee["items"][0]["materials"][0]["link"] == (
            "https://example.com/a1"
        )

    async def test_admin_sees_live_items_during_review(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp_id, _ = await _make_plan_in_review(db, tenant, user, employee)
        await service.add_item(
            db,
            tenant.id,
            pdp_id,
            PDPItemCreate(title="Item B", entity_type="custom", sort_index=1),
        )

        # Different user id (e.g. an admin) — viewer is not the PDP's employee,
        # so they keep seeing live items including the new one.
        other_admin_id = uuid.uuid4()
        detail = await service.get_pdp_detail(
            db, tenant.id, pdp_id, viewer_user_id=other_admin_id
        )
        titles = sorted(i["title"] for i in detail["items"])
        assert titles == ["Item A", "Item B"]

    async def test_employee_sees_live_items_after_returned(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp_id, _ = await _make_plan_in_review(db, tenant, user, employee)
        new_item = await service.add_item(
            db,
            tenant.id,
            pdp_id,
            PDPItemCreate(title="Item B", entity_type="custom", sort_index=1),
        )
        # HRP-187: Review → Returned needs every item to carry a material —
        # parity with Send. Seed one on the freshly added item so the
        # transition is allowed, then re-check the post-return view.
        await service.add_material(
            db,
            tenant.id,
            pdp_id,
            new_item["id"],
            PDPMaterialCreate(title="Mat B1", link="https://example.com/b1"),
        )
        await service.change_pdp_status(db, tenant.id, pdp_id, "returned")

        detail = await service.get_pdp_detail(
            db, tenant.id, pdp_id, viewer_user_id=user.id
        )
        titles = sorted(i["title"] for i in detail["items"])
        assert titles == ["Item A", "Item B"]

    async def test_viewer_unknown_falls_back_to_live_items(
        self, db: AsyncSession, tenant, user, employee
    ):
        pdp_id, _ = await _make_plan_in_review(db, tenant, user, employee)
        await service.add_item(
            db,
            tenant.id,
            pdp_id,
            PDPItemCreate(title="Item B", entity_type="custom", sort_index=1),
        )

        # No viewer_user_id (background job, e2e helper, …) — defaults to live
        # items so internal callers don't accidentally get a stale snapshot.
        detail = await service.get_pdp_detail(db, tenant.id, pdp_id)
        titles = sorted(i["title"] for i in detail["items"])
        assert titles == ["Item A", "Item B"]


class TestMarkItemPassedDuringReview:
    async def test_mark_item_passed_blocked_in_review_for_owner(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-24/130: the plan owner is locked out of item checkboxes while
        # the plan is under review — that's the admin/reviewer's surface.
        # The wrong-actor case returns 403; HRP-130 admins use a dedicated
        # ``is_admin=True`` flag to opt back in.
        pdp_id, item_a_id = await _make_plan_in_review(db, tenant, user, employee)

        with pytest.raises(HTTPException) as excinfo:
            await service.mark_item_passed(
                db, tenant.id, pdp_id, item_a_id, user.id
            )
        assert excinfo.value.status_code == 403

    async def test_mark_item_passed_allowed_after_returned(
        self, db: AsyncSession, tenant, user, employee
    ):
        # HRP-198: ``returned → sent`` is no longer allowed. The owner ticks
        # items off while the plan is in ``returned`` itself.
        pdp_id, item_a_id = await _make_plan_in_review(db, tenant, user, employee)
        await service.change_pdp_status(db, tenant.id, pdp_id, "returned")

        result = await service.mark_item_passed(
            db, tenant.id, pdp_id, item_a_id, user.id
        )
        assert result["is_passed"] is True
