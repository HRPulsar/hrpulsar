"""Development-loop issues — the shared answer to "who has a problem".

The dashboard used to compute these cohorts inline and keep them to
itself: the tiles said "23 employees with gaps" and the link next to
them opened the unfiltered employee list. This module is the single
source both sides read, so a filtered list can never disagree with the
number that sent the user there.

Five codes, all derived from an employee's LATEST done assessment and
their open development plans:

* ``competence_gap``     — a result below the passing bar.
* ``gaps_without_plan``  — ``competence_gap`` and no open PDP.
* ``pdp_overdue``        — an open PDP past its deadline.
* ``pdp_stuck_review``   — a PDP sitting in review/returned for 14 days.
* ``assessment_stale``   — no done assessment in the last 180 days.

Only ``active`` employees participate: the loop is about people the
company is developing, and a terminated row with no recent assessment
is not a finding anybody can act on.

Two cohort modes, and the difference is correctness, not tuning:

* tenant-wide (``employee_ids=None``) — what the dashboard counts and
  what the ``?issue=`` filter needs, because the filter has to select
  rows *before* pagination;
* narrowed (``employee_ids={...}``) — one page of a list, so rendering
  the issue badges does not drag the tenant's whole assessment history
  into memory.

``visible_employee_ids`` is ``get_visible_employee_ids`` output: ``None``
means unrestricted (admin / hr), any set is the caller's read scope.
Passing it here is what keeps a division manager's dashboard numbers
equal to their own filtered list.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assessment.models import (
    PDP,
    Assessment,
    AssessmentResult,
    AssessmentStatus,
)
from app.modules.assessment.pdp_service import PDP_FINALIZED_STATUSES
from app.modules.employee.models import Employee

# Thresholds. Kept here rather than in the analytics service because the
# employee list now answers to them too — a stale-assessment badge and a
# stale-assessment tile must age out on the same day.
STALE_DAYS = 180
STUCK_REVIEW_DAYS = 14
CLOSED_WINDOW_DAYS = 90
DEFAULT_PASSING = 75
# Assessment statuses that still expect an answer — an open assessment is
# what makes ``ended_at`` a promise rather than history (HRP-720).
OPEN_ASSESSMENT_STATUSES = ("sent", "in_progress")

IssueCode = Literal[
    "competence_gap",
    "gaps_without_plan",
    "pdp_overdue",
    "pdp_stuck_review",
    "assessment_stale",
]

ISSUE_CODES: tuple[IssueCode, ...] = (
    "competence_gap",
    "gaps_without_plan",
    "pdp_overdue",
    "pdp_stuck_review",
    "assessment_stale",
)

# Stable en labels; the UI localises by code, the API echoes these so a
# raw API consumer gets something readable.
ISSUE_LABELS: dict[IssueCode, str] = {
    "competence_gap": "Competence below the required bar",
    "gaps_without_plan": "Competence gap with no development plan",
    "pdp_overdue": "Development plan is overdue",
    "pdp_stuck_review": "Development plan stuck in review",
    "assessment_stale": "No assessment in the last 180 days",
}


def passing_bar(passing_score: int | None) -> int:
    # Identity check, not truthiness: 0 is a legitimate stored bar
    # ("no bar") and must not silently become the default 75.
    return DEFAULT_PASSING if passing_score is None else passing_score


def is_gap(percent: int | float, bar: int) -> bool:
    """HRP-731: the one growth-zone / gap rule for the whole product.

    A competence counts as a gap when its result is **at or below** the
    bar. The boundary is inclusive on purpose: scoring exactly the bar is
    not a competence the business treats as closed, and the group
    analytics growth zones have always read it that way. Every surface
    that splits results into gaps and strengths goes through here — the
    dashboard queue, the employee chips, the Competences tab and the
    assessment results blocks (the last two via the frontend twin
    ``isGap``) — so they cannot drift apart again.

    Takes the resolved bar rather than the raw snapshot: callers already
    have it from ``passing_bar`` and several of them reuse it across a
    whole assessment's results.

    ``collect_issue_facts`` decides the live cohorts through this function;
    anything re-deriving a gap at another point in time (a historical
    replay, a report) must call it too rather than spelling the comparison
    out again (HRP-729).
    """
    return percent <= bar


@dataclass(frozen=True)
class IssueFacts:
    """Everything the loop derives from one pass over the cohort's data."""

    active_by_id: dict[uuid.UUID, Employee] = field(default_factory=dict)
    done_rows: Sequence[Row] = ()
    results_by_assessment: dict[uuid.UUID, list[Row]] = field(default_factory=dict)
    latest_done: dict[uuid.UUID, Row] = field(default_factory=dict)
    assessed_recent: set[uuid.UUID] = field(default_factory=set)
    gap_employees: set[uuid.UUID] = field(default_factory=set)
    gap_competences: int = 0
    open_pdp_employees: set[uuid.UUID] = field(default_factory=set)
    open_pdp_count: int = 0
    overdue_employees: set[uuid.UUID] = field(default_factory=set)
    stuck_employees: set[uuid.UUID] = field(default_factory=set)
    plans_done_on_time: int = 0
    gaps_closed: int = 0
    # HRP-720: "when does this resolve?" — per employee, the date of the thing
    # each dated code is about: the earliest missed plan deadline, the earliest
    # deadline of a plan in the stuck set (review / returned), the earliest
    # deadline of a plan in review, the earliest missed assessment end date and
    # the next one still ahead. Collected here because the pass already reads
    # both tables; ``issue_deadlines`` picks the dict per code.
    pdp_overdue_deadline: dict[uuid.UUID, date] = field(default_factory=dict)
    pdp_stuck_deadline: dict[uuid.UUID, date] = field(default_factory=dict)
    pdp_pending_deadline: dict[uuid.UUID, date] = field(default_factory=dict)
    assessment_overdue_deadline: dict[uuid.UUID, date] = field(default_factory=dict)
    assessment_next_deadline: dict[uuid.UUID, date] = field(default_factory=dict)
    # HRP-729: how bad each gap is, per employee — collected in the same pass
    # that decides *whether* there is a gap, so the severity can never disagree
    # with the cohort about what counts as below the bar.
    gap_count: dict[uuid.UUID, int] = field(default_factory=dict)
    gap_worst_depth: dict[uuid.UUID, int] = field(default_factory=dict)
    # Same idea for the plan codes: how many days past the deadline, and how
    # many days sitting in review. Precomputed here rather than in the sort
    # key, which would otherwise rescan every plan for every employee.
    pdp_overdue_days: dict[uuid.UUID, int] = field(default_factory=dict)
    pdp_stuck_days: dict[uuid.UUID, int] = field(default_factory=dict)
    # HRP-724: the raw plan rows, kept so a caller can ask a window question
    # the fixed 90-day tiles do not answer. Already fetched — dropping them
    # only bought a second query later.
    pdp_rows: Sequence[Row] = ()

    @property
    def total_active(self) -> int:
        return len(self.active_by_id)


