"""HRP-254 (D6) — analytics endpoints isolate demo tenants by construction.

``app.modules.analytics.service`` scopes every aggregate to a single
``tenant_id``, so demo sandboxes never leak into a paying tenant's
report (and vice versa). This regression test pins that contract: if
anyone introduces a cross-tenant query without filtering
``Tenant.is_demo``, this test fails.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from app.core.security import hash_password
from app.modules.analytics import service as analytics_service
from app.modules.assessment.models import (
    Assessment,
    AssessmentStatus,
    AssessmentType,
)
from app.modules.auth.models import User
from app.modules.company.models import Tenant
from app.modules.employee.models import Employee
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def status_done(db: AsyncSession):
    result = await db.execute(
        select(AssessmentStatus).where(AssessmentStatus.code == "done")
    )
    s = result.scalar_one_or_none()
    if not s:
        s = AssessmentStatus(code="done", title="Done", sequence=6)
        db.add(s)
        await db.commit()
        await db.refresh(s)
    return s


@pytest_asyncio.fixture
async def type_self(db: AsyncSession):
    result = await db.execute(
        select(AssessmentType).where(AssessmentType.code == "self")
    )
    t = result.scalar_one_or_none()
    if not t:
        t = AssessmentType(code="self", title="Self assessment")
        db.add(t)
        await db.commit()
        await db.refresh(t)
    return t


async def _make_tenant_with_assessment(
    db: AsyncSession,
    *,
    is_demo: bool,
    status: AssessmentStatus,
    a_type: AssessmentType,
) -> tuple[Tenant, Assessment]:
    suffix = uuid.uuid4().hex[:6]
    t = Tenant(name=f"T-{suffix}", slug=f"t-{suffix}", is_demo=is_demo)
    db.add(t)
    await db.flush()

    user = User(
        email=f"u-{suffix}@example.com",
        password_hash=hash_password("pw12345678"),
        first_name="U",
        last_name="V",
        tenant_id=t.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()

    emp = Employee(
        user_id=user.id,
        tenant_id=t.id,
        position_title="Engineer",
        hire_date=date(2024, 1, 15),
    )
    db.add(emp)
    await db.flush()

    a = Assessment(
        tenant_id=t.id,
        title=f"Assessment-{suffix}",
        employee_id=emp.id,
        type_id=a_type.id,
        status_id=status.id,
        initiator_id=user.id,
    )
    db.add(a)
    await db.commit()
    await db.refresh(t)
    await db.refresh(a)
    return t, a


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assessment_stats_paid_tenant_excludes_demo_data(
    db: AsyncSession, status_done, type_self
):
    paid_tenant, _ = await _make_tenant_with_assessment(
        db, is_demo=False, status=status_done, a_type=type_self
    )
    _, _ = await _make_tenant_with_assessment(
        db, is_demo=True, status=status_done, a_type=type_self
    )

    stats = await analytics_service.assessment_stats(db, paid_tenant.id)
    # Paid tenant has exactly its own one assessment, not the demo's
    assert stats["total"] == 1
    assert stats["by_status"].get("done") == 1


@pytest.mark.asyncio
async def test_assessment_stats_demo_tenant_excludes_paid_data(
    db: AsyncSession, status_done, type_self
):
    _, _ = await _make_tenant_with_assessment(
        db, is_demo=False, status=status_done, a_type=type_self
    )
    demo_tenant, _ = await _make_tenant_with_assessment(
        db, is_demo=True, status=status_done, a_type=type_self
    )

    stats = await analytics_service.assessment_stats(db, demo_tenant.id)
    assert stats["total"] == 1
    assert stats["by_status"].get("done") == 1


@pytest.mark.asyncio
async def test_assessment_stats_unknown_tenant_returns_empty(
    db: AsyncSession, status_done, type_self
):
    # A paid tenant exists with data, but we query a different uuid
    await _make_tenant_with_assessment(
        db, is_demo=False, status=status_done, a_type=type_self
    )
    stats = await analytics_service.assessment_stats(db, uuid.uuid4())
    assert stats["total"] == 0
    assert stats["by_status"] == {}
