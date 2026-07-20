"""POS6: Employee alert priority scale + bulk computation."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from app.core.security import hash_password
from app.modules.assessment.models import (
    PDP,
    Assessment,
    AssessmentStatus,
    AssessmentType,
)
from app.modules.auth.models import User
from app.modules.company.models import Division
from app.modules.employee.alerts import (
    ALERT_PRIORITY,
    compute_employee_alert,
    compute_employee_alerts_bulk,
)
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, tenant, *, is_active: bool = True) -> User:
    u = User(
        email=f"alert-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name="Alert",
        last_name="Person",
        tenant_id=tenant.id,
        is_active=is_active,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_full_employee(
    db: AsyncSession,
    tenant,
    *,
    user_active: bool = True,
    division: Division | None = None,
    position: Position | None = None,
) -> Employee:
    """Create an employee with division+position set so the profile is complete."""
    user = await _make_user(db, tenant, is_active=user_active)
    if division is None:
        division = Division(tenant_id=tenant.id, name=f"Div-{uuid.uuid4().hex[:6]}")
        db.add(division)
        await db.commit()
        await db.refresh(division)
    if position is None:
        position = Position(
            tenant_id=tenant.id,
            title=f"Role-{uuid.uuid4().hex[:6]}",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

    emp = Employee(
        tenant_id=tenant.id,
        user_id=user.id,
        division_id=division.id,
        position_id=position.id,
        position_title=position.title,
        hire_date=date(2025, 1, 1),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    # Refresh with eager-loaded user (alerts read emp.user.is_active).
    from sqlalchemy.orm import selectinload

    refreshed = (
        await db.execute(
            select(Employee)
            .options(selectinload(Employee.user))
            .where(Employee.id == emp.id)
        )
    ).scalar_one()
    return refreshed


@pytest_asyncio.fixture
async def assessment_status_map(db: AsyncSession):
    """Seed the assessment statuses POS6 alerts depend on."""
    needed = [
        ("draft", "Draft", 0),
        ("sent", "Sent", 1),
        ("in_progress", "In progress", 2),
        ("await_result", "Await result", 3),
        ("done", "Done", 5),
    ]
    out: dict[str, AssessmentStatus] = {}
    for code, title, seq in needed:
        existing = (
            await db.execute(
                select(AssessmentStatus).where(AssessmentStatus.code == code)
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = AssessmentStatus(code=code, title=title, sequence=seq)
            db.add(existing)
        out[code] = existing
    await db.commit()
    return out


@pytest_asyncio.fixture
async def assessment_type_self(db: AsyncSession):
    existing = (
        await db.execute(select(AssessmentType).where(AssessmentType.code == "self"))
    ).scalar_one_or_none()
    if existing is None:
        existing = AssessmentType(code="self", title="Self assessment")
        db.add(existing)
        await db.commit()
        await db.refresh(existing)
    return existing


# ---------------------------------------------------------------------------
# Priority order is stable
# ---------------------------------------------------------------------------


def test_alert_priority_is_stable():
    assert ALERT_PRIORITY == (
        "user_inactive",
        "profile_incomplete",
        "assessment_overdue",
        "assessment_pending",
        "pdp_pending_review",
    )


# ---------------------------------------------------------------------------
# Per-priority cases
# ---------------------------------------------------------------------------


class TestSingleEmployeeAlert:
    async def test_no_alert_for_clean_employee(self, db: AsyncSession, tenant):
        emp = await _make_full_employee(db, tenant)
        assert await compute_employee_alert(db, tenant.id, emp) is None

    async def test_priority_1_user_inactive(self, db: AsyncSession, tenant):
        emp = await _make_full_employee(db, tenant, user_active=False)
        assert await compute_employee_alert(db, tenant.id, emp) == "user_inactive"

    async def test_priority_2_profile_incomplete(self, db: AsyncSession, tenant):
        emp = await _make_full_employee(db, tenant)
        # Drop the division reference to break the profile.
        emp.division_id = None
        await db.commit()
        await db.refresh(emp)

        assert await compute_employee_alert(db, tenant.id, emp) == "profile_incomplete"

    async def test_priority_3_assessment_overdue(
        self,
        db: AsyncSession,
        tenant,
        user,
        assessment_status_map,
        assessment_type_self,
    ):
        emp = await _make_full_employee(db, tenant)
        a = Assessment(
            tenant_id=tenant.id,
            employee_id=emp.id,
            type_id=assessment_type_self.id,
            status_id=assessment_status_map["in_progress"].id,
            initiator_id=user.id,
            ended_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(a)
        await db.commit()

        assert await compute_employee_alert(db, tenant.id, emp) == "assessment_overdue"

    async def test_priority_4_assessment_pending(
        self,
        db: AsyncSession,
        tenant,
        user,
        assessment_status_map,
        assessment_type_self,
    ):
        emp = await _make_full_employee(db, tenant)
        a = Assessment(
            tenant_id=tenant.id,
            employee_id=emp.id,
            type_id=assessment_type_self.id,
            status_id=assessment_status_map["await_result"].id,
            initiator_id=user.id,
        )
        db.add(a)
        await db.commit()

        assert await compute_employee_alert(db, tenant.id, emp) == "assessment_pending"

    async def test_priority_5_pdp_pending_review(self, db: AsyncSession, tenant, user):
        emp = await _make_full_employee(db, tenant)
        pdp = PDP(
            tenant_id=tenant.id,
            title="Plan",
            employee_id=emp.id,
            author_id=user.id,
            status="review",
        )
        db.add(pdp)
        await db.commit()

        assert await compute_employee_alert(db, tenant.id, emp) == "pdp_pending_review"

    async def test_higher_priority_wins(
        self,
        db: AsyncSession,
        tenant,
        user,
        assessment_status_map,
        assessment_type_self,
    ):
        # Profile incomplete (priority 2) AND PDP pending review (priority 5).
        emp = await _make_full_employee(db, tenant)
        emp.division_id = None
        await db.commit()
        await db.refresh(emp)

        pdp = PDP(
            tenant_id=tenant.id,
            title="Plan",
            employee_id=emp.id,
            author_id=user.id,
            status="review",
        )
        db.add(pdp)
        await db.commit()

        assert await compute_employee_alert(db, tenant.id, emp) == "profile_incomplete"


# ---------------------------------------------------------------------------
# Bulk computation: no N+1
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("assessment_type_self")
class TestBulkAlerts:
    async def test_bulk_dispatches_correct_codes(
        self,
        db: AsyncSession,
        tenant,
        user,
        assessment_status_map,
        assessment_type_self,
    ):
        clean = await _make_full_employee(db, tenant)
        inactive = await _make_full_employee(db, tenant, user_active=False)
        incomplete = await _make_full_employee(db, tenant)
        incomplete.division_id = None
        await db.commit()
        await db.refresh(incomplete)

        overdue = await _make_full_employee(db, tenant)
        db.add(
            Assessment(
                tenant_id=tenant.id,
                employee_id=overdue.id,
                type_id=assessment_type_self.id,
                status_id=assessment_status_map["sent"].id,
                initiator_id=user.id,
                ended_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        await db.commit()

        result = await compute_employee_alerts_bulk(
            db, tenant.id, [clean, inactive, incomplete, overdue]
        )

        assert result[clean.id] is None
        assert result[inactive.id] == "user_inactive"
        assert result[incomplete.id] == "profile_incomplete"
        assert result[overdue.id] == "assessment_overdue"

    async def test_bulk_uses_constant_query_count(
        self,
        db: AsyncSession,
        tenant,
        user,
        assessment_status_map,
        assessment_type_self,
    ):
        # Ten employees with mixed signals — bulk fetch must stay O(1) round
        # trips regardless of cohort size.
        cohort: list[Employee] = []
        for i in range(10):
            emp = await _make_full_employee(db, tenant)
            cohort.append(emp)
            if i % 2 == 0:
                # half get an overdue assessment
                db.add(
                    Assessment(
                        tenant_id=tenant.id,
                        employee_id=emp.id,
                        type_id=assessment_type_self.id,
                        status_id=assessment_status_map["in_progress"].id,
                        initiator_id=user.id,
                        ended_at=datetime.now(timezone.utc) - timedelta(days=2),
                    )
                )
        await db.commit()

        # Capture executions while the bulk runs.
        events: list[str] = []

        from sqlalchemy import event

        bind = db.bind

        def _on_execute(conn, clauseelement, *args, **kwargs):  # noqa: ANN001
            text = str(clauseelement)
            if "FROM assessments" in text or "FROM pdps" in text:
                events.append(text.split("FROM")[1].split()[0])

        event.listen(bind.sync_engine, "before_execute", _on_execute)
        try:
            result = await compute_employee_alerts_bulk(db, tenant.id, cohort)
        finally:
            event.remove(bind.sync_engine, "before_execute", _on_execute)

        # Exactly 3 round-trips total: overdue assessments, pending
        # assessments, pdps in review. (Each query may name the
        # employees table once, hence we filter on `assessments` / `pdps`.)
        assert len(events) == 3, events
        # And the codes still resolve correctly.
        for i, emp in enumerate(cohort):
            if i % 2 == 0:
                assert result[emp.id] == "assessment_overdue"
            else:
                assert result[emp.id] is None

    async def test_bulk_handles_empty_input(self, db: AsyncSession, tenant):
        assert await compute_employee_alerts_bulk(db, tenant.id, []) == {}

    async def test_bulk_isolates_off_tenant_employees(
        self,
        db: AsyncSession,
        tenant,
        user,
        assessment_status_map,
        assessment_type_self,
    ):
        """Mixed-tenant cohort: alerts must never reference rows from another
        tenant, and off-tenant employees come back with ``None``."""
        from app.modules.company.models import Tenant

        own = await _make_full_employee(db, tenant)
        # Build a second tenant, employee, and an *overdue* assessment for it.
        other_tenant = Tenant(
            name=f"Other {uuid.uuid4().hex[:6]}",
            slug=f"other-{uuid.uuid4().hex[:8]}",
        )
        db.add(other_tenant)
        await db.commit()
        await db.refresh(other_tenant)

        outsider = await _make_full_employee(db, other_tenant)
        db.add(
            Assessment(
                tenant_id=other_tenant.id,
                employee_id=outsider.id,
                type_id=assessment_type_self.id,
                status_id=assessment_status_map["in_progress"].id,
                initiator_id=user.id,
                ended_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        await db.commit()

        # Pass both into the resolver under the *original* tenant id; the
        # outsider's overdue row must not surface.
        result = await compute_employee_alerts_bulk(db, tenant.id, [own, outsider])
        assert result[own.id] is None
        assert result[outsider.id] is None
