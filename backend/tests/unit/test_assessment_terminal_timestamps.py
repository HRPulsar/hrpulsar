"""HRP-161: ``finished_at`` is stamped on both terminal transitions so the
UI can swap the Deadline label for a Completed / Cancelled date.

Companion to HRP-132's PDP behaviour — keeps the assessment record in sync
when the workflow ends through either branch.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from app.modules.assessment import service
from app.modules.assessment.models import Assessment
from app.modules.assessment.schemas import AssessmentCreate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tests.unit._send_prereqs import (
    advance_to_done,
    advance_to_in_progress,
    seed_send_prereqs,
)


class TestAssessmentTerminalTimestamp:
    @pytest_asyncio.fixture
    async def created(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title="Term",
                employee_id=employee.id,
                type_code="self",
            ),
        )
        return created

    async def test_finished_at_set_on_done(
        self,
        db,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        created,
    ):
        a_id = uuid.UUID(str(created["id"]))
        await seed_send_prereqs(db, tenant.id, a_id)
        await service.change_status(db, tenant.id, a_id, "sent")
        await advance_to_in_progress(db, tenant.id, a_id)
        await advance_to_done(db, tenant.id, a_id)

        a = (
            await db.execute(
                select(Assessment)
                .options(selectinload(Assessment.status))
                .where(Assessment.id == a_id)
            )
        ).scalar_one()
        assert a.status.code == "done"
        assert a.finished_at is not None

    async def test_finished_at_set_on_cancelled_from_draft(
        self,
        db,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        created,
    ):
        # Cancelling straight from draft (the common case for abandoned
        # assessments) must still pin ``finished_at`` so the UI shows
        # "Cancelled <date>".
        a_id = uuid.UUID(str(created["id"]))
        await service.change_status(db, tenant.id, a_id, "cancelled")

        a = (
            await db.execute(
                select(Assessment)
                .options(selectinload(Assessment.status))
                .where(Assessment.id == a_id)
            )
        ).scalar_one()
        assert a.status.code == "cancelled"
        assert a.finished_at is not None

    async def test_finished_at_set_on_cancelled_from_in_progress(
        self,
        db,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
        created,
    ):
        a_id = uuid.UUID(str(created["id"]))
        await seed_send_prereqs(db, tenant.id, a_id)
        await service.change_status(db, tenant.id, a_id, "sent")
        await advance_to_in_progress(db, tenant.id, a_id)
        await service.change_status(db, tenant.id, a_id, "cancelled")

        a = (
            await db.execute(
                select(Assessment)
                .options(selectinload(Assessment.status))
                .where(Assessment.id == a_id)
            )
        ).scalar_one()
        assert a.status.code == "cancelled"
        assert a.finished_at is not None