def latest_done_by_employee(
    done_rows: Sequence[Row], employee_ids: dict | set
) -> dict[uuid.UUID, Row]:
    """First (newest) done row per employee, restricted to ``employee_ids``."""
    latest: dict[uuid.UUID, Row] = {}
    for row in done_rows:
        if row.employee_id in employee_ids and row.employee_id not in latest:
            latest[row.employee_id] = row
    return latest


def closed_against_previous(
    passed_now: set[uuid.UUID],
    earlier: Sequence[Row],
    results_by_assessment: dict[uuid.UUID, list[Row]],
) -> set[uuid.UUID]:
    """Competences confirmed closed by the latest assessment.

    ``earlier`` is newest-first; per competence only its most recent
    earlier result is compared — a below-the-bar score further back that
    was already re-confirmed does not count again.
    """
    closed: set[uuid.UUID] = set()
    seen: set[uuid.UUID] = set()
    for prev in earlier:
        prev_bar = passing_bar(prev.passing_score)
        for res in results_by_assessment.get(prev.id, []):
            if res.competence_id in seen:
                continue
            seen.add(res.competence_id)
            if is_gap(res.percent, prev_bar) and res.competence_id in passed_now:
                closed.add(res.competence_id)
    return closed


def improved_against_previous(
    inside: Sequence[Row],
    before: Sequence[Row],
    results_by_assessment: dict[uuid.UUID, list[Row]],
) -> set[uuid.UUID]:
    """HRP-724: competences that scored higher inside the window than before it.

    Sibling of :func:`closed_against_previous`, and deliberately not the same
    question: that one counts crossing the passing bar, this one counts any
    strict improvement — 40 to 55 is movement worth reporting even though the
    gap is still open.

    Both sequences are one employee's done assessments, newest first (the
    order ``collect_issue_facts`` returns). Per competence only the newest
    result on each side is compared, and a competence with nothing measured
    before the window is not counted: with no baseline there is no gain, only
    a first reading.
    """

    def _newest(rows: Sequence[Row]) -> dict[uuid.UUID, int]:
        out: dict[uuid.UUID, int] = {}
        for row in rows:
            for res in results_by_assessment.get(row.id, []):
                out.setdefault(res.competence_id, res.percent)
        return out

    baseline = _newest(before)
    return {
        competence_id
        for competence_id, percent in _newest(inside).items()
        if competence_id in baseline and percent > baseline[competence_id]
    }


