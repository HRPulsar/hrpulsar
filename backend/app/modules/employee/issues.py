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
from datetime import UTC, datetime, timedelta
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
            if res.percent < prev_bar and res.competence_id in passed_now:
                closed.add(res.competence_id)
    return closed


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
    ).where(PDP.tenant_id == tenant_id)
    if cohort is not None:
        # Narrow on the active set actually loaded, not on the requested
        # cohort: a requested id that is terminated or off-tenant carries
        # no issues, and its rows would only be discarded downstream.
        loaded = set(active_by_id)
        done_q = done_q.where(Assessment.employee_id.in_(loaded))
        results_q = results_q.where(Assessment.employee_id.in_(loaded))
        pdp_q = pdp_q.where(PDP.employee_id.in_(loaded))

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
    for emp_id, row in latest_done.items():
        bar = passing_bar(row.passing_score)
        for res in results_by_assessment.get(row.id, []):
            if res.percent < bar:
                gap_employees.add(emp_id)
                gap_competences += 1

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
            if res.percent >= latest_bar
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
    plans_done_on_time = sum(
        1
        for r in pdp_rows
        if r.status == "done"
        and r.finished_at is not None
        and r.finished_at >= closed_cutoff
        and r.deadline is not None
        and r.finished_at <= r.deadline
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
    )


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
