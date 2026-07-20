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
from typing import Literal

from sqlalchemy import select
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
    """Resolve alerts for a list of employees with at most three DB round-trips.

    All rows that contribute to an alert are filtered by ``tenant_id`` as
    defence-in-depth so a mixed-tenant cohort can never leak rows across
    tenants. Returns a dict ``{employee_id: alert_code | None}``; missing keys
    can be treated as "no alert".
    """
    if not employees:
        return {}

    now = now or datetime.now(timezone.utc)
    # Drop any employees from a different tenant before they participate in
    # the priority scan — same defence-in-depth principle as the SQL filters.
    cohort = [e for e in employees if e.tenant_id == tenant_id]
    if not cohort:
        return {e.id: None for e in employees}
    employee_ids = [e.id for e in cohort]

    # --- Round-trip 1: employees with overdue assessments. ---
    overdue_rows = await db.execute(
        select(Assessment.employee_id)
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
    overdue_ids: set[uuid.UUID] = {row[0] for row in overdue_rows.all()}

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
        select(PDP.employee_id)
        .where(
            PDP.tenant_id == tenant_id,
            PDP.employee_id.in_(employee_ids),
            PDP.status.in_(_PDP_REVIEW_STATUSES),
        )
        .group_by(PDP.employee_id)
    )
    pdp_ids: set[uuid.UUID] = {row[0] for row in pdp_rows.all()}

    result: dict[uuid.UUID, AlertCode | None] = {}
    for emp in employees:
        if emp.tenant_id != tenant_id:
            # Off-tenant employees never get an alert — they were excluded
            # from the SQL filters above, so we can't reason about their state.
            result[emp.id] = None
            continue
        if _user_inactive(emp):
            result[emp.id] = "user_inactive"
            continue
        if is_incomplete(emp):
            result[emp.id] = "profile_incomplete"
            continue
        if emp.id in overdue_ids:
            result[emp.id] = "assessment_overdue"
            continue
        if emp.id in pending_ids:
            result[emp.id] = "assessment_pending"
            continue
        if emp.id in pdp_ids:
            result[emp.id] = "pdp_pending_review"
            continue
        result[emp.id] = None

    return result


# Stable label map; UI may localise but the testing layer relies on these keys.
ALERT_LABELS: dict[AlertCode, str] = {
    "user_inactive": "User has no active account",
    "profile_incomplete": "Employee profile is incomplete",
    "assessment_overdue": "Assessment is overdue",
    "assessment_pending": "Assessment awaiting approval",
    "pdp_pending_review": "Development plan awaiting review",
}
