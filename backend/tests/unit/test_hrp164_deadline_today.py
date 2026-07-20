"""HRP-164: a deadline equal to today's UTC date must not count as "in the past".

Reproduces the QA cases on top of the same fixtures the HRP-83 suite uses:

* Case 1 — single assessment, ``change_status(... "sent")``.
* Case 2 — mass assessment, ``bulk_change_status(... "sent")``.

Before the fix ``_deadline_in_past`` compared the deadline instant against
``datetime.now(timezone.utc)``. Picking "today" in the date picker stored
``00:00:00 UTC``, so a few hours later the send action rejected it with
``Deadline is in the past`` / inflated ``deadline_in_past`` skip counter.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from app.modules.assessment import service
from app.modules.assessment.models import Assessment
from app.modules.assessment.schemas import AssessmentCreate, MassAssessmentCreate
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit._send_prereqs import seed_send_prereqs


async def _make_assessment(db, tenant, user, employee) -> dict:
    return await service.create_assessment(
        db,
        tenant.id,
        user.id,
        AssessmentCreate(
            title=f"hrp164-{uuid.uuid4().hex[:6]}",
            employee_id=employee.id,
            type_code="self",
        ),
    )


async def _set_deadline(db: AsyncSession, assessment_id: uuid.UUID, value: datetime) -> None:
    a = await db.get(Assessment, assessment_id)
    assert a is not None
    a.ended_at = value
    await db.commit()


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
        email=f"hrp164-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
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


class TestSingleAssessmentDeadlineToday:
    async def test_change_status_accepts_deadline_at_today_midnight_utc(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Case 1: deadline picked as today lands as 00:00:00 UTC."""
        created = await _make_assessment(db, tenant, user, employee)
        await seed_send_prereqs(db, tenant.id, created["id"])
        today_midnight = datetime.combine(
            datetime.now(timezone.utc).date(),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        await _set_deadline(db, created["id"], today_midnight)

        result = await service.change_status(db, tenant.id, created["id"], "sent")
        assert result["status_code"] == "sent"

    async def test_change_status_still_rejects_yesterday(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Regression: a deadline that landed on yesterday's UTC date stays a hard error."""
        created = await _make_assessment(db, tenant, user, employee)
        await seed_send_prereqs(db, tenant.id, created["id"])
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        await _set_deadline(db, created["id"], yesterday)

        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, created["id"], "sent")
        # HRP-83 REDO: response code lifted from 400 to 409 (payload is
        # fine, the stored deadline is the conflict).
        assert exc.value.status_code == 409
        assert "deadline" in exc.value.detail.lower()


class TestMassAssessmentDeadlineToday:
    async def test_bulk_change_status_sends_when_deadline_is_today(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Case 2: bulk Change status (all) → Sent on a group with today's deadline."""
        emp2 = await _make_extra_employee(db, tenant, "today")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="HRP-164 bulk today",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        today_midnight = datetime.combine(
            datetime.now(timezone.utc).date(),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        for child in group["assessments"]:
            await seed_send_prereqs(db, tenant.id, child["id"])
            await _set_deadline(db, child["id"], today_midnight)

        result = await service.bulk_change_status(db, tenant.id, group["id"], "sent")

        assert result["changed"] == 2
        assert result["skipped"] == 0
        assert result["skipped_reasons"]["deadline_in_past"] == 0

        for child in group["assessments"]:
            a = await db.get(Assessment, child["id"])
            await db.refresh(a, ["status"])
            assert a.status.code == "sent"