def split_by_window(
    rows: Sequence[Row], window_start: datetime
) -> tuple[list[Row], list[Row]]:
    """Split done assessments (newest first) into inside / before the window.

    Rows with no ``finished_at`` sit in neither half — an undated assessment
    cannot be placed on either side of a date.
    """
    inside = [
        r for r in rows if r.finished_at is not None and r.finished_at >= window_start
    ]
    before = [
        r for r in rows if r.finished_at is not None and r.finished_at < window_start
    ]
    return inside, before


def _cohort_filter(
    visible_employee_ids: set[uuid.UUID] | None,
    employee_ids: set[uuid.UUID] | None,
) -> set[uuid.UUID] | None:
    """Intersect the read scope with an explicit cohort; ``None`` = no limit."""
    if visible_employee_ids is None:
        return employee_ids
    if employee_ids is None:
        return visible_employee_ids
    return visible_employee_ids & employee_ids


async def collect_issue_facts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    visible_employee_ids: set[uuid.UUID] | None = None,
    employee_ids: set[uuid.UUID] | None = None,
    now: datetime | None = None,
) -> IssueFacts:
    """One pass over the cohort's assessments and plans.

    Three queries regardless of cohort size — active employees, their done
    assessments, the per-competence results — plus one for the plans.
    """
    now = now or datetime.now(UTC)
    stale_cutoff = now - timedelta(days=STALE_DAYS)
    stuck_cutoff = now - timedelta(days=STUCK_REVIEW_DAYS)
    closed_cutoff = now - timedelta(days=CLOSED_WINDOW_DAYS)

    cohort = _cohort_filter(visible_employee_ids, employee_ids)
    if cohort is not None and not cohort:
        # An empty scope is a legitimate answer (a manager with nobody
        # under them), not a reason to scan the tenant.
        return IssueFacts()

    active_q = select(Employee).where(
        Employee.tenant_id == tenant_id, Employee.status == "active"
    )
    if cohort is not None:
        active_q = active_q.where(Employee.id.in_(cohort))
    active_employees = (await db.execute(active_q)).scalars().all()
    active_by_id = {e.id: e for e in active_employees}
    if not active_by_id:
        return IssueFacts()

    done_q = (
        select(
            Assessment.id,
            Assessment.employee_id,
            Assessment.finished_at,
            Assessment.passing_score,
        )
        .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
        .where(Assessment.tenant_id == tenant_id, AssessmentStatus.code == "done")
        .order_by(Assessment.finished_at.desc().nulls_last(), Assessment.id.desc())
    )
    # Join instead of expanding done ids into an IN list: tenant-wide the id
    # set is the whole assessment history, and one bind param per id caps
    # out at asyncpg's 65535 limit long before a big tenant does.
    results_q = (
        select(
            AssessmentResult.assessment_id,
            AssessmentResult.competence_id,
            AssessmentResult.percent,
        )
        .join(Assessment, Assessment.id == AssessmentResult.assessment_id)
        .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
        .join(Employee, Employee.id == Assessment.employee_id)
        .where(
            Assessment.tenant_id == tenant_id,
            AssessmentStatus.code == "done",
            Employee.status == "active",
            AssessmentResult.percent.is_not(None),
        )
    )
    pdp_q = select(
        PDP.employee_id,
        PDP.status,
        PDP.deadline,
        PDP.updated_at,
        PDP.finished_at,
        # HRP-732: when the plan started existing — the only way to ask
        # "did this person have a plan back then?" without a second query.
        PDP.created_at,
    ).where(PDP.tenant_id == tenant_id)
    # HRP-720: every open assessment's end date. Split below into missed and
    # still ahead — one grouped minimum cannot tell those apart, and a stale
    # badge must not promise a date that has already passed.
    due_q = (
        select(Assessment.employee_id, Assessment.ended_at)
        .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
        .where(
            Assessment.tenant_id == tenant_id,
            AssessmentStatus.code.in_(OPEN_ASSESSMENT_STATUSES),
            Assessment.ended_at.is_not(None),
        )
    )
    if cohort is not None:
        # Narrow on the active set actually loaded, not on the requested
        # cohort: a requested id that is terminated or off-tenant carries
        # no issues, and its rows would only be discarded downstream.
        loaded = set(active_by_id)
        done_q = done_q.where(Assessment.employee_id.in_(loaded))
        results_q = results_q.where(Assessment.employee_id.in_(loaded))
        pdp_q = pdp_q.where(PDP.employee_id.in_(loaded))
        due_q = due_q.where(Assessment.employee_id.in_(loaded))

    done_rows = (await db.execute(done_q)).all()
    results_by_assessment: dict[uuid.UUID, list[Row]] = {}
    for res in (await db.execute(results_q)).all():
        results_by_assessment.setdefault(res.assessment_id, []).append(res)

    latest_done = latest_done_by_employee(done_rows, active_by_id)

    assessed_recent = {
        emp_id
        for emp_id, row in latest_done.items()
        if row.finished_at is not None and row.finished_at >= stale_cutoff
    }

    # Gaps: results below the bar in the employee's latest done assessment.
    gap_employees: set[uuid.UUID] = set()
    gap_competences = 0
    gap_count: dict[uuid.UUID, int] = {}
    gap_worst_depth: dict[uuid.UUID, int] = {}
    for emp_id, row in latest_done.items():
        bar = passing_bar(row.passing_score)
        for res in results_by_assessment.get(row.id, []):
            if is_gap(res.percent, bar):
                gap_employees.add(emp_id)
                gap_competences += 1
                # HRP-729: inside the branch on purpose — whatever the bar
                # comparison becomes, the severity follows it for free.
                gap_count[emp_id] = gap_count.get(emp_id, 0) + 1
                depth = bar - res.percent
                if depth > gap_worst_depth.get(emp_id, 0):
                    gap_worst_depth[emp_id] = depth

    # Confirmed closures: competence below the bar in the IMMEDIATELY
    # preceding result and at/above the bar in the latest assessment,
    # counted when the closing (latest) assessment finished inside the
    # 90-day window. Only the adjacent-previous result counts — otherwise
    # a gap closed years ago would be re-counted on every re-assessment
    # and the Closed tile would grow monotonically (review finding).
    done_by_employee: dict[uuid.UUID, list[Row]] = {}
    for row in done_rows:
        if row.employee_id in active_by_id:
            done_by_employee.setdefault(row.employee_id, []).append(row)
    gaps_closed = 0
    for emp_id, latest in latest_done.items():
        if latest.finished_at is None or latest.finished_at < closed_cutoff:
            continue
        latest_bar = passing_bar(latest.passing_score)
        passed_now = {
            res.competence_id
            for res in results_by_assessment.get(latest.id, [])
            if not is_gap(res.percent, latest_bar)
        }
        earlier = [r for r in done_by_employee[emp_id] if r.id != latest.id]
        gaps_closed += len(
            closed_against_previous(passed_now, earlier, results_by_assessment)
        )

    pdp_rows = (await db.execute(pdp_q)).all()
    open_pdp_employees = {
        r.employee_id for r in pdp_rows if r.status not in PDP_FINALIZED_STATUSES
    }
    open_pdp_count = sum(1 for r in pdp_rows if r.status not in PDP_FINALIZED_STATUSES)
    overdue_employees = {
        r.employee_id
        for r in pdp_rows
        if r.status not in PDP_FINALIZED_STATUSES
        and r.deadline is not None
        and r.deadline < now
    }
    stuck_employees = {
        r.employee_id
        for r in pdp_rows
        if r.status in {"review", "returned"} and r.updated_at < stuck_cutoff
    }
    # HRP-729: worst plan per employee, on the same clock as the cohorts above.
    pdp_overdue_days: dict[uuid.UUID, int] = {}
    pdp_stuck_days: dict[uuid.UUID, int] = {}
    for r in pdp_rows:
        if (
            r.status not in PDP_FINALIZED_STATUSES
            and r.deadline is not None
            and r.deadline < now
        ):
            days = (now - r.deadline).days
            if days > pdp_overdue_days.get(r.employee_id, -1):
                pdp_overdue_days[r.employee_id] = days
        if r.status in {"review", "returned"}:
            days = (now - r.updated_at).days
            if days > pdp_stuck_days.get(r.employee_id, -1):
                pdp_stuck_days[r.employee_id] = days
    plans_done_on_time = sum(
        1
        for r in pdp_rows
        if r.status == "done"
        and r.finished_at is not None
        and r.finished_at >= closed_cutoff
        and r.deadline is not None
        and r.finished_at <= r.deadline
    )

    # Per code, the plan that raised it: the overdue code answers with the
    # earliest missed deadline, the stuck code with the earliest deadline in
    # its review / returned set, the pending code with a plan in review only
    # (a returned plan is not awaiting anybody's review). One nearest date
    # across all open plans handed a stuck review the in-progress plan's date
    # (review finding).
    pdp_overdue_deadline: dict[uuid.UUID, date] = {}
    pdp_stuck_deadline: dict[uuid.UUID, date] = {}
    pdp_pending_deadline: dict[uuid.UUID, date] = {}
    for r in pdp_rows:
        if r.status in PDP_FINALIZED_STATUSES or r.deadline is None:
            continue
        due = r.deadline.date()
        if r.deadline < now:
            pdp_overdue_deadline[r.employee_id] = min(
                pdp_overdue_deadline.get(r.employee_id, due), due
            )
        if r.status in {"review", "returned"}:
            pdp_stuck_deadline[r.employee_id] = min(
                pdp_stuck_deadline.get(r.employee_id, due), due
            )
        if r.status == "review":
            pdp_pending_deadline[r.employee_id] = min(
                pdp_pending_deadline.get(r.employee_id, due), due
            )
    # Same split for assessments: a missed end date is what ``assessment_overdue``
    # is about; ``assessment_stale`` may only point at one still ahead.
    assessment_overdue_deadline: dict[uuid.UUID, date] = {}
    assessment_next_deadline: dict[uuid.UUID, date] = {}
    today = now.date()
    for emp_id, ends in (await db.execute(due_q)).all():
        if emp_id not in active_by_id:
            continue
        due = ends.date()
        if ends < now:
            assessment_overdue_deadline[emp_id] = min(
                assessment_overdue_deadline.get(emp_id, due), due
            )
        if due >= today:
            assessment_next_deadline[emp_id] = min(
                assessment_next_deadline.get(emp_id, due), due
            )

    return IssueFacts(
        active_by_id=active_by_id,
        done_rows=done_rows,
        results_by_assessment=results_by_assessment,
        latest_done=latest_done,
        assessed_recent=assessed_recent,
        gap_employees=gap_employees,
        gap_competences=gap_competences,
        open_pdp_employees=open_pdp_employees,
        open_pdp_count=open_pdp_count,
        overdue_employees=overdue_employees,
        stuck_employees=stuck_employees,
        plans_done_on_time=plans_done_on_time,
        gaps_closed=gaps_closed,
        pdp_overdue_deadline=pdp_overdue_deadline,
        pdp_stuck_deadline=pdp_stuck_deadline,
        pdp_pending_deadline=pdp_pending_deadline,
        assessment_overdue_deadline=assessment_overdue_deadline,
        assessment_next_deadline=assessment_next_deadline,
        gap_count=gap_count,
        gap_worst_depth=gap_worst_depth,
        pdp_overdue_days=pdp_overdue_days,
        pdp_stuck_days=pdp_stuck_days,
        pdp_rows=pdp_rows,
    )


