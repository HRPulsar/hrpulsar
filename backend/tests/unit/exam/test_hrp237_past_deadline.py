"""HRP-237: cannot send a mass exam whose deadline already passed."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.modules.exam import service
from app.modules.exam.schemas import MassExamCreate, OptionCreate, QuestionCreate
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


def _question() -> QuestionCreate:
    return QuestionCreate(
        title=f"Q-{uuid.uuid4().hex[:6]}",
        question_type="single_choice",
        options=[
            OptionCreate(title="A", is_correct=True),
            OptionCreate(title="B"),
        ],
    )


class TestPastDeadlineBlocksSend:
    async def test_past_deadline_rejects_send(
        self, db: AsyncSession, tenant, user, employee
    ):
        # Create exam first (without past deadline), then poke the row to
        # backdate the ended_at — schema validation refuses past values upfront.
        from app.modules.exam.models import MassExam

        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-237")
        )
        await service.add_question(db, tenant.id, me["id"], _question())
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])

        row = await db.get(MassExam, me["id"])
        row.ended_at = datetime.now(timezone.utc) - timedelta(days=3)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        assert exc.value.status_code == 400
        assert exc.value.detail == "Deadline in the past"

    async def test_today_deadline_allows_send(
        self, db: AsyncSession, tenant, user, employee
    ):
        from app.modules.exam.models import MassExam

        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-237 today")
        )
        await service.add_question(db, tenant.id, me["id"], _question())
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])

        row = await db.get(MassExam, me["id"])
        row.ended_at = datetime.now(timezone.utc)
        await db.commit()

        sent = await service.change_mass_exam_status(db, tenant.id, me["id"], "sent")
        assert sent["status"] == "sent"
