"""HRP-234: Change status used the wrong body shape (`status` instead of
`status_code`), which produced `status_code: Field required`. The endpoint
contract is now exercised from the FastAPI level."""

from __future__ import annotations

import uuid

from app.modules.exam import service
from app.modules.exam.schemas import MassExamCreate, OptionCreate, QuestionCreate
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _question() -> QuestionCreate:
    return QuestionCreate(
        title=f"Q-{uuid.uuid4().hex[:6]}",
        question_type="single_choice",
        options=[
            OptionCreate(title="Right", is_correct=True),
            OptionCreate(title="Wrong"),
        ],
    )


class TestChangeStatusEndpointAcceptsStatusCode:
    async def test_status_code_field_is_what_backend_expects(
        self,
        auth_client: AsyncClient,
        db: AsyncSession,
        tenant,
        user,
        employee,
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-234 endpoint")
        )
        await service.add_question(db, tenant.id, me["id"], _question())
        await service.assign_employees(db, tenant.id, me["id"], [employee.id])

        # Wrong body shape from the original bug
        bad = await auth_client.post(
            f"/api/mass-exams/{me['id']}/status", json={"status": "sent"}
        )
        assert bad.status_code == 422
        assert "status_code" in bad.text

        # Correct body shape
        good = await auth_client.post(
            f"/api/mass-exams/{me['id']}/status", json={"status_code": "sent"}
        )
        assert good.status_code == 200, good.text
        assert good.json()["status"] == "sent"

    async def test_forbidden_transition_returns_helpful_message(
        self,
        auth_client: AsyncClient,
        db: AsyncSession,
        tenant,
        user,
    ):
        me = await service.create_mass_exam(
            db, tenant.id, user.id, MassExamCreate(title="HRP-234 forbidden")
        )
        res = await auth_client.post(
            f"/api/mass-exams/{me['id']}/status", json={"status_code": "done"}
        )
        assert res.status_code == 400
        assert "Cannot transition" in res.json()["detail"]
        assert "Allowed" in res.json()["detail"]