def development_dynamics(
    facts: IssueFacts, days: int, *, now: datetime | None = None
) -> dict:
    """HRP-724: what actually moved in the last ``days``.

    Two numbers, both about people and not about paperwork: development plans
    that reached ``done`` inside the window, and (employee, competence) pairs
    scoring higher now than they did before the window opened.

    Deliberately separate from the ``closed`` stage: that one counts gaps
    crossing the passing bar in a fixed 90-day window and is what the loop is
    graded on. This one answers "did the last quarter change anything", which
    a competence climbing 40 to 55 does even though no bar was crossed.
    """
    window_start = (now or datetime.now(UTC)) - timedelta(days=days)
    # Both halves of the tile count the same population: active employees.
    # Without the filter a terminated employee's finished plan still raised
    # plans_completed while their competences could never raise the other
    # number (review finding).
    plans_completed = sum(
        1
        for r in facts.pdp_rows
        if r.status == "done"
        and r.finished_at is not None
        and r.finished_at >= window_start
        and r.employee_id in facts.active_by_id
    )
    done_by_employee: dict[uuid.UUID, list[Row]] = {}
    for row in facts.done_rows:
        if row.employee_id in facts.active_by_id:
            done_by_employee.setdefault(row.employee_id, []).append(row)
    competences_improved = 0
    for rows in done_by_employee.values():
        inside, before = split_by_window(rows, window_start)
        competences_improved += len(
            improved_against_previous(inside, before, facts.results_by_assessment)
        )
    return {
        "days": days,
        "plans_completed": plans_completed,
        "competences_improved": competences_improved,
    }


