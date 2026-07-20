"""HRP-166: ``GET /assessments`` groups rows by status — active first
(ordered by ``created_at`` desc), then Done (``finished_at`` desc), then
Cancelled (``finished_at`` desc). The UI uses this ordering to label the
trailing date column per row, so the contract is asserted end-to-end on
the service shape.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from app.modules.assessment import service
from app.modules.assessment.models import Assessment
from app.modules.assessment.schemas import AssessmentCreate
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import (
    advance_to_done,
    advance_to_in_progress,
    seed_send_prereqs,
)


class TestAssessmentOrdering:
    @pytest_asyncio.fixture
    async def trio(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        # Create three assessments — one per status bucket. The created_at /
        # finished_at stamps differ so the assertions on ordering inside each
        # bucket don't rely on insertion order.
        a_active = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(title="Active", employee_id=employee.id, type_code="self"),
        )
        a_done = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(title="Done", employee_id=employee.id, type_code="self"),
        )
        a_cancel = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Cancelled", employee_id=employee.id, type_code="self"
            ),
        )

        done_id = uuid.UUID(str(a_done["id"]))
        cancel_id = uuid.UUID(str(a_cancel["id"]))

        await seed_send_prereqs(db, tenant.id, done_id)
        await service.change_status(db, tenant.id, done_id, "sent")
        await advance_to_in_progress(db, tenant.id, done_id)
        await advance_to_done(db, tenant.id, done_id)
        await service.change_status(db, tenant.id, cancel_id, "cancelled")

        # Pin a deterministic finished_at so "done newer than cancelled" is
        # not subject to test-clock races.
        now = datetime.now(timezone.utc)
        done_row = await db.get(Assessment, done_id)
        cancel_row = await db.get(Assessment, cancel_id)
        assert done_row is not None and cancel_row is not None
        done_row.finished_at = now - timedelta(hours=1)
        cancel_row.finished_at = now - timedelta(hours=2)
        await db.commit()

        return {
            "active": uuid.UUID(str(a_active["id"])),
            "done": done_id,
            "cancel": cancel_id,
        }

    async def test_grouped_ordering(self, db, tenant, trio):
        items, total = await service.list_assessments(db, tenant.id)
        assert total == 3
        codes = [r["status_code"] for r in items]
        # Active (draft) sits first; both terminal rows follow.
        assert codes[0] not in ("done", "cancelled")
        assert codes == ["draft", "done", "cancelled"]

        ids = [r["id"] for r in items]
        assert ids == [trio["active"], trio["done"], trio["cancel"]]

    async def test_grouped_ordering_buckets_groups_and_singles(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """HRP-166 REDO: ``list_assessments_grouped`` (used by the main
        /assessments page) must apply the same active → done → cancelled
        bucketing as ``list_assessments``, with the bucket date driving
        the order inside each bucket. Mixed list of singles + groups."""
        from app.modules.assessment.schemas import MassAssessmentCreate

        # 1) Single active (draft).
        await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Single-Active", employee_id=employee.id, type_code="self"
            ),
        )
        # 2) Single done.
        single_done = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Single-Done", employee_id=employee.id, type_code="self"
            ),
        )
        done_id = uuid.UUID(str(single_done["id"]))
        await seed_send_prereqs(db, tenant.id, done_id)
        await service.change_status(db, tenant.id, done_id, "sent")
        await advance_to_in_progress(db, tenant.id, done_id)
        await advance_to_done(db, tenant.id, done_id)

        # 3) Group with one active child — must land in active bucket.
        await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Group-Active",
                employee_ids=[employee.id],
                type_code="self",
            ),
        )

        # 4) Group whose only child is cancelled — terminal bucket.
        group_cancelled = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="Group-Cancelled",
                employee_ids=[employee.id],
                type_code="self",
            ),
        )
        cancel_child_id = uuid.UUID(str(group_cancelled["assessments"][0]["id"]))
        await service.change_status(db, tenant.id, cancel_child_id, "cancelled")

        # Pin deterministic timestamps so bucket-internal ordering is
        # stable across test runs.
        now = datetime.now(timezone.utc)
        done_row = await db.get(Assessment, done_id)
        cancel_row = await db.get(Assessment, cancel_child_id)
        assert done_row is not None and cancel_row is not None
        done_row.finished_at = now - timedelta(hours=1)
        cancel_row.finished_at = now - timedelta(hours=2)
        await db.commit()

        items, total = await service.list_assessments_grouped(db, tenant.id)
        # Active rows first (group_active + single_active), then single_done,
        # then group_cancelled. Order within active doesn't matter for the
        # bucket assertion — we just need to confirm both are ahead of
        # terminals.
        assert total >= 4
        titles_in_order: list[str] = []
        for item in items:
            if item["kind"] == "single" and item["assessment"]:
                titles_in_order.append(item["assessment"]["title"])
            elif item["kind"] == "group" and item["group"]:
                titles_in_order.append(item["group"]["title"])
        active_titles = {"Single-Active", "Group-Active"}
        for active_title in active_titles:
            assert titles_in_order.index(active_title) < titles_in_order.index(
                "Single-Done"
            )
            assert titles_in_order.index(active_title) < titles_in_order.index(
                "Group-Cancelled"
            )
        # Done sits ahead of Cancelled (sorted by finished_at desc across
        # buckets — done at -1h, cancelled at -2h).
        assert titles_in_order.index("Single-Done") < titles_in_order.index(
            "Group-Cancelled"
        )

    async def test_active_bucket_orders_by_created_desc(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        first = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(title="First", employee_id=employee.id, type_code="self"),
        )
        second = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(title="Second", employee_id=employee.id, type_code="self"),
        )

        # The default rounding granularity on created_at can collapse two
        # creations into the same timestamp — bump the second row by a
        # second so the desc ordering is deterministic.
        second_row = await db.get(Assessment, uuid.UUID(str(second["id"])))
        first_row = await db.get(Assessment, uuid.UUID(str(first["id"])))
        assert first_row is not None and second_row is not None
        second_row.created_at = first_row.created_at + timedelta(seconds=1)
        await db.commit()

        items, _ = await service.list_assessments(db, tenant.id)
        ids = [r["id"] for r in items]
        assert ids[0] == uuid.UUID(str(second["id"]))
        assert ids[1] == uuid.UUID(str(first["id"]))
