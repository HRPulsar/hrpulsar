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
async def test_result_at_the_bar_is_a_gap(db: AsyncSession, tenant, loop_fixtures):
    # HRP-731: the bar itself is a growth zone. One inclusive rule across
    # the product — the one the campaign analytics always used.
    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant)
    await _done_assessment(db, tenant, emp, statuses, types, percent=75)

    cohorts = await _cohorts(db, tenant)

    assert cohorts["competence_gap"] == {emp.id}


@pytest.mark.asyncio
async def test_result_above_the_bar_is_not_a_gap(
    db: AsyncSession, tenant, loop_fixtures
):
    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant)
    await _done_assessment(db, tenant, emp, statuses, types, percent=76)

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
    plan.updated_at = datetime.now(UTC) - timedelta(days=issues.STUCK_REVIEW_DAYS + 1)
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

    facts = await issues.collect_issue_facts(db, tenant.id, visible_employee_ids=set())

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
# HRP-720: "there is a problem -> what was done -> when does it resolve?"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pdp_codes_carry_the_open_plan_deadline(
    db: AsyncSession, tenant, loop_fixtures
):
    from app.modules.employee.service import get_employee

    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant, last_name="Overdue")
    await _done_assessment(db, tenant, emp, statuses, types, percent=30)
    due = datetime.now(UTC) - timedelta(days=5)
    await _add_pdp(db, tenant, emp, status="in_progress", deadline=due)
    # A finished plan is not what the badge is about, and its later deadline
    # must not win the "nearest" pick.
    await _add_pdp(
        db,
        tenant,
        emp,
        status="done",
        deadline=datetime.now(UTC) + timedelta(days=1),
    )

    card = await get_employee(db, tenant.id, emp.id, with_issues=True)
    by_code = {i["code"]: i["deadline"] for i in card["issues"]}

    assert by_code["pdp_overdue"] == due.date()
    # A gap is not a scheduled event -- nobody promised a date for it.
    assert by_code["competence_gap"] is None


@pytest.mark.asyncio
async def test_assessment_codes_carry_the_open_assessment_due_date(
    db: AsyncSession, tenant, loop_fixtures
):
    from app.modules.employee.service import get_employee

    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant, last_name="Stale")
    await _done_assessment(
        db, tenant, emp, statuses, types, percent=90, finished_days_ago=400
    )
    ends = datetime.now(UTC) + timedelta(days=7)
    a = Assessment(
        tenant_id=tenant.id,
        title="Re-assess",
        employee_id=emp.id,
        type_id=types["self"].id,
        status_id=statuses["sent"].id,
        initiator_id=emp.user_id,
        ended_at=ends,
    )
    db.add(a)
    await db.commit()

    card = await get_employee(db, tenant.id, emp.id, with_issues=True)
    by_code = {i["code"]: i["deadline"] for i in card["issues"]}

    assert by_code["assessment_stale"] == ends.date()


@pytest.mark.asyncio
async def test_stale_without_an_open_assessment_has_no_date(
    db: AsyncSession, tenant, loop_fixtures
):
    """Nothing scheduled is the honest answer -- not "due today"."""
    from app.modules.employee.service import get_employee

    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant, last_name="Forgotten")
    await _done_assessment(
        db, tenant, emp, statuses, types, percent=90, finished_days_ago=400
    )

    card = await get_employee(db, tenant.id, emp.id, with_issues=True)
    by_code = {i["code"]: i["deadline"] for i in card["issues"]}

    assert by_code["assessment_stale"] is None


async def _open_assessment(
    db: AsyncSession, tenant, emp: Employee, types, status, *, ended_at=None
) -> Assessment:
    a = Assessment(
        tenant_id=tenant.id,
        title=f"Open {uuid.uuid4().hex[:6]}",
        employee_id=emp.id,
        type_id=types["self"].id,
        status_id=status.id,
        initiator_id=emp.user_id,
        ended_at=ended_at,
    )
    db.add(a)
    await db.commit()
    return a


async def _await_result_status(db: AsyncSession):
    """The finalisation status the shared fixture does not seed."""
    from app.modules.assessment.models import AssessmentStatus
    from sqlalchemy import select

    row = (
        await db.execute(
            select(AssessmentStatus).where(AssessmentStatus.code == "await_result")
        )
    ).scalar_one_or_none()
    if row is None:
        row = AssessmentStatus(code="await_result", title="Await result", sequence=4)
        db.add(row)
        await db.commit()
    return row


@pytest.mark.asyncio
async def test_pending_finalisation_carries_no_date(
    db: AsyncSession, tenant, loop_fixtures
):
    """``assessment_pending`` fires on an ``await_result`` assessment, which has
    nothing left to schedule -- another open assessment's end date must not be
    pinned onto it."""
    from app.modules.employee.service import get_employee

    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant, last_name="Pending")
    await _open_assessment(db, tenant, emp, types, await _await_result_status(db))
    await _open_assessment(
        db,
        tenant,
        emp,
        types,
        statuses["sent"],
        ended_at=datetime.now(UTC) + timedelta(days=7),
    )

    card = await get_employee(db, tenant.id, emp.id, with_issues=True)
    by_code = {i["code"]: i["deadline"] for i in card["issues"]}

    assert "assessment_pending" in by_code
    assert by_code["assessment_pending"] is None


