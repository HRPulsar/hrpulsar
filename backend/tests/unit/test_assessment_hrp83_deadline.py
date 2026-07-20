"""HRP-83: launching an assessment (draft → sent) must refuse an
already-elapsed deadline so the assignee never lands on an overdue plan.

QA cases (all three transition draft → sent):
  1. Mass Assessment via action menu → bulk_change_status
  2. Mass Assessment child page → change_status on the child
  3. Single Assessment → change_status

Cases 2 and 3 hit the same code path (change_status); we cover one of
them and rely on the bulk test for case 1.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

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
        title=kwargs.get("title", f"hrp83-{uuid.uuid4().hex[:6]}"),
        employee_id=employee.id,
        type_code=kwargs.get("type_code", "self"),
    )
    return await service.create_assessment(db, tenant.id, user.id, data)


async def _make_extra_employee(db: AsyncSession, tenant, suffix: str):
    from datetime import date

    from app.core.security import hash_password
    from app.modules.auth.models import User as AuthUser
    from app.modules.employee.models import Employee
    from app.modules.position.models import Position

    pos = Position(tenant_id=tenant.id, title=f"Pos-{suffix}", source="manual")
    db.add(pos)
    await db.commit()
    await db.refresh(pos)

    u = AuthUser(
        email=f"hrp83-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
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


async def _force_past_deadline(
    db: AsyncSession, assessment_id: uuid.UUID, *, days_ago: int = 7
) -> None:
    """Rewrite ``ended_at`` directly. The schema validator blocks past
    deadlines on input, so we have to bypass it to reproduce the QA
    scenario (assessment was created with a future deadline, then time
    moved past it before launch)."""
    a = await db.get(Assessment, assessment_id)
    assert a is not None
    a.ended_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    await db.commit()


class TestChangeStatusDraftToSentDeadline:
    async def test_blocks_when_deadline_is_in_the_past(
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
        await _force_past_deadline(db, created["id"])

        with pytest.raises(HTTPException) as exc:
            await service.change_status(db, tenant.id, created["id"], "sent")
        # HRP-83 REDO: lifted from 400 to 409 — the payload is fine, the
        # conflict is with the stored ended_at value.
        assert exc.value.status_code == 409
        assert "deadline" in exc.value.detail.lower()

        # Status must stay draft.
        a = (
            await db.execute(select(Assessment).where(Assessment.id == created["id"]))
        ).scalar_one()
        await db.refresh(a, ["status"])
        assert a.status.code == "draft"

    async def test_allows_future_deadline(
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

        a = await db.get(Assessment, created["id"])
        a.ended_at = datetime.now(timezone.utc) + timedelta(days=7)
        await db.commit()

        result = await service.change_status(db, tenant.id, created["id"], "sent")
        assert result["status_code"] == "sent"

    async def test_allows_null_deadline(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Deadline is optional — when unset the launch must proceed."""
        created = await _make_assessment(db, tenant, user, employee)
        await seed_send_prereqs(db, tenant.id, created["id"])

        a = await db.get(Assessment, created["id"])
        assert a.ended_at is None  # default for AssessmentCreate without ended_at

        result = await service.change_status(db, tenant.id, created["id"], "sent")
        assert result["status_code"] == "sent"


class TestBulkChangeStatusDraftToSentDeadline:
    async def test_bulk_draft_to_sent_skips_past_deadline_with_reason(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """Mass action: 2 children, one of them past-deadline. Healthy one
        launches; expired one stays draft and surfaces a deadline reason
        so the UI snackbar can call it out separately from missing prereqs."""
        emp2 = await _make_extra_employee(db, tenant, "bd")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="HRP-83 bulk",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        a1_id = group["assessments"][0]["id"]
        a2_id = group["assessments"][1]["id"]
        await seed_send_prereqs(db, tenant.id, a1_id)
        await seed_send_prereqs(db, tenant.id, a2_id)
        await _force_past_deadline(db, a2_id)

        result = await service.bulk_change_status(db, tenant.id, group["id"], "sent")

        assert result["changed"] == 1
        assert result["skipped"] == 1
        assert result["skipped_reasons"]["deadline_in_past"] == 1
        # The healthy child must not be charged to another reason bucket.
        assert result["skipped_reasons"]["missing_criteria_or_scale"] == 0

        # Verify the actual statuses.
        a1 = await db.get(Assessment, a1_id)
        a2 = await db.get(Assessment, a2_id)
        await db.refresh(a1, ["status"])
        await db.refresh(a2, ["status"])
        assert a1.status.code == "sent"
        assert a2.status.code == "draft"

    async def test_bulk_response_schema_surfaces_deadline_reason(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """HRP-83 REDO: the response model ``BulkStatusChangeResult`` must
        carry the deadline bucket through Pydantic serialization, otherwise
        the toast falls back to "No assessments updated" even though the
        service knows every child was deadline-blocked. Previously
        ``BulkStatusSkipReasons`` only declared four fields and Pydantic
        silently dropped ``deadline_in_past``."""
        from app.modules.assessment.schemas import BulkStatusChangeResult

        emp2 = await _make_extra_employee(db, tenant, "redo-schema")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="HRP-83 schema",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )
        for child in group["assessments"]:
            await seed_send_prereqs(db, tenant.id, child["id"])
            await _force_past_deadline(db, child["id"])

        raw = await service.bulk_change_status(db, tenant.id, group["id"], "sent")
        # Serialize the same way the FastAPI response_model does.
        modeled = BulkStatusChangeResult.model_validate(raw)
        assert modeled.changed == 0
        assert modeled.skipped == 2
        assert modeled.skipped_reasons.deadline_in_past == 2, (
            "deadline_in_past must survive Pydantic serialization — the "
            "frontend uses it to swap the toast wording (HRP-83 REDO)."
        )

    async def test_bulk_draft_to_sent_when_every_child_past_deadline(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        """QA case 1: mass action with every child past-deadline. Nothing
        advances and the deadline bucket accounts for every skip, so the UI
        can surface a single "Deadline is in the past" error instead of a
        misleading "Updated 0 of N" success toast."""
        emp2 = await _make_extra_employee(db, tenant, "all-past")
        group = await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="HRP-83 bulk all past",
                employee_ids=[employee.id, emp2.id],
                type_code="self",
            ),
        )

        a1_id = group["assessments"][0]["id"]
        a2_id = group["assessments"][1]["id"]
        await seed_send_prereqs(db, tenant.id, a1_id)
        await seed_send_prereqs(db, tenant.id, a2_id)
        await _force_past_deadline(db, a1_id)
        await _force_past_deadline(db, a2_id)

        result = await service.bulk_change_status(db, tenant.id, group["id"], "sent")

        assert result["changed"] == 0
        assert result["skipped"] == 2
        assert result["skipped_reasons"]["deadline_in_past"] == 2
        # No other reason should fire — UI relies on deadline being the sole
        # bucket to swap the toast wording.
        assert result["skipped_reasons"]["missing_criteria_or_scale"] == 0
        assert result["skipped_reasons"]["terminal"] == 0
        assert result["skipped_reasons"]["same_or_lower_status"] == 0

        a1 = await db.get(Assessment, a1_id)
        a2 = await db.get(Assessment, a2_id)
        await db.refresh(a1, ["status"])
        await db.refresh(a2, ["status"])
        assert a1.status.code == "draft"
        assert a2.status.code == "draft"
