"""HRP-37 REDO: per-employee active-assessment cap.

Two deliverables on the REDO comment:

1. Lower the cap from 5 to 3 — covered by the constant assertion below.
2. Apply the cap during Mass assessment creation: if every assessee is
   already at the cap → 409, the group is not created. If only some
   are capped → the group is created with only the eligible children,
   and the response surfaces ``created_count`` / ``skipped_capped_count``
   so the frontend can render a `Created M of N` snackbar.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from app.core.security import hash_password
from app.modules.assessment import service
from app.modules.assessment.schemas import (
    AssessmentCreate,
    MassAssessmentCreate,
)


async def _extra_employee(db, tenant, suffix: str):
    from app.modules.auth.models import User as AuthUser
    from app.modules.employee.models import Employee
    from app.modules.position.models import Position

    pos = Position(tenant_id=tenant.id, title=f"Pos-{suffix}", source="manual")
    db.add(pos)
    await db.commit()
    await db.refresh(pos)

    u = AuthUser(
        email=f"{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("p"),
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


def test_hrp37_cap_is_three() -> None:
    """The REDO comment locked the value at 3."""
    assert service.MAX_ACTIVE_ASSESSMENTS_PER_EMPLOYEE == 3


@pytest.mark.asyncio
async def test_mass_partial_create_when_some_employees_capped(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Two employees in the batch; one already at the cap → group is
    created with only the eligible child and the response carries the
    partial counts."""
    other = await _extra_employee(db, tenant, "h37a")
    cap = service.MAX_ACTIVE_ASSESSMENTS_PER_EMPLOYEE
    for i in range(cap):
        await service.create_assessment(
            db,
            tenant.id,
            user.id,
            AssessmentCreate(
                title=f"fill-{i}",
                employee_id=employee.id,
                type_code="self",
            ),
        )

    result = await service.create_mass_assessment(
        db,
        tenant.id,
        user.id,
        MassAssessmentCreate(
            title="MassPartial",
            employee_ids=[employee.id, other.id],
            type_code="self",
        ),
    )
    assert result["created_count"] == 1
    assert result["requested_count"] == 2
    assert result["skipped_capped_count"] == 1
    # Only the eligible employee got a child assessment.
    assessees = {a["employee_id"] for a in result["assessments"]}
    assert assessees == {other.id}


@pytest.mark.asyncio
async def test_mass_create_409_when_all_employees_capped(
    db, tenant, user, employee, assessment_statuses, assessment_types
):
    """Both employees at the cap → request is rejected with 409 and the
    group row is not created."""
    other = await _extra_employee(db, tenant, "h37b")
    cap = service.MAX_ACTIVE_ASSESSMENTS_PER_EMPLOYEE
    for emp_id in (employee.id, other.id):
        for i in range(cap):
            await service.create_assessment(
                db,
                tenant.id,
                user.id,
                AssessmentCreate(
                    title=f"fill-{emp_id}-{i}",
                    employee_id=emp_id,
                    type_code="self",
                ),
            )

    with pytest.raises(Exception) as exc:
        await service.create_mass_assessment(
            db,
            tenant.id,
            user.id,
            MassAssessmentCreate(
                title="MassFail",
                employee_ids=[employee.id, other.id],
                type_code="self",
            ),
        )
    assert getattr(exc.value, "status_code", None) == 409