@pytest.mark.asyncio
async def test_review_codes_carry_the_reviewed_plan_deadline(
    db: AsyncSession, tenant, loop_fixtures
):
    """The plan sitting in review is the one the review codes are about, even
    when another open plan resolves sooner."""
    from app.modules.employee.service import get_employee

    emp = await _make_employee(db, tenant, last_name="Reviewed")
    await _add_pdp(
        db,
        tenant,
        emp,
        status="in_progress",
        deadline=datetime.now(UTC) + timedelta(days=3),
    )
    review_due = datetime.now(UTC) + timedelta(days=90)
    plan = await _add_pdp(db, tenant, emp, status="review", deadline=review_due)
    plan.updated_at = datetime.now(UTC) - timedelta(days=issues.STUCK_REVIEW_DAYS + 1)
    await db.commit()

    card = await get_employee(db, tenant.id, emp.id, with_issues=True)
    by_code = {i["code"]: i["deadline"] for i in card["issues"]}

    assert by_code["pdp_stuck_review"] == review_due.date()
    assert by_code["pdp_pending_review"] == review_due.date()


@pytest.mark.asyncio
async def test_pending_review_reads_only_the_plan_in_review(
    db: AsyncSession, tenant, loop_fixtures
):
    """``pdp_pending_review`` fires on a ``review`` plan alone; a ``returned``
    plan belongs to the stuck set and must not lend it an earlier date."""
    from app.modules.employee.service import get_employee

    emp = await _make_employee(db, tenant, last_name="Returned")
    returned_due = datetime.now(UTC) + timedelta(days=10)
    review_due = datetime.now(UTC) + timedelta(days=40)
    returned = await _add_pdp(db, tenant, emp, status="returned", deadline=returned_due)
    review = await _add_pdp(db, tenant, emp, status="review", deadline=review_due)
    for plan in (returned, review):
        plan.updated_at = datetime.now(UTC) - timedelta(
            days=issues.STUCK_REVIEW_DAYS + 1
        )
    await db.commit()

    card = await get_employee(db, tenant.id, emp.id, with_issues=True)
    by_code = {i["code"]: i["deadline"] for i in card["issues"]}

    assert by_code["pdp_pending_review"] == review_due.date()
    assert by_code["pdp_stuck_review"] == returned_due.date()


@pytest.mark.asyncio
async def test_stuck_plan_without_a_deadline_has_no_date(
    db: AsyncSession, tenant, loop_fixtures
):
    from app.modules.employee.service import get_employee

    emp = await _make_employee(db, tenant, last_name="Undated")
    await _add_pdp(
        db,
        tenant,
        emp,
        status="in_progress",
        deadline=datetime.now(UTC) + timedelta(days=3),
    )
    plan = await _add_pdp(db, tenant, emp, status="review")
    plan.updated_at = datetime.now(UTC) - timedelta(days=issues.STUCK_REVIEW_DAYS + 1)
    await db.commit()

    card = await get_employee(db, tenant.id, emp.id, with_issues=True)
    by_code = {i["code"]: i["deadline"] for i in card["issues"]}

    assert by_code["pdp_stuck_review"] is None


@pytest.mark.asyncio
async def test_stale_with_only_an_overdue_open_assessment_has_no_date(
    db: AsyncSession, tenant, loop_fixtures
):
    """A missed end date answers ``assessment_overdue``; it is not a date the
    stale badge can promise."""
    from app.modules.employee.service import get_employee

    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant, last_name="Missed")
    await _done_assessment(
        db, tenant, emp, statuses, types, percent=90, finished_days_ago=400
    )
    missed = datetime.now(UTC) - timedelta(days=30)
    await _open_assessment(db, tenant, emp, types, statuses["sent"], ended_at=missed)

    card = await get_employee(db, tenant.id, emp.id, with_issues=True)
    by_code = {i["code"]: i["deadline"] for i in card["issues"]}

    assert by_code["assessment_stale"] is None
    assert by_code["assessment_overdue"] == missed.date()


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
    with_gap = [await _make_employee(db, tenant, last_name=f"Gap{i}") for i in range(3)]
    for emp in with_gap:
        await _done_assessment(db, tenant, emp, statuses, types, percent=40)
    planned = with_gap[0]
    await _add_pdp(db, tenant, planned, status="in_progress")
    await _make_employee(db, tenant, last_name="Clean")

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    finding = next(f for f in payload["findings"] if f["code"] == "gaps_without_plan")

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
    finding = next(f for f in payload["findings"] if f["code"] == "gaps_without_plan")
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


