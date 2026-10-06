"""Employee status alerts (POS6).

Resolves a single alert code per employee using the product-spec priority
scale. The first rule that fires wins:

1. ``user_inactive``        — Employee has no User or ``User.is_active`` is False.
2. ``profile_incomplete``   — Anchor profile fields are missing
                               (see :mod:`employee.profile_completeness`).
3. ``assessment_overdue``   — At least one Assessment in (sent, in_progress) has
                               passed ``ended_at``.
4. ``assessment_pending``   — At least one Assessment is in the ``await_result``
                               status (initiator finalisation pending).
5. ``pdp_pending_review``   — At least one PDP is in ``review``.

The bulk variant fetches all per-employee state in three aggregated queries so
listing N employees stays O(1) round-trips, not O(N).

Tenant isolation is enforced at this layer regardless of how the cohort was
assembled: every query filters `tenant_id` even though the caller is expected
to pass employees from the active tenant. This is defence-in-depth against
mixed-tenant cohorts leaking across tenant boundaries.

Loading note: ``_user_inactive`` reads ``emp.user.is_active``.
``Employee.user`` is declared with ``lazy="selectin"`` in the ORM, so the
relationship is batch-loaded by a single extra round-trip when the cohort is
selected. If that lazy strategy ever changes to ``lazy="select"`` callers must
add an explicit ``selectinload(Employee.user)`` before invoking the resolver,
or this becomes N+1 on user-loading.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, get_args

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assessment.models import PDP, Assessment, AssessmentStatus
from app.modules.employee.models import Employee
from app.modules.employee.profile_completeness import is_incomplete

AlertCode = Literal[
    "user_inactive",
    "profile_incomplete",
    "assessment_overdue",
    "assessment_pending",
    "pdp_pending_review",
]

# Codes ordered from highest to lowest priority. Tests rely on this ordering.
ALERT_PRIORITY: tuple[AlertCode, ...] = (
    "user_inactive",
    "profile_incomplete",
    "assessment_overdue",
    "assessment_pending",
    "pdp_pending_review",
)

# HRP-729 REDO: the hygiene codes the ``?issue=`` employee filter accepts next
# to the development-loop ones. Each has a "since when" that orders the list
# oldest first (see ``scan_employee_alerts``); ``user_inactive`` and
# ``assessment_pending`` stay display-only.
FilterableAlertCode = Literal[
    "profile_incomplete",
    "pdp_pending_review",
    "assessment_overdue",
]
FILTERABLE_ALERT_CODES: tuple[FilterableAlertCode, ...] = get_args(FilterableAlertCode)

# Assessment status codes the alerts depend on.
_OVERDUE_STATUS_CODES = ("sent", "in_progress")
_PENDING_APPROVAL_STATUS_CODES = ("await_result",)

# PDP statuses that count as "waiting for review".
# HRP-16: ``on_approval`` was removed from the status model — ``review`` is
# the only "pending admin action" state left.
_PDP_REVIEW_STATUSES = ("review",)


def _user_inactive(emp: Employee) -> bool:
    user = getattr(emp, "user", None)
    if user is None:
        return True
    return not bool(user.is_active)


async def compute_employee_alert(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    emp: Employee,
    *,
    now: datetime | None = None,
) -> AlertCode | None:
    """Resolve the highest-priority alert for a single employee."""
    bulk = await compute_employee_alerts_bulk(db, tenant_id, [emp], now=now)
    return bulk.get(emp.id)


async def compute_employee_alerts_bulk(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employees: list[Employee],
    *,
    now: datetime | None = None,
) -> dict[uuid.UUID, AlertCode | None]:
    """Resolve the single highest-priority alert per employee.

    Returns a dict ``{employee_id: alert_code | None}``; missing keys can be
    treated as "no alert".
    """
    every = await compute_employee_alerts_bulk_all(db, tenant_id, employees, now=now)
    return {emp_id: (codes[0] if codes else None) for emp_id, codes in every.items()}


async def compute_employee_alerts_bulk_all(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employees: list[Employee],
    *,
    now: datetime | None = None,
) -> dict[uuid.UUID, list[AlertCode]]:
    """Every alert that fires per employee, in ``ALERT_PRIORITY`` order.

    Three DB round-trips regardless of cohort size. All rows that contribute
    to an alert are filtered by ``tenant_id`` as defence-in-depth so a
    mixed-tenant cohort can never leak rows across tenants.

    HRP-638: the employee list shows every problem a row has, so the scan
    collects them all; ``compute_employee_alerts_bulk`` narrows that back to
    the top one for the single-badge callers (position and specialization
    drill-downs), whose contract is unchanged.
    """
    scan = await scan_employee_alerts(db, tenant_id, employees, now=now)
    return {emp_id: list(found) for emp_id, found in scan.items()}


async def scan_employee_alerts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employees: list[Employee],
    *,
    now: datetime | None = None,
) -> dict[uuid.UUID, dict[AlertCode, datetime | None]]:
    """Every alert per employee, in ``ALERT_PRIORITY`` order, with since when.

    The date is what the ``?issue=`` list orders a filterable code by, oldest
    first (HRP-729 REDO): the earliest missed end date for
    ``assessment_overdue``, the earliest last move of a plan in review for
    ``pdp_pending_review`` (the clock ``pdp_stuck_review`` already uses), and
    the date the employee was added for ``profile_incomplete``. The other two
    codes carry ``None``. Same three round-trips — the dates are aggregates
    of the rows the predicates already select.
    """
    if not employees:
        return {}

    now = now or datetime.now(timezone.utc)
    # Drop any employees from a different tenant before they participate in
    # the priority scan — same defence-in-depth principle as the SQL filters.
    cohort = [e for e in employees if e.tenant_id == tenant_id]
    if not cohort:
        return {e.id: {} for e in employees}
    employee_ids = [e.id for e in cohort]

    # --- Round-trip 1: employees with overdue assessments. ---
    overdue_rows = await db.execute(
        select(Assessment.employee_id, func.min(Assessment.ended_at))
        .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
        .where(
            Assessment.tenant_id == tenant_id,
            Assessment.employee_id.in_(employee_ids),
            AssessmentStatus.code.in_(_OVERDUE_STATUS_CODES),
            Assessment.ended_at.is_not(None),
            Assessment.ended_at < now,
        )
        .group_by(Assessment.employee_id)
    )
    overdue_since: dict[uuid.UUID, datetime | None] = dict(overdue_rows.tuples().all())

    # --- Round-trip 2: employees with pending-approval assessments. ---
    pending_rows = await db.execute(
        select(Assessment.employee_id)
        .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
        .where(
            Assessment.tenant_id == tenant_id,
            Assessment.employee_id.in_(employee_ids),
            AssessmentStatus.code.in_(_PENDING_APPROVAL_STATUS_CODES),
        )
        .group_by(Assessment.employee_id)
    )
    pending_ids: set[uuid.UUID] = {row[0] for row in pending_rows.all()}

    # --- Round-trip 3: employees with PDPs in review. ---
    pdp_rows = await db.execute(
        select(PDP.employee_id, func.min(PDP.updated_at))
        .where(
            PDP.tenant_id == tenant_id,
            PDP.employee_id.in_(employee_ids),
            PDP.status.in_(_PDP_REVIEW_STATUSES),
        )
        .group_by(PDP.employee_id)
    )
    review_since: dict[uuid.UUID, datetime | None] = dict(pdp_rows.tuples().all())

    result: dict[uuid.UUID, dict[AlertCode, datetime | None]] = {}
    for emp in employees:
        if emp.tenant_id != tenant_id:
            # Off-tenant employees never get an alert — they were excluded
            # from the SQL filters above, so we can't reason about their state.
            result[emp.id] = {}
            continue
        found: dict[AlertCode, datetime | None] = {}
        if _user_inactive(emp):
            found["user_inactive"] = None
        if is_incomplete(emp):
            found["profile_incomplete"] = emp.created_at
        if emp.id in overdue_since:
            found["assessment_overdue"] = overdue_since[emp.id]
        if emp.id in pending_ids:
            found["assessment_pending"] = None
        if emp.id in review_since:
            found["pdp_pending_review"] = review_since[emp.id]
        # Inserted in ALERT_PRIORITY order above, so the keys are already
        # sorted and the first is what the single-alert callers expect.
        result[emp.id] = found

    return result


# Stable label map; UI may localise but the testing layer relies on these keys.
ALERT_LABELS: dict[AlertCode, str] = {
    "user_inactive": "User has no active account",
    "profile_incomplete": "Employee profile is incomplete",
    "assessment_overdue": "Assessment is overdue",
    "assessment_pending": "Assessment awaiting approval",
    "pdp_pending_review": "Development plan awaiting review",
}