def issue_cohorts(facts: IssueFacts) -> dict[IssueCode, set[uuid.UUID]]:
    """Employee ids per issue code — the filter and the badges read this."""
    return {
        "competence_gap": facts.gap_employees,
        "gaps_without_plan": facts.gap_employees - facts.open_pdp_employees,
        "pdp_overdue": facts.overdue_employees,
        "pdp_stuck_review": facts.stuck_employees,
        "assessment_stale": set(facts.active_by_id) - facts.assessed_recent,
    }


def issues_by_employee(
    cohorts: dict[IssueCode, set[uuid.UUID]],
) -> dict[uuid.UUID, list[IssueCode]]:
    """Invert the cohorts into per-employee code lists.

    ``gaps_without_plan`` implies ``competence_gap``, so the broader code is
    dropped when the narrower one fires — two badges saying the same thing
    twice is noise. The filter still matches both: suppression is a display
    rule, applied here rather than in ``issue_cohorts``.
    """
    out: dict[uuid.UUID, list[IssueCode]] = {}
    without_plan = cohorts.get("gaps_without_plan", set())
    for code in ISSUE_CODES:
        if code == "competence_gap":
            members = cohorts.get(code, set()) - without_plan
        else:
            members = cohorts.get(code, set())
        for emp_id in members:
            out.setdefault(emp_id, []).append(code)
    return out


