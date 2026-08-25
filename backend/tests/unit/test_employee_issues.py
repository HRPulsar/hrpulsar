"""HRP-638: development-loop issue cohorts.

The dashboard counts these sets and the employee list filters by them, so
the rules live in one module and get pinned once. What each test protects:
a tile's number and the list behind its link are the same people.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from app.core.security import hash_password
from app.modules.assessment.models import PDP, Assessment, AssessmentResult
from app.modules.auth.models import User
from app.modules.competence.models import Competence, CompetenceGroup
from app.modules.employee import issues
from app.modules.employee.models import Employee
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_employee(
    db: AsyncSession, tenant, *, last_name: str = "Doe", status: str = "active"
) -> Employee:
    suffix = uuid.uuid4().hex[:6]
    user = User(
        email=f"issues-{suffix}@example.com",
        password_hash=hash_password("pw12345678"),
        first_name="Jane",
        last_name=last_name,
        tenant_id=tenant.id,
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    await db.flush()
    emp = Employee(
        user_id=user.id,
        tenant_id=tenant.id,
        position_title="Engineer",
        hire_date=date(2024, 1, 15),
        status=status,
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _done_assessment(
    db: AsyncSession,
    tenant,
    emp: Employee,
    statuses,
    types,
    *,
    percent: int | None = None,
    finished_days_ago: int = 3,
    passing_score: int | None = None,
) -> Assessment:
    a = Assessment(
        tenant_id=tenant.id,
        title=f"Review {uuid.uuid4().hex[:6]}",
        employee_id=emp.id,
        type_id=types["self"].id,
        status_id=statuses["done"].id,
        initiator_id=emp.user_id,
        finished_at=datetime.now(UTC) - timedelta(days=finished_days_ago),
        passing_score=passing_score,
    )
    db.add(a)
    await db.flush()
    if percent is not None:
        group = CompetenceGroup(tenant_id=tenant.id, title=f"G{uuid.uuid4().hex[:6]}")
        db.add(group)
        await db.flush()
        comp = Competence(
            tenant_id=tenant.id, group_id=group.id, title=f"C{uuid.uuid4().hex[:6]}"
        )
        db.add(comp)
        await db.flush()
        db.add(
            AssessmentResult(
                assessment_id=a.id,
                competence_id=comp.id,
                avg_score=percent / 25,
                percent=percent,
            )
        )
    await db.commit()
    return a


async def _add_pdp(db: AsyncSession, tenant, emp: Employee, **kwargs) -> PDP:
    plan = PDP(
        tenant_id=tenant.id,
        title=f"Plan {uuid.uuid4().hex[:6]}",
        employee_id=emp.id,
        author_id=emp.user_id,
        **kwargs,
    )
    db.add(plan)
    await db.commit()
    return plan


async def _cohorts(db: AsyncSession, tenant, **kwargs) -> dict[str, set[uuid.UUID]]:
    facts = await issues.collect_issue_facts(db, tenant.id, **kwargs)
    return issues.issue_cohorts(facts)


@pytest_asyncio.fixture
async def loop_fixtures(assessment_statuses, assessment_types):
    return assessment_statuses, assessment_types


# ---------------------------------------------------------------------------
# Cohort rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_tenant_has_no_issues(db: AsyncSession, tenant):
    cohorts = await _cohorts(db, tenant)
    assert all(not ids for ids in cohorts.values())


@pytest.mark.asyncio
async def test_gap_without_plan_is_both_gap_codes(
    db: AsyncSession, tenant, loop_fixtures
):
    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant)
    await _done_assessment(db, tenant, emp, statuses, types, percent=60)

    cohorts = await _cohorts(db, tenant)

    assert cohorts["competence_gap"] == {emp.id}
    assert cohorts["gaps_without_plan"] == {emp.id}


@pytest.mark.asyncio
async def test_open_plan_clears_gaps_without_plan(
    db: AsyncSession, tenant, loop_fixtures
):
    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant)
    await _done_assessment(db, tenant, emp, statuses, types, percent=60)
    await _add_pdp(db, tenant, emp, status="draft")

    cohorts = await _cohorts(db, tenant)

    assert cohorts["competence_gap"] == {emp.id}
    assert cohorts["gaps_without_plan"] == set()


@pytest.mark.asyncio
async def test_result_at_the_bar_is_not_a_gap(db: AsyncSession, tenant, loop_fixtures):
    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant)
    await _done_assessment(db, tenant, emp, statuses, types, percent=75)

    cohorts = await _cohorts(db, tenant)

    assert cohorts["competence_gap"] == set()


@pytest.mark.asyncio
async def test_pdp_overdue(db: AsyncSession, tenant, loop_fixtures):
    emp = await _make_employee(db, tenant)
    await _add_pdp(
        db,
        tenant,
        emp,
        status="in_progress",
        deadline=datetime.now(UTC) - timedelta(days=1),
    )

    cohorts = await _cohorts(db, tenant)

    assert cohorts["pdp_overdue"] == {emp.id}


@pytest.mark.asyncio
async def test_finished_plan_past_deadline_is_not_overdue(
    db: AsyncSession, tenant, loop_fixtures
):
    emp = await _make_employee(db, tenant)
    await _add_pdp(
        db,
        tenant,
        emp,
        status="done",
        deadline=datetime.now(UTC) - timedelta(days=5),
        finished_at=datetime.now(UTC) - timedelta(days=1),
    )

    cohorts = await _cohorts(db, tenant)

    assert cohorts["pdp_overdue"] == set()


@pytest.mark.asyncio
async def test_pdp_stuck_in_review(db: AsyncSession, tenant, loop_fixtures):
    fresh = await _make_employee(db, tenant, last_name="Fresh")
    stale = await _make_employee(db, tenant, last_name="Stale")
    await _add_pdp(db, tenant, fresh, status="review")
    plan = await _add_pdp(db, tenant, stale, status="review")
    # updated_at is server-managed; age it explicitly past the 14-day line.
    plan.updated_at = datetime.now(UTC) - timedelta(
        days=issues.STUCK_REVIEW_DAYS + 1
    )
    await db.commit()

    cohorts = await _cohorts(db, tenant)

    assert cohorts["pdp_stuck_review"] == {stale.id}


@pytest.mark.asyncio
async def test_assessment_stale_covers_never_assessed(
    db: AsyncSession, tenant, loop_fixtures
):
    statuses, types = loop_fixtures
    never = await _make_employee(db, tenant, last_name="Never")
    old = await _make_employee(db, tenant, last_name="Old")
    recent = await _make_employee(db, tenant, last_name="Recent")
    await _done_assessment(
        db,
        tenant,
        old,
        statuses,
        types,
        percent=90,
        finished_days_ago=issues.STALE_DAYS + 1,
    )
    await _done_assessment(db, tenant, recent, statuses, types, percent=90)

    cohorts = await _cohorts(db, tenant)

    assert cohorts["assessment_stale"] == {never.id, old.id}


@pytest.mark.asyncio
async def test_terminated_employees_are_out_of_scope(
    db: AsyncSession, tenant, loop_fixtures
):
    gone = await _make_employee(db, tenant, last_name="Gone", status="terminated")

    cohorts = await _cohorts(db, tenant)

    assert gone.id not in cohorts["assessment_stale"]


# ---------------------------------------------------------------------------
# Scoping — what makes the dashboard and the list agree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_visible_scope_limits_the_cohorts(
    db: AsyncSession, tenant, loop_fixtures
):
    statuses, types = loop_fixtures
    mine = await _make_employee(db, tenant, last_name="Mine")
    theirs = await _make_employee(db, tenant, last_name="Theirs")
    for emp in (mine, theirs):
        await _done_assessment(db, tenant, emp, statuses, types, percent=50)

    cohorts = await _cohorts(db, tenant, visible_employee_ids={mine.id})

    assert cohorts["competence_gap"] == {mine.id}


@pytest.mark.asyncio
async def test_empty_scope_yields_nothing(db: AsyncSession, tenant, loop_fixtures):
    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant)
    await _done_assessment(db, tenant, emp, statuses, types, percent=50)

    facts = await issues.collect_issue_facts(
        db, tenant.id, visible_employee_ids=set()
    )

    assert facts.total_active == 0
    assert issues.issue_cohorts(facts)["competence_gap"] == set()


@pytest.mark.asyncio
async def test_page_cohort_matches_tenant_wide_answer(
    db: AsyncSession, tenant, loop_fixtures
):
    """The list badges narrow the scan to one page; the verdict must not move."""
    statuses, types = loop_fixtures
    shown = await _make_employee(db, tenant, last_name="Shown")
    other = await _make_employee(db, tenant, last_name="Other")
    for emp in (shown, other):
        await _done_assessment(db, tenant, emp, statuses, types, percent=40)

    page = await _cohorts(db, tenant, employee_ids={shown.id})
    everyone = await _cohorts(db, tenant)

    assert page["gaps_without_plan"] == {shown.id}
    assert everyone["gaps_without_plan"] == {shown.id, other.id}


# ---------------------------------------------------------------------------
# Badge rendering
# ---------------------------------------------------------------------------


def test_broader_gap_code_is_suppressed_when_the_narrow_one_fires():
    emp = uuid.uuid4()
    per_employee = issues.issues_by_employee(
        {"competence_gap": {emp}, "gaps_without_plan": {emp}}
    )
    assert per_employee[emp] == ["gaps_without_plan"]


def test_gap_with_a_plan_still_shows_the_broad_code():
    emp = uuid.uuid4()
    per_employee = issues.issues_by_employee(
        {"competence_gap": {emp}, "gaps_without_plan": set()}
    )
    assert per_employee[emp] == ["competence_gap"]


def test_every_code_has_a_label_and_a_priority():
    for code in issues.ISSUE_CODES:
        assert code in issues.ISSUE_LABELS
        assert code in issues.ISSUE_PRIORITY


# ---------------------------------------------------------------------------
# The contract this whole change exists for
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finding_count_equals_the_filtered_list_total(
    db: AsyncSession, tenant, loop_fixtures
):
    """Click the finding, land on a list holding exactly that many people.

    The dashboard and the employee list must never disagree — that mismatch
    is what the filter was added to remove, so it gets pinned end to end
    rather than per module.
    """
    from app.modules.analytics import service as analytics_service
    from app.modules.employee import service as employee_service

    statuses, types = loop_fixtures
    with_gap = [
        await _make_employee(db, tenant, last_name=f"Gap{i}") for i in range(3)
    ]
    for emp in with_gap:
        await _done_assessment(db, tenant, emp, statuses, types, percent=40)
    planned = with_gap[0]
    await _add_pdp(db, tenant, planned, status="in_progress")
    await _make_employee(db, tenant, last_name="Clean")

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    finding = next(
        f for f in payload["findings"] if f["code"] == "gaps_without_plan"
    )

    _, total = await employee_service.list_employees(
        db, tenant.id, issue=["gaps_without_plan"]
    )

    assert finding["count"] == total == 2
    assert finding["href"] == "/employees?issue=gaps_without_plan"


@pytest.mark.asyncio
async def test_scoped_finding_count_equals_the_scoped_list_total(
    db: AsyncSession, tenant, loop_fixtures
):
    """Same equality for a division manager, whose scope narrows both sides."""
    from app.modules.analytics import service as analytics_service
    from app.modules.employee import service as employee_service

    statuses, types = loop_fixtures
    mine = await _make_employee(db, tenant, last_name="Mine")
    theirs = await _make_employee(db, tenant, last_name="Theirs")
    for emp in (mine, theirs):
        await _done_assessment(db, tenant, emp, statuses, types, percent=40)
    scope = {mine.id}

    payload = await analytics_service.dev_loop(db, tenant.id, scope)
    finding = next(
        f for f in payload["findings"] if f["code"] == "gaps_without_plan"
    )
    _, total = await employee_service.list_employees(
        db, tenant.id, visible_employee_ids=scope, issue=["gaps_without_plan"]
    )

    assert finding["count"] == total == 1


@pytest.mark.asyncio
async def test_gaps_tile_equals_the_competence_gap_list(
    db: AsyncSession, tenant, loop_fixtures
):
    """The tile counts everyone with a gap, plan or no plan."""
    from app.modules.analytics import service as analytics_service
    from app.modules.employee import service as employee_service

    statuses, types = loop_fixtures
    for i in range(2):
        emp = await _make_employee(db, tenant, last_name=f"Tile{i}")
        await _done_assessment(db, tenant, emp, statuses, types, percent=30)
        if i == 0:
            await _add_pdp(db, tenant, emp, status="draft")

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    _, total = await employee_service.list_employees(
        db, tenant.id, issue=["competence_gap"]
    )

    assert payload["stages"]["gaps"]["employees"] == total == 2
