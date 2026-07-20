"""HRP-192: in_progress is auto-driven only. Any manual transition that
tries to push an assessment into ``in_progress`` — single or bulk — must
be rejected so the operator can't bypass the auto-flow guarantees
(first answer flips Sent → In progress server-side; manual nudges would
desync the lifecycle invariant the UI relies on).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from app.modules.assessment import service
from app.modules.assessment.models import Assessment
from app.modules.assessment.schemas import AssessmentCreate, MassAssessmentCreate
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import seed_send_prereqs


async def _make_assessment(db, tenant, user, employee, **kwargs) -> dict:
    data = AssessmentCreate(
        title=kwargs.get("title", f"hrp192-{uuid.uuid4().hex[:6]}"),
        employee_id=employee.id,
        type_code=kwargs.get("type_code", "self"),
    )
    return await service.create_assessment(db, tenant.id, user.id, data)


async def _make_extra_employee(db: AsyncSession, tenant, suffix: str):
    from app.core.security import hash_password
    from app.modules.auth.models import User as AuthUser
    from app.modules.employee.models import Employee
    from app.modules.position.models import Position

    pos = Position(tenant_id=tenant.id, title=f"Pos-{suffix}", source="manual")
    db.add(pos)
    await db.commit()
    await db.refresh(pos)

    u = AuthUser(
        email=f"hrp192-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("testpass"),
        first_name=f"F{suffix}",
        last_name=f"L{suffix}",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)

    emp = Employee(
        user_id=u.id,
        tenant_id=tenant.id,
        position_id=pos.id,
        position_title=pos.title,
        hire_date=date(2024, 1, 15),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


class TestChangeStatusManualInProgressIsRejected:
    async def test_sent_to_in_progress_is_rejected(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        created = await _make_assessment(db, tenant, user, employee)
        await seed_send_prereqs(db, tenant.id, created["id"])
        await service.change_status(db, tenant.id, created["id"], "sent")

        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, created["id"], "in_progress")
        assert exc.value.status_code == 400
        assert "manual transition is not allowed" in exc.value.detail.lower()

        a = (
            await db.execute(select(Assessment).where(Assessment.id == created["id"]))
        ).scalar_one()
        await db.refresh(a, ["status"])
        assert a.status.code == "sent"

    async def test_draft_to_in_progress_is_also_rejected(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """The guard is global — even from Draft (where sequence numbers would
        otherwise allow the jump) the manual push into In progress is denied
        so operators can't bypass the Sent checkpoint."""
        created = await _make_assessment(db, tenant, user, employee)
        await seed_send_prereqs(db, tenant.id, created["id"])

        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, created["id"], "in_progress")
        assert exc.value.status_code == 400
        assert "manual transition is not allowed" in exc.value.detail.lower()


class TestBulkChangeStatusManualInProgressIsSkipped:
    async def test_bulk_in_progress_skips_every_child_with_dedicated_reason(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Bulk path should not crash on the rejection — it skips per-child
        with the manual-in-progress reason so the UI can swap the toast
        copy to mirror the single-assessment error."""
        emp2 = await _make_extra_employee(db, tenant, "bulk-ip")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="HRP-192 bulk",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        a1_id = group["assessments"][0]["id"]
        a2_id = group["assessments"][1]["id"]
        await seed_send_prereqs(db, tenant.id, a1_id)
        await seed_send_prereqs(db, tenant.id, a2_id)
        await service.change_status(db, tenant.id, a1_id, "sent")
        await service.change_status(db, tenant.id, a2_id, "sent")

        result = await service.bulk_change_status(
            db, tenant.id, group["id"], "in_progress"
        )

        assert result["changed"] == 0
        assert result["skipped"] == 2
        reasons = result["skipped_reasons"]
        assert reasons["manual_in_progress_not_allowed"] == 2
        # Nothing else should fire — UI relies on this being the sole bucket
        # to swap the toast wording to "Manual transition is not allowed".
        assert reasons["terminal"] == 0
        assert reasons["same_or_lower_status"] == 0
        assert reasons["deadline_in_past"] == 0

        a1 = await db.get(Assessment, a1_id)
        a2 = await db.get(Assessment, a2_id)
        await db.refresh(a1, ["status"])
        await db.refresh(a2, ["status"])
        assert a1.status.code == "sent"
        assert a2.status.code == "sent"
