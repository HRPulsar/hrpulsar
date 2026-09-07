"""HRP-729: severity ordering — worst first in the chips and in the list.

The rule these pin: the five names on a dashboard chip are the five worst
cases, not the five alphabetically first, and the ``?issue=`` list that the
chip links to opens on the same person the chip led with.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from app.core.security import hash_password
from app.modules.analytics import service as analytics_service
from app.modules.assessment.models import PDP, Assessment, AssessmentResult
from app.modules.auth.models import User
from app.modules.competence.models import Competence, CompetenceGroup
from app.modules.employee import issues
from app.modules.employee import service as employee_service
from app.modules.employee.models import Employee
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def loop_fixtures(assessment_statuses, assessment_types):
    return assessment_statuses, assessment_types


async def _employee(db: AsyncSession, tenant, last_name: str) -> Employee:
    suffix = uuid.uuid4().hex[:6]
    user = User(
        email=f"sev-{suffix}@example.com",
        password_hash=hash_password("pw12345678"),
        first_name="Test",
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
        status="active",
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _assessment_with_gaps(
    db: AsyncSession,
    tenant,
    emp: Employee,
    statuses,
    types,
    percents: list[int],
    *,
    finished_days_ago: int = 3,
) -> Assessment:
    a = Assessment(
        tenant_id=tenant.id,
        title=f"Review {uuid.uuid4().hex[:6]}",
        employee_id=emp.id,
        type_id=types["self"].id,
        status_id=statuses["done"].id,
        initiator_id=emp.user_id,
        finished_at=datetime.now(UTC) - timedelta(days=finished_days_ago),
    )
    db.add(a)
    await db.flush()
    group = CompetenceGroup(tenant_id=tenant.id, title=f"G{uuid.uuid4().hex[:6]}")
    db.add(group)
    await db.flush()
    for percent in percents:
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


async def _pdp(
    db: AsyncSession, tenant, emp: Employee, *, status: str, **kwargs
) -> PDP:
    plan = PDP(
        tenant_id=tenant.id,
        title=f"Plan {uuid.uuid4().hex[:6]}",
        employee_id=emp.id,
        author_id=emp.user_id,
        status=status,
        **kwargs,
    )
    db.add(plan)
    await db.commit()
    return plan


@pytest.mark.asyncio
async def test_more_gaps_outrank_fewer(db: AsyncSession, tenant, loop_fixtures):
    statuses, types = loop_fixtures
    # Alphabetically Adams comes first; by severity Zorin must.
    adams = await _employee(db, tenant, "Adams")
    zorin = await _employee(db, tenant, "Zorin")
    await _assessment_with_gaps(db, tenant, adams, statuses, types, [70])
    await _assessment_with_gaps(db, tenant, zorin, statuses, types, [70, 60, 50])

    facts = await issues.collect_issue_facts(db, tenant.id)
    ordered = issues.sort_by_severity(
        facts, [adams, zorin], ["gaps_without_plan"]
    )
    assert [e.id for e in ordered] == [zorin.id, adams.id]


@pytest.mark.asyncio
async def test_deeper_gap_breaks_the_tie(db: AsyncSession, tenant, loop_fixtures):
    statuses, types = loop_fixtures
    shallow = await _employee(db, tenant, "Shallow")
    deep = await _employee(db, tenant, "Deep")
    # Same count, so only the depth of the worst competence can separate them.
    await _assessment_with_gaps(db, tenant, shallow, statuses, types, [70, 71])
    await _assessment_with_gaps(db, tenant, deep, statuses, types, [70, 20])

    facts = await issues.collect_issue_facts(db, tenant.id)
    ordered = issues.sort_by_severity(facts, [shallow, deep], ["gaps_without_plan"])
    assert [e.id for e in ordered] == [deep.id, shallow.id]


@pytest.mark.asyncio
async def test_a_result_exactly_on_the_bar_scores_as_a_zero_depth_gap(
    db: AsyncSession, tenant, loop_fixtures
):
    """HRP-731: ``<=`` made depth 0 reachable — it must still count.

    With the old strict rule the worst depth was at least 1, so nothing ever
    exercised the ``gap_worst_depth`` default. A competence sitting exactly
    on the bar now IS a gap whose depth is 0: it must score as one gap
    (count dominates) and must lose the tie to any gap with real depth.
    """
    statuses, types = loop_fixtures
    on_bar = await _employee(db, tenant, "Onbar")
    below = await _employee(db, tenant, "Below")
    await _assessment_with_gaps(db, tenant, on_bar, statuses, types, [75])
    await _assessment_with_gaps(db, tenant, below, statuses, types, [70])

    facts = await issues.collect_issue_facts(db, tenant.id)
    # Counted as a gap at all — the whole point of the inclusive rule.
    assert facts.gap_count[on_bar.id] == 1
    # Depth 0 is never stored, so the score falls through to the default.
    assert on_bar.id not in facts.gap_worst_depth
    assert issues.issue_severity(facts, on_bar.id, "gaps_without_plan") == 100.0
    assert issues.issue_severity(facts, below.id, "gaps_without_plan") == 105.0

    ordered = issues.sort_by_severity(facts, [on_bar, below], ["gaps_without_plan"])
    assert [e.id for e in ordered] == [below.id, on_bar.id]


@pytest.mark.asyncio
async def test_never_assessed_outranks_long_ago(
    db: AsyncSession, tenant, loop_fixtures
):
    """Decision on HRP-729: no measurement at all is the worse state."""
    statuses, types = loop_fixtures
    never = await _employee(db, tenant, "Never")
    stale = await _employee(db, tenant, "Stale")
    await _assessment_with_gaps(
        db, tenant, stale, statuses, types, [90], finished_days_ago=400
    )

    facts = await issues.collect_issue_facts(db, tenant.id)
    ordered = issues.sort_by_severity(facts, [stale, never], ["assessment_stale"])
    assert [e.id for e in ordered] == [never.id, stale.id]


@pytest.mark.asyncio
async def test_equal_severity_keeps_alphabetical_order(
    db: AsyncSession, tenant, loop_fixtures
):
    statuses, types = loop_fixtures
    b = await _employee(db, tenant, "Baker")
    a = await _employee(db, tenant, "Archer")
    for emp in (a, b):
        await _assessment_with_gaps(db, tenant, emp, statuses, types, [70])

    facts = await issues.collect_issue_facts(db, tenant.id)
    ordered = issues.sort_by_severity(facts, [b, a], ["gaps_without_plan"])
    assert [e.id for e in ordered] == [a.id, b.id]


@pytest.mark.asyncio
async def test_severity_follows_the_cohort_rule(
    db: AsyncSession, tenant, loop_fixtures
):
    """A result at or above the bar contributes nothing to the score.

    The severity reads the counters the cohort pass fills in, so it can never
    call something a gap that the chip does not.
    """
    statuses, types = loop_fixtures
    emp = await _employee(db, tenant, "Passing")
    await _assessment_with_gaps(db, tenant, emp, statuses, types, [90, 80])

    facts = await issues.collect_issue_facts(db, tenant.id)
    assert emp.id not in facts.gap_employees
    assert issues.issue_severity(facts, emp.id, "gaps_without_plan") == 0.0


@pytest.mark.asyncio
async def test_longer_overdue_outranks_shorter(db: AsyncSession, tenant):
    now = datetime.now(UTC)
    barely = await _employee(db, tenant, "Barely")
    ancient = await _employee(db, tenant, "Ancient")
    await _pdp(db, tenant, barely, status="in_progress", deadline=now - timedelta(days=2))
    await _pdp(db, tenant, ancient, status="in_progress", deadline=now - timedelta(days=90))

    facts = await issues.collect_issue_facts(db, tenant.id, now=now)
    assert issues.issue_severity(facts, ancient.id, "pdp_overdue") == 90
    assert issues.issue_severity(facts, barely.id, "pdp_overdue") == 2
    ordered = issues.sort_by_severity(facts, [barely, ancient], ["pdp_overdue"])
    assert [e.id for e in ordered] == [ancient.id, barely.id]


@pytest.mark.asyncio
async def test_longer_stuck_in_review_outranks_shorter(db: AsyncSession, tenant):
    now = datetime.now(UTC)
    fresh = await _employee(db, tenant, "Fresh")
    forgotten = await _employee(db, tenant, "Forgotten")
    # updated_at is server-managed, so set it after the insert.
    fresh_plan = await _pdp(db, tenant, fresh, status="review")
    old_plan = await _pdp(db, tenant, forgotten, status="returned")
    fresh_plan.updated_at = now - timedelta(days=20)
    old_plan.updated_at = now - timedelta(days=200)
    await db.commit()

    facts = await issues.collect_issue_facts(db, tenant.id, now=now)
    assert issues.issue_severity(facts, forgotten.id, "pdp_stuck_review") == 200
    assert issues.issue_severity(facts, fresh.id, "pdp_stuck_review") == 20
    ordered = issues.sort_by_severity(facts, [fresh, forgotten], ["pdp_stuck_review"])
    assert [e.id for e in ordered] == [forgotten.id, fresh.id]


@pytest.mark.asyncio
async def test_several_issue_codes_fall_back_to_newest_first(
    db: AsyncSession, tenant, loop_fixtures
):
    """Severity is not comparable across codes, so a mixed filter must not use it."""
    statuses, types = loop_fixtures
    # Never assessed — 10**6, the top of the severity scale, so severity would
    # lead with it. Created FIRST, so newest-first must put it LAST: the two
    # orderings disagree and the assertion can actually fail.
    never = await _employee(db, tenant, "Aaa")
    gapped = await _employee(db, tenant, "Zzz")
    await _assessment_with_gaps(db, tenant, gapped, statuses, types, [10, 20, 30])

    items, total = await employee_service.list_employees(
        db, tenant.id, issue=["gaps_without_plan", "assessment_stale"]
    )
    assert total == 2
    assert [i["id"] for i in items] == [gapped.id, never.id]


@pytest.mark.asyncio
async def test_chip_shows_the_worst_five_not_the_first_five(
    db: AsyncSession, tenant, loop_fixtures
):
    """The cut to five happens after the sort, not before it."""
    statuses, types = loop_fixtures
    # Six people; the worst one sorts last alphabetically, so under the old
    # ordering they were exactly the name that fell off the chip.
    mild = []
    for name in ("Aaa", "Bbb", "Ccc", "Ddd", "Eee"):
        emp = await _employee(db, tenant, name)
        await _assessment_with_gaps(db, tenant, emp, statuses, types, [70])
        mild.append(emp)
    worst = await _employee(db, tenant, "Zzz")
    await _assessment_with_gaps(db, tenant, worst, statuses, types, [10, 20, 30, 40])

    payload = await analytics_service.dev_loop(db, tenant.id, None)
    finding = next(
        f for f in payload["findings"] if f["code"] == "gaps_without_plan"
    )
    assert finding["count"] == 6
    assert len(finding["employees"]) == 5
    assert finding["employees"][0]["id"] == str(worst.id)


@pytest.mark.asyncio
async def test_data_version_covers_the_named_employees(
    db: AsyncSession, tenant, loop_fixtures
):
    """The AI-summary cache key must move when the five names move.

    Severity decides who is on the chip; if that ordering sat outside the
    fingerprint, a reshuffled queue would be described by a cached summary
    written about the old one.
    """
    statuses, types = loop_fixtures
    first = await _employee(db, tenant, "Aaa")
    second = await _employee(db, tenant, "Bbb")
    await _assessment_with_gaps(db, tenant, first, statuses, types, [70])
    await _assessment_with_gaps(db, tenant, second, statuses, types, [70])

    before = await analytics_service.dev_loop(db, tenant.id, None)
    names_before = [
        e["id"]
        for f in before["findings"]
        if f["code"] == "gaps_without_plan"
        for e in f["employees"]
    ]

    # Same cohort, same number of gaps, same gap_competences total — only the
    # depth differs, so the order of the named five is the ONLY thing that can
    # move the payload. A deeper *and* wider gap would change the stage counts
    # too and the assertion would pass without the order being in the print.
    await _assessment_with_gaps(db, tenant, second, statuses, types, [50])

    after = await analytics_service.dev_loop(db, tenant.id, None)
    names_after = [
        e["id"]
        for f in after["findings"]
        if f["code"] == "gaps_without_plan"
        for e in f["employees"]
    ]
    assert before["stages"] == after["stages"]
    assert names_before != names_after
    assert before["data_version"] != after["data_version"]


@pytest.mark.asyncio
async def test_issue_list_defaults_to_severity_order(
    db: AsyncSession, tenant, loop_fixtures
):
    statuses, types = loop_fixtures
    # The severe one is created FIRST so the two orderings actually disagree:
    # by severity it leads, by creation date (newest first) it trails. With the
    # rows the other way round both orderings coincide and neither assertion
    # below would be able to fail.
    severe = await _employee(db, tenant, "Zzz")
    mild = await _employee(db, tenant, "Aaa")
    await _assessment_with_gaps(db, tenant, severe, statuses, types, [10, 20, 30])
    await _assessment_with_gaps(db, tenant, mild, statuses, types, [70])

    items, total = await employee_service.list_employees(
        db, tenant.id, issue="gaps_without_plan"
    )
    assert total == 2
    assert [i["id"] for i in items] == [severe.id, mild.id]

    # The explicit opt-out goes back to newest-first, which here is the reverse.
    by_created, _ = await employee_service.list_employees(
        db, tenant.id, issue="gaps_without_plan", sort="created"
    )
    assert [i["id"] for i in by_created] == [mild.id, severe.id]


@pytest.mark.asyncio
async def test_issue_list_paginates_in_severity_order(
    db: AsyncSession, tenant, loop_fixtures
):
    """Paging must walk the ranked list, not re-sort each page on its own."""
    statuses, types = loop_fixtures
    made = []
    for i, name in enumerate(("Aaa", "Bbb", "Ccc")):
        emp = await _employee(db, tenant, name)
        # Aaa gets 3 gaps, Bbb 2, Ccc 1 — severity is the reverse of the alphabet.
        await _assessment_with_gaps(
            db, tenant, emp, statuses, types, [70] * (3 - i)
        )
        made.append(emp)

    page1, total = await employee_service.list_employees(
        db, tenant.id, skip=0, limit=2, issue="gaps_without_plan"
    )
    page2, _ = await employee_service.list_employees(
        db, tenant.id, skip=2, limit=2, issue="gaps_without_plan"
    )
    assert total == 3
    ordered = [str(i["id"]) for i in page1] + [str(i["id"]) for i in page2]
    assert ordered == [str(e.id) for e in made]