# Display order for the combined badge list: how urgent the problem is,
# not which module computed it. The employee list sorts by this so a row's
# first badge is the one worth acting on.
ISSUE_PRIORITY: tuple[str, ...] = (
    "user_inactive",
    "profile_incomplete",
    "pdp_overdue",
    "gaps_without_plan",
    "competence_gap",
    "assessment_overdue",
    "pdp_stuck_review",
    "assessment_pending",
    "pdp_pending_review",
    "assessment_stale",
)


# HRP-720: "there is a problem -> what was done -> when does it resolve?".
# Only the codes whose resolution is actually scheduled carry a date: a plan
# has a deadline, an open assessment has an end date. A competence gap, the
# hygiene codes and a finalisation waiting on the initiator
# (``assessment_pending``) resolve when somebody acts, and inventing a date for
# them would be a promise the system cannot keep.


def issue_deadlines(
    facts: IssueFacts, employee_id: uuid.UUID, codes: Sequence[str]
) -> dict[str, date]:
    """Per-code resolution date for one employee; codes without one are absent.

    Each code reads the date of the thing that raised it, so two codes on
    one card can name two different plans. ``assessment_stale`` with nothing
    scheduled ahead stays undated on purpose — "nothing has been done yet" is
    the honest answer, and a badge reading "due <today>" or pointing at a date
    already missed would say the opposite.
    """
    sources: dict[str, dict[uuid.UUID, date]] = {
        "pdp_overdue": facts.pdp_overdue_deadline,
        "pdp_stuck_review": facts.pdp_stuck_deadline,
        "pdp_pending_review": facts.pdp_pending_deadline,
        "assessment_overdue": facts.assessment_overdue_deadline,
        "assessment_stale": facts.assessment_next_deadline,
    }
    out: dict[str, date] = {}
    for code in codes:
        due = sources.get(code, {}).get(employee_id)
        if due is not None:
            out[code] = due
    return out