# ---------------------------------------------------------------------------
# HRP-660: the card speaks the same language as the list row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_card_codes_match_the_list_row(db: AsyncSession, tenant, loop_fixtures):
    """One employee's card badges must equal the badges on their list row."""
    from app.modules.employee import service as employee_service

    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant, last_name="Carded")
    await _make_employee(db, tenant, last_name="Bystander")
    await _done_assessment(db, tenant, emp, statuses, types, percent=40)

    card = await employee_service.get_employee(db, tenant.id, emp.id, with_issues=True)
    rows, _ = await employee_service.list_employees(db, tenant.id, with_alerts=True)
    row = next(r for r in rows if r["id"] == emp.id)

    codes = [i["code"] for i in card["issues"]]
    assert codes == [i["code"] for i in row["issues"]]
    assert "gaps_without_plan" in codes


# ---------------------------------------------------------------------------
# HRP-706: the card's issue scan is bounded to the employee it describes
# ---------------------------------------------------------------------------


# Tables that hold per-employee rows. A statement reading any of them on the
# card path must say which employee it is about.
_EMPLOYEE_SCOPED_TABLES = ("assessments", "pdps", "assessment_results", "employees")

# The restrictions that make it about one employee. ``employees.id IN`` is the
# alerts collector reading the cohort rows themselves; the ``employee_id IN``
# pair is every signal query hanging off them.
_COHORT_PREDICATES = (
    "assessments.employee_id IN",
    "pdps.employee_id IN",
    "employees.id IN",
)


@pytest.mark.asyncio
async def test_card_issue_scan_names_the_employee_in_every_query(
    db: AsyncSession, tenant, loop_fixtures
):
    """HRP-706: every query behind one employee card names that employee.

    The review read ``employee_issue_codes`` as running two tenant-scale
    collectors per card open. It does not: ``compute_employee_alerts_bulk_all``
    restricts each of its queries by ``employee_ids`` and ``collect_issue_facts``
    by ``cohort``. Nothing was changed here -- this pins the claim.

    What is asserted is the cohort predicate itself. A statement count alone
    would not pin it: strip the WHERE out of either collector and the count
    does not move, the same queries just come back with the whole roster in
    them. So every statement touching employee-scoped tables has to carry an
    ``employee_id IN`` / ``employees.id IN`` restriction, and that assertion
    is what goes red if a filter is dropped.

    The roster-invariance of the count is asserted underneath, where it does
    earn its keep: it catches an N+1 opening up per bystander.
    """
    from app.modules.employee.service import employee_issue_codes
    from sqlalchemy import event

    statuses, types = loop_fixtures
    emp = await _make_employee(db, tenant, last_name="Carded")
    await _done_assessment(db, tenant, emp, statuses, types, percent=30)
    await db.commit()

    emp_id = emp.id

    async def _capture() -> list[str]:
        """The SQL employee_issue_codes issues for this one employee."""
        # Same starting point both times: a warm identity map would let the
        # second run skip relationship loads the first one paid for. The
        # re-fetch happens before the listener attaches, so it is not part
        # of what is captured.
        db.expunge_all()
        fresh = await db.get(Employee, emp_id)
        assert fresh is not None
        seen: list[str] = []

        def _on_exec(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            seen.append(" ".join(statement.split()))

        bind = db.bind
        event.listen(bind.sync_engine, "before_cursor_execute", _on_exec)
        try:
            await employee_issue_codes(db, tenant.id, fresh)
        finally:
            event.remove(bind.sync_engine, "before_cursor_execute", _on_exec)
        return seen

    def _assert_every_read_is_scoped(statements: list[str]) -> int:
        scoped = [
            s
            for s in statements
            if any(table in s for table in _EMPLOYEE_SCOPED_TABLES)
        ]
        # Sanity: if this ever drops to zero the capture broke, and an
        # all-green vacuous pass is exactly what this test exists to avoid.
        assert len(scoped) == 8, [f"{len(scoped)} scoped reads", *scoped]
        for sql in scoped:
            assert any(p in sql for p in _COHORT_PREDICATES), (
                "a collector query reads employee-scoped rows without naming "
                f"the employee -- it now scans the tenant: {sql}"
            )
        return len(statements)

    alone = _assert_every_read_is_scoped(await _capture())

    for i in range(10):
        other = await _make_employee(db, tenant, last_name=f"Bystander{i}")
        await _done_assessment(db, tenant, other, statuses, types, percent=30)
    await db.commit()

    # Ten bystanders, all carrying the same signals: a collector that lost
    # its cohort would now be pulling their rows too.
    crowded = _assert_every_read_is_scoped(await _capture())

    assert alone == crowded, (
        f"opening one card cost {alone} queries on a 1-employee roster and "
        f"{crowded} on an 11-employee one -- an N+1 opened up per bystander"
    )
    # 8 scoped collector reads (HRP-720 added the open-assessment due date)
    # plus the two selectin loads (user, roles) on the single cohort row.
    assert alone == 10, alone
