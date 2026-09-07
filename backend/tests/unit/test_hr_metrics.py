"""HRP-732: HR metrics on the analytics page.

What these protect: a number is never shown as harder than it is, and a
metric this workspace has no signal for says so instead of reporting zero.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from app.core.security import hash_password
from app.main import app
from app.modules.analytics.hr_metrics import APPROX, EXACT, NO_DATA, hr_metrics
from app.modules.assessment.models import PDP
from app.modules.auth.models import User
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Employee, EmployeeEvent
from app.modules.talent_market.models import TalentCandidate, TalentCard
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def loop_fixtures(assessment_statuses, assessment_types):
    return assessment_statuses, assessment_types


async def _employee(db: AsyncSession, tenant, last_name: str = "Doe") -> Employee:
    suffix = uuid.uuid4().hex[:6]
    user = User(
        email=f"hrm-{suffix}@example.com",
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


async def _grades(db: AsyncSession, tenant) -> tuple[str, ...]:
    """Junior < Middle < Senior on the tenant's ladder, as the event log
    stores them (string ids)."""
    suffix = uuid.uuid4().hex[:6]
    items = [
        DictionaryItem(
            type="grade", title=f"{title} {suffix}", tenant_id=tenant.id, sort_index=idx
        )
        for title, idx in (("Junior", 10), ("Middle", 20), ("Senior", 30))
    ]
    db.add_all(items)
    await db.flush()
    ids = tuple(str(item.id) for item in items)
    await db.commit()
    return ids


def _move(
    emp: Employee, old: str | None, new: str | None, days_ago: int
) -> EmployeeEvent:
    return EmployeeEvent(
        employee_id=emp.id,
        event_type="position_change",
        description="moved",
        event_date=datetime.now(UTC).date() - timedelta(days=days_ago),
        old_value={"position_title": "Dev", "grade_id": old},
        new_value={"position_title": "Dev", "grade_id": new},
    )


def _exit(emp: Employee, days_ago: int) -> EmployeeEvent:
    return EmployeeEvent(
        employee_id=emp.id,
        event_type="termination",
        description="left",
        event_date=datetime.now(UTC).date() - timedelta(days=days_ago),
        old_value={"status": "active"},
        new_value={"status": "terminated"},
    )


def _by_code(result: dict) -> dict[str, dict]:
    return {m["code"]: m for m in result["metrics"]}


@pytest.mark.asyncio
async def test_empty_workspace_reports_no_data_not_zero(db: AsyncSession, tenant):
    """Three metrics live only in the event log; with no log they are unknown."""
    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    for code in ("promoted", "turnover", "time_to_promote"):
        assert metrics[code]["kind"] == NO_DATA
        assert metrics[code]["now"] is None


@pytest.mark.asyncio
async def test_plans_closed_compares_against_the_previous_window(
    db: AsyncSession, tenant
):
    emp = await _employee(db, tenant)
    now = datetime.now(UTC)
    for days_ago in (10, 20, 100):
        db.add(
            PDP(
                tenant_id=tenant.id,
                title=f"Plan {days_ago}",
                employee_id=emp.id,
                author_id=emp.user_id,
                status="done",
                finished_at=now - timedelta(days=days_ago),
            )
        )
    await db.commit()

    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    plans = metrics["plans_closed"]
    assert plans["kind"] == EXACT
    # Two inside the last 90 days, one in the 90 days before that.
    assert (plans["before"], plans["now"]) == (1, 2)


@pytest.mark.asyncio
async def test_promotion_needs_a_grade_change_not_just_a_title(
    db: AsyncSession, tenant
):
    """A renamed position is not a promotion; a changed grade is."""
    emp = await _employee(db, tenant)
    today = datetime.now(UTC).date()
    grade_a, _, grade_b = await _grades(db, tenant)
    db.add(
        EmployeeEvent(
            employee_id=emp.id,
            event_type="position_change",
            description="renamed",
            event_date=today,
            old_value={"position_title": "Dev", "grade_id": grade_a},
            new_value={"position_title": "Developer", "grade_id": grade_a},
        )
    )
    db.add(
        EmployeeEvent(
            employee_id=emp.id,
            event_type="position_change",
            description="promoted",
            event_date=today,
            old_value={"position_title": "Developer", "grade_id": grade_a},
            new_value={"position_title": "Senior Developer", "grade_id": grade_b},
        )
    )
    await db.commit()

    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    assert metrics["promoted"]["kind"] == APPROX
    assert metrics["promoted"]["now"] == 1


@pytest.mark.asyncio
async def test_legacy_title_only_events_are_not_counted(db: AsyncSession, tenant):
    """Rows written before HRP-732 carry no grade, so they cannot prove a move."""
    await _grades(db, tenant)
    emp = await _employee(db, tenant)
    db.add(
        EmployeeEvent(
            employee_id=emp.id,
            event_type="position_change",
            description="old row",
            event_date=datetime.now(UTC).date(),
            old_value={"position_title": "Dev"},
            new_value={"position_title": "Senior Dev"},
        )
    )
    await db.commit()

    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    assert metrics["promoted"]["now"] == 0


@pytest.mark.asyncio
async def test_promotions_without_a_grade_ladder_are_unknown_not_zero(
    db: AsyncSession, tenant
):
    """A move is ranked against the grade ladder; with no ladder at all the
    count is unknown, not a confident zero."""
    emp = await _employee(db, tenant)
    db.add(_move(emp, None, None, days_ago=1))
    await db.commit()
    # The shared test DB accumulates origin grades (tenant NULL) from other
    # files. Hide them inside this transaction only: the rename is rolled
    # back below, and hr_metrics never commits.
    await db.execute(
        update(DictionaryItem)
        .where(DictionaryItem.tenant_id.is_(None), DictionaryItem.type == "grade")
        .values(type="grade-hidden")
    )

    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    await db.rollback()
    assert metrics["promoted"]["kind"] == NO_DATA
    assert metrics["promoted"]["now"] is None


@pytest.mark.asyncio
async def test_turnover_is_a_share_of_headcount(db: AsyncSession, tenant):
    for _ in range(4):
        await _employee(db, tenant)
    leaver = await _employee(db, tenant, "Gone")
    leaver.status = "terminated"
    db.add(
        EmployeeEvent(
            employee_id=leaver.id,
            event_type="termination",
            description="left",
            event_date=datetime.now(UTC).date(),
            old_value={"status": "active"},
            new_value={"status": "terminated"},
        )
    )
    await db.commit()

    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    # Five on the books at the start of the window, one of them left: 1 of 5.
    # The leaver counts in the base of the bucket they left in, not only in
    # its numerator. Reconstructed from today's state, so an estimate.
    assert metrics["turnover"]["kind"] == APPROX
    assert metrics["turnover"]["now"] == 20


@pytest.mark.asyncio
async def test_turnover_counts_the_leavers_in_the_base_of_their_bucket(
    db: AsyncSession, tenant
):
    """Each bucket divides by the people on the books at its own start.

    Dividing every bucket by today's headcount made the earlier rate — and
    the trend between the two — drift with every later exit.
    """
    for _ in range(4):
        await _employee(db, tenant)
    for days_ago in (120, 100, 10):
        leaver = await _employee(db, tenant, "Gone")
        leaver.status = "terminated"
        db.add(_exit(leaver, days_ago))
    await db.commit()

    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    turnover = metrics["turnover"]
    assert turnover["kind"] == APPROX
    # Before (days 180..90 ago): 2 exits over the 4 still here plus the 3 who
    # left since day 180 = 2/7 -> 29. Now: 1 exit over 4 + 1 = 1/5 -> 20.
    assert (turnover["before"], turnover["now"]) == (29, 20)


@pytest.mark.asyncio
async def test_future_dated_events_are_not_counted(db: AsyncSession, tenant):
    """A termination or promotion dated after today is not a fact yet."""
    junior, _, senior = await _grades(db, tenant)
    emp = await _employee(db, tenant)
    leaver = await _employee(db, tenant, "Leaving")
    leaver.status = "terminated"
    db.add(_exit(leaver, -30))
    db.add(_move(emp, junior, senior, -30))
    await db.commit()

    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    assert (metrics["turnover"]["before"], metrics["turnover"]["now"]) == (0, 0)
    assert (metrics["promoted"]["before"], metrics["promoted"]["now"]) == (0, 0)


@pytest.mark.asyncio
async def test_only_an_upward_grade_move_is_a_promotion(db: AsyncSession, tenant):
    """A demotion and a move to an ungraded position change the grade too."""
    junior, _, senior = await _grades(db, tenant)
    up = await _employee(db, tenant, "Up")
    down = await _employee(db, tenant, "Down")
    out = await _employee(db, tenant, "Out")
    db.add_all(
        [
            _move(up, junior, senior, 10),
            _move(down, senior, junior, 10),
            _move(out, senior, None, 10),
        ]
    )
    await db.commit()

    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    assert metrics["promoted"]["now"] == 1


@pytest.mark.asyncio
async def test_time_to_promote_follows_the_bucket_of_the_later_move(
    db: AsyncSession, tenant
):
    """A gap belongs to the window its closing promotion landed in."""
    junior, middle, senior = await _grades(db, tenant)
    recent = await _employee(db, tenant, "Recent")
    earlier = await _employee(db, tenant, "Earlier")
    db.add_all(
        [
            # 170 days between the moves, the later one inside the window.
            _move(recent, junior, middle, 200),
            _move(recent, middle, senior, 30),
            # 140 days, the later one in the window before.
            _move(earlier, junior, middle, 260),
            _move(earlier, middle, senior, 120),
        ]
    )
    await db.commit()

    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    ttp = metrics["time_to_promote"]
    assert ttp["kind"] == APPROX
    assert (ttp["before"], ttp["now"]) == (
        round(140 / 30.44, 1),
        round(170 / 30.44, 1),
    )


@pytest.mark.asyncio
async def test_at_risk_replays_the_rule_against_the_plans_that_existed_then(
    db: AsyncSession, tenant, assessment_statuses, assessment_types
):
    """A gap with no plan back then counts before; a plan made since clears now."""
    from app.modules.assessment.models import Assessment, AssessmentResult
    from app.modules.competence.models import Competence, CompetenceGroup

    emp = await _employee(db, tenant)
    group = CompetenceGroup(tenant_id=tenant.id, title="G")
    db.add(group)
    await db.flush()
    comp = Competence(tenant_id=tenant.id, group_id=group.id, title="C")
    db.add(comp)
    await db.flush()
    a = Assessment(
        tenant_id=tenant.id,
        title="Review",
        employee_id=emp.id,
        type_id=assessment_types["self"].id,
        status_id=assessment_statuses["done"].id,
        initiator_id=emp.user_id,
        finished_at=datetime.now(UTC) - timedelta(days=100),
    )
    db.add(a)
    await db.flush()
    # 50 against the default bar of 75: a gap.
    db.add(
        AssessmentResult(
            assessment_id=a.id, competence_id=comp.id, avg_score=2.0, percent=50
        )
    )
    await db.commit()

    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    assert (metrics["at_risk"]["before"], metrics["at_risk"]["now"]) == (1, 1)

    db.add(
        PDP(
            tenant_id=tenant.id,
            title="Close it",
            employee_id=emp.id,
            author_id=emp.user_id,
        )
    )
    await db.commit()
    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    # The plan did not exist at the start of the window, so "before" holds.
    assert (metrics["at_risk"]["before"], metrics["at_risk"]["now"]) == (1, 0)


@pytest.mark.asyncio
async def test_avg_match_is_the_mean_of_the_stored_scores(db: AsyncSession, tenant):
    a = await _employee(db, tenant, "A")
    b = await _employee(db, tenant, "B")
    card = TalentCard(
        tenant_id=tenant.id,
        title="Card",
        card_type="vacancy",
        author_id=a.user_id,
        start_date=date.today(),
    )
    db.add(card)
    await db.flush()
    db.add_all(
        [
            TalentCandidate(
                card_id=card.id, employee_id=a.id, status="matched", match_score=60
            ),
            TalentCandidate(
                card_id=card.id, employee_id=b.id, status="matched", match_score=80
            ),
        ]
    )
    await db.commit()

    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    assert metrics["avg_match"]["kind"] == APPROX
    assert metrics["avg_match"]["now"] == 70


@pytest.mark.asyncio
async def test_engagement_cannot_exceed_one_hundred_percent(
    db: AsyncSession, tenant, assessment_statuses, assessment_types, skill_levels
):
    """A leaver who answered must not be counted against the active headcount."""
    from app.modules.assessment.models import (
        Assessment,
        AssessmentAnswer,
        AssessmentParticipant,
    )
    from app.modules.competence.models import Competence, CompetenceGroup, Indicator

    active = await _employee(db, tenant, "Stays")
    leaver = await _employee(db, tenant, "Left")
    leaver.status = "terminated"

    group = CompetenceGroup(tenant_id=tenant.id, title="G")
    db.add(group)
    await db.flush()
    comp = Competence(tenant_id=tenant.id, group_id=group.id, title="C")
    db.add(comp)
    await db.flush()
    indicator = Indicator(
        title="I",
        weight=1,
        sort_index=0,
        skill_level_id=skill_levels["Basic"].id,
        competence_id=comp.id,
        tenant_id=tenant.id,
    )
    a = Assessment(
        tenant_id=tenant.id,
        title="Review",
        employee_id=active.id,
        type_id=assessment_types["self"].id,
        status_id=assessment_statuses["done"].id,
        initiator_id=active.user_id,
    )
    db.add_all([indicator, a])
    await db.flush()
    # Both answer; only the active one may reach the numerator.
    for emp in (active, leaver):
        part = AssessmentParticipant(
            assessment_id=a.id, user_id=emp.user_id, role="self"
        )
        db.add(part)
        await db.flush()
        db.add(
            AssessmentAnswer(
                assessment_id=a.id,
                participant_id=part.id,
                indicator_id=indicator.id,
                score=4,
            )
        )
    await db.commit()

    metrics = _by_code(await hr_metrics(db, tenant.id, None, days=90))
    # One active employee, one counted answer: 1 of 1, not 2 of 1.
    assert metrics["engagement"]["now"] == 100


@pytest.mark.asyncio
async def test_empty_scope_reports_nothing(db: AsyncSession, tenant):
    """A manager with nobody under them must not read the whole workspace."""
    await _employee(db, tenant)
    metrics = _by_code(await hr_metrics(db, tenant.id, set(), days=90))
    assert metrics["plans_closed"]["now"] == 0
    assert metrics["engagement"]["now"] is None


def test_router_url_matches_the_one_the_page_calls():
    """The frontend asks for /analytics/hr-metrics; the router must serve it."""
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/analytics/hr-metrics" in paths


def test_analytics_page_endpoints_admit_hr():
    """HRP-732: HR opens the analytics page, so its own endpoints must let HR in."""
    import inspect

    from app.modules.analytics import router as analytics_router

    source = inspect.getsource(analytics_router)
    for route in ("assessments", "pdp", "hr-metrics"):
        marker = f'@router.get("/analytics/{route}")'
        assert marker in source, route
        # Everything from this decorator up to the next route definition.
        rest = source[source.index(marker) + len(marker) :]
        next_route = rest.find("@router.")
        block = rest if next_route == -1 else rest[:next_route]
        assert 'require_role("admin", "manager", "hr")' in block, route
