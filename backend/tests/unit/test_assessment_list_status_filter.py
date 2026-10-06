"""HRP-907: ``GET /assessments?status=`` — the dashboard's per-status totals.

The Active assessments block used to count a 100-row page client-side, so
every number capped at 100. It now reads ``total`` once per status; these pin
that the filter narrows both the rows and the count.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from app.core.security import hash_password
from app.modules.assessment import service
from app.modules.assessment.models import Assessment
from app.modules.auth.models import User
from app.modules.employee.models import Employee
from sqlalchemy.ext.asyncio import AsyncSession


async def _employee(db: AsyncSession, tenant) -> Employee:
    user = User(
        email=f"st-{uuid.uuid4().hex[:6]}@example.com",
        password_hash=hash_password("pw12345678"),
        first_name="Status",
        last_name="Filter",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    await db.flush()
    emp = Employee(
        user_id=user.id,
        tenant_id=tenant.id,
        hire_date=date(2024, 1, 1),
        status="active",
    )
    db.add(emp)
    await db.commit()
    return emp


@pytest.mark.asyncio
async def test_status_filter_narrows_rows_and_total(
    db: AsyncSession, tenant, assessment_statuses, assessment_types
):
    emp = await _employee(db, tenant)
    for code, n in (("draft", 2), ("sent", 3), ("in_progress", 1), ("done", 4)):
        for _ in range(n):
            db.add(
                Assessment(
                    tenant_id=tenant.id,
                    title=f"A {uuid.uuid4().hex[:6]}",
                    employee_id=emp.id,
                    type_id=assessment_types["self"].id,
                    status_id=assessment_statuses[code].id,
                    initiator_id=emp.user_id,
                )
            )
    await db.commit()

    items, total = await service.list_assessments(
        db, tenant.id, limit=1, status_codes=["sent"]
    )
    assert total == 3
    assert [i["status_code"] for i in items] == ["sent"]

    _, total = await service.list_assessments(
        db, tenant.id, limit=1, status_codes=["draft", "sent", "in_progress"]
    )
    assert total == 6
    # No filter keeps the old contract: every status.
    _, total = await service.list_assessments(db, tenant.id, limit=1)
    assert total == 10


@pytest.mark.asyncio
async def test_route_accepts_the_status_filter_the_dashboard_sends(auth_client):
    response = await auth_client.get("/api/assessments?status=on_review&limit=1")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_a_mistyped_status_is_rejected_not_counted_as_zero(auth_client):
    response = await auth_client.get("/api/assessments?status=on_reviw&limit=1")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_filter_accepts_every_seeded_status(
    db: AsyncSession, assessment_statuses
):
    """The literal is the status dictionary, not a guess at it."""
    from typing import get_args

    from app.modules.assessment.models import AssessmentStatus
    from app.modules.assessment.router import AssessmentStatusCode
    from sqlalchemy import select

    seeded = set((await db.execute(select(AssessmentStatus.code))).scalars())
    assert seeded <= set(get_args(AssessmentStatusCode))