# HRP-729: how bad one person's problem is, so the queue chips and the
# ``?issue=`` list can lead with whoever needs a human first.
#
# One comparator, one place. Scores are comparable only WITHIN a code —
# 342 "gap" points and 21 "days stuck" are different units, and nothing
# sorts the codes against each other (the queue's chip order is fixed).
#
# The gap score reads ``gap_count`` / ``gap_worst_depth``, both filled by
# the same branch that decides whether a result is below the bar, so a
# change to that rule carries over without a second comparison here.
#
# Never assessed outranks assessed-long-ago (decision on HRP-729,
# 06.09.2026): no measurement at all is the worse state. Flipping that is
# a one-line change to ``_NEVER_ASSESSED_DAYS``.
_GAP_COUNT_WEIGHT = 100
_NEVER_ASSESSED_DAYS = 10**6


def issue_severity(
    facts: IssueFacts,
    employee_id: uuid.UUID,
    code: str,
    *,
    now: datetime | None = None,
) -> float:
    """Severity of ``code`` for one employee; higher is worse, 0.0 if unknown.

    Every branch is a dict lookup: the counting happens once, in the pass that
    built ``facts``. ``now`` is only consulted for staleness, which is measured
    against read time rather than collection time.
    """
    if code in ("gaps_without_plan", "competence_gap"):
        count = facts.gap_count.get(employee_id, 0)
        if not count:
            return 0.0
        # Count dominates, depth breaks ties: three competences below the
        # bar is a bigger hole than one competence that sank further.
        return float(
            count * _GAP_COUNT_WEIGHT + facts.gap_worst_depth.get(employee_id, 0)
        )
    if code == "pdp_overdue":
        return float(facts.pdp_overdue_days.get(employee_id, 0))
    if code == "pdp_stuck_review":
        return float(facts.pdp_stuck_days.get(employee_id, 0))
    if code in ("assessment_stale", "assessment_coverage"):
        now = now or datetime.now(UTC)
        row = facts.latest_done.get(employee_id)
        if row is None or row.finished_at is None:
            return float(_NEVER_ASSESSED_DAYS)
        return float((now - row.finished_at).days)
    return 0.0


def sort_by_severity(
    facts: IssueFacts,
    employees: Sequence[Employee],
    codes: Sequence[str],
    *,
    now: datetime | None = None,
) -> list[Employee]:
    """Worst first; equal severity keeps last name / id order so the list is stable.

    ``codes`` is normally a single code. Passing several ranks each employee by
    their worst one, which mixes units and is why callers fall back to another
    ordering rather than asking for that.
    """
    now = now or datetime.now(UTC)
    return sorted(
        employees,
        key=lambda e: (
            -max((issue_severity(facts, e.id, c, now=now) for c in codes), default=0.0),
            e.user.last_name if e.user else "",
            str(e.id),
        ),
    )
