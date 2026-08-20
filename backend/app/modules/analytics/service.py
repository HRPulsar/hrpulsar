"""Analytics service — assessment / PDP / compensation aggregates.

Every public function in this module takes a ``tenant_id`` parameter
and scopes its SELECT/JOIN tree to that tenant. Public-demo sandboxes
(``Tenant.is_demo=True``) are therefore isolated from paying tenants
by construction — there is no cross-tenant aggregation here, so an
explicit ``~Tenant.is_demo`` filter would be a no-op. If a future
function ever crosses the tenant boundary (e.g. a platform-wide
benchmark), it MUST join ``tenants`` and filter
``Tenant.is_demo.is_(False)`` to keep demo data out of the paid view.
See ``backend/tests/unit/test_demo_analytics_isolation.py`` for the
regression test that pins this contract.
"""

import hashlib
import io
import json
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fastapi import status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, exception_summary
from app.core.redis import redis_client
from app.modules.assessment.models import (
    CPA,
    PDP,
    Assessment,
    AssessmentParticipant,
    AssessmentResult,
    AssessmentStatus,
    PDPVersion,
)
from app.modules.assessment.pdp_service import PDP_FINALIZED_STATUSES
from app.modules.auth.models import User
from app.modules.company.models import Division, SpecializationDivision
from app.modules.competence.models import Competence
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Compensation, Employee
from app.modules.grade_system.models import GradeCompetenceLink, GradeSpecialization

logger = logging.getLogger(__name__)


async def assessment_stats(db: AsyncSession, tenant_id: uuid.UUID) -> dict:

    # Count by status
    result = await db.execute(
        select(AssessmentStatus.code, func.count(Assessment.id))
        .join(Assessment, Assessment.status_id == AssessmentStatus.id)
        .where(Assessment.tenant_id == tenant_id)
        .group_by(AssessmentStatus.code)
    )
    by_status: dict[str, int] = dict(result.all())  # type: ignore[arg-type]

    total = sum(by_status.values())

    # Avg score for completed
    avg_result = await db.execute(
        select(func.avg(AssessmentResult.avg_score))
        .join(Assessment, Assessment.id == AssessmentResult.assessment_id)
        .where(Assessment.tenant_id == tenant_id)
    )
    avg_score = avg_result.scalar()

    return {
        "total": total,
        "by_status": by_status,
        "avg_score": round(avg_score, 2) if avg_score else None,
    }


async def pdp_stats(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    result = await db.execute(
        select(PDP.status, func.count(PDP.id))
        .where(PDP.tenant_id == tenant_id)
        .group_by(PDP.status)
    )
    by_status: dict[str, int] = dict(result.all())  # type: ignore[arg-type]

    avg_result = await db.execute(
        select(func.avg(PDP.total_progress)).where(PDP.tenant_id == tenant_id)
    )
    avg_progress = avg_result.scalar()

    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "avg_progress": round(avg_progress, 1) if avg_progress else 0,
    }


async def compensation_stats(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Compensation analytics: avg salary by division, by grade, totals by type."""

    # Total compensation by type
    type_result = await db.execute(
        select(
            Compensation.type,
            func.sum(Compensation.amount),
            func.avg(Compensation.amount),
            func.count(Compensation.id),
        )
        .join(Employee, Employee.id == Compensation.employee_id)
        .where(Employee.tenant_id == tenant_id, Compensation.end_date.is_(None))
        .group_by(Compensation.type)
    )
    by_type = {}
    for comp_type, total, avg, cnt in type_result.all():
        by_type[comp_type] = {
            "total": int(total),
            "avg": round(float(avg), 2),
            "count": int(cnt),
        }

    # Avg salary by division (active salary records only)
    div_result = await db.execute(
        select(
            Division.id,
            Division.name,
            func.avg(Compensation.amount),
            func.count(Compensation.id),
        )
        .join(Employee, Employee.division_id == Division.id)
        .join(Compensation, Compensation.employee_id == Employee.id)
        .where(
            Employee.tenant_id == tenant_id,
            Compensation.type == "salary",
            Compensation.end_date.is_(None),
        )
        .group_by(Division.id, Division.name)
    )
    by_division = [
        {
            "division_id": str(div_id),
            "division_name": name,
            "avg_salary": round(float(avg), 2),
            "count": int(cnt),
        }
        for div_id, name, avg, cnt in div_result.all()
    ]

    # Overall stats
    overall = await db.execute(
        select(
            func.count(Compensation.id),
            func.sum(Compensation.amount),
            func.avg(Compensation.amount),
        )
        .join(Employee, Employee.id == Compensation.employee_id)
        .where(Employee.tenant_id == tenant_id, Compensation.end_date.is_(None))
    )
    row = overall.one()
    total_count = int(row[0] or 0)
    total_amount = int(row[1] or 0)
    overall_avg = round(float(row[2]), 2) if row[2] else 0

    return {
        "total_records": total_count,
        "total_amount": total_amount,
        "overall_avg": overall_avg,
        "by_type": by_type,
        "by_division": by_division,
    }


async def export_assessments_xlsx(
    db: AsyncSession, tenant_id: uuid.UUID
) -> StreamingResponse:

    result = await db.execute(
        select(Assessment)
        .where(Assessment.tenant_id == tenant_id)
        .order_by(Assessment.created_at.desc())
    )
    assessments = result.scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Assessments"
    ws.append(["ID", "Title", "Employee ID", "Status", "Created At"])

    for a in assessments:
        ws.append(
            [
                str(a.id),
                a.title or "",
                str(a.employee_id),
                a.status.code if a.status else "",
                a.created_at.isoformat() if a.created_at else "",
            ]
        )

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=assessments.xlsx"},
    )


# ---------------------------------------------------------------------------
# GF5 Improve: Compensation benchmarking by grade/specialization
# ---------------------------------------------------------------------------


async def compensation_benchmark(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Avg salary by grade and by specialization for benchmarking."""
    # By grade
    grade_result = await db.execute(
        select(
            DictionaryItem.id,
            DictionaryItem.title,
            func.avg(Compensation.amount),
            func.count(Compensation.id),
        )
        .join(Employee, Employee.id == Compensation.employee_id)
        .join(Assessment, Assessment.employee_id == Employee.id)
        .join(DictionaryItem, DictionaryItem.id == Assessment.grade_id)
        .where(
            Employee.tenant_id == tenant_id,
            Compensation.type == "salary",
            Compensation.end_date.is_(None),
            Assessment.grade_id.isnot(None),
        )
        .group_by(DictionaryItem.id, DictionaryItem.title)
    )
    by_grade = [
        {
            "grade_id": str(gid),
            "grade_title": title,
            "avg_salary": round(float(avg), 2),
            "count": int(cnt),
        }
        for gid, title, avg, cnt in grade_result.all()
    ]

    # By specialization
    spec_result = await db.execute(
        select(
            DictionaryItem.id,
            DictionaryItem.title,
            func.avg(Compensation.amount),
            func.count(Compensation.id),
        )
        .join(Employee, Employee.id == Compensation.employee_id)
        .join(Assessment, Assessment.employee_id == Employee.id)
        .join(DictionaryItem, DictionaryItem.id == Assessment.specialization_id)
        .where(
            Employee.tenant_id == tenant_id,
            Compensation.type == "salary",
            Compensation.end_date.is_(None),
            Assessment.specialization_id.isnot(None),
        )
        .group_by(DictionaryItem.id, DictionaryItem.title)
    )
    by_specialization = [
        {
            "specialization_id": str(sid),
            "specialization_title": title,
            "avg_salary": round(float(avg), 2),
            "count": int(cnt),
        }
        for sid, title, avg, cnt in spec_result.all()
    ]

    return {"by_grade": by_grade, "by_specialization": by_specialization}


# ---------------------------------------------------------------------------
# GF7 Improve: Division × Specialization matrix with headcounts
# ---------------------------------------------------------------------------


async def division_specialization_matrix(
    db: AsyncSession, tenant_id: uuid.UUID
) -> dict:
    """Matrix of divisions × specializations with employee headcounts."""
    # Get all divisions
    div_result = await db.execute(
        select(Division.id, Division.name).where(Division.tenant_id == tenant_id)
    )
    divisions = [{"id": str(d_id), "name": name} for d_id, name in div_result.all()]

    # Get all specialization-division mappings
    sd_result = await db.execute(
        select(
            SpecializationDivision.division_id,
            SpecializationDivision.specialization_id,
            DictionaryItem.title,
        )
        .join(
            DictionaryItem,
            DictionaryItem.id == SpecializationDivision.specialization_id,
        )
        .where(SpecializationDivision.tenant_id == tenant_id)
    )
    mappings = sd_result.all()

    # Collect unique specializations
    specs_map: dict[str, str] = {}
    for _, spec_id, title in mappings:
        specs_map[str(spec_id)] = title
    specializations = [{"id": sid, "title": title} for sid, title in specs_map.items()]

    # Get employee counts per division
    emp_result = await db.execute(
        select(Employee.division_id, func.count(Employee.id))
        .where(Employee.tenant_id == tenant_id, Employee.status == "active")
        .group_by(Employee.division_id)
    )
    emp_counts: dict[str, int] = {
        str(div_id): cnt for div_id, cnt in emp_result.all() if div_id
    }

    # Build matrix cells
    active_cells: set[tuple[str, str]] = set()
    for div_id, spec_id, _ in mappings:
        active_cells.add((str(div_id), str(spec_id)))

    cells = []
    for d in divisions:
        for s in specializations:
            if (d["id"], s["id"]) in active_cells:
                cells.append(
                    {
                        "division_id": d["id"],
                        "specialization_id": s["id"],
                        "headcount": emp_counts.get(d["id"], 0),
                        "active": True,
                    }
                )

    return {
        "divisions": divisions,
        "specializations": specializations,
        "cells": cells,
    }


# ---------------------------------------------------------------------------
# GF8 Improve: CPA comparison between rounds
# ---------------------------------------------------------------------------


async def compare_cpa_rounds(
    db: AsyncSession, tenant_id: uuid.UUID, cpa_id_1: uuid.UUID, cpa_id_2: uuid.UUID
) -> dict:
    """Compare two CPA rounds: per-employee score changes."""

    async def _cpa_scores(cpa_id: uuid.UUID) -> dict:
        result = await db.execute(
            select(
                Assessment.employee_id,
                func.avg(AssessmentResult.avg_score).label("avg_score"),
            )
            .join(AssessmentResult, AssessmentResult.assessment_id == Assessment.id)
            .where(Assessment.cpa_id == cpa_id, Assessment.tenant_id == tenant_id)
            .group_by(Assessment.employee_id)
        )
        return {str(emp_id): round(float(avg), 2) for emp_id, avg in result.all()}

    scores_1 = await _cpa_scores(cpa_id_1)
    scores_2 = await _cpa_scores(cpa_id_2)

    # Get CPA titles
    cpa1 = await db.get(CPA, cpa_id_1)
    cpa2 = await db.get(CPA, cpa_id_2)

    all_employees = set(scores_1.keys()) | set(scores_2.keys())

    # Get employee names
    name_result = await db.execute(
        select(Employee.id, User.first_name, User.last_name)
        .join(User, User.id == Employee.user_id)
        .where(Employee.tenant_id == tenant_id)
    )
    names = {str(eid): f"{fn} {ln}" for eid, fn, ln in name_result.all()}

    comparisons = []
    for emp_id in sorted(all_employees):
        s1 = scores_1.get(emp_id)
        s2 = scores_2.get(emp_id)
        comparisons.append(
            {
                "employee_id": emp_id,
                "employee_name": names.get(emp_id, "Unknown"),
                "round_1_score": s1,
                "round_2_score": s2,
                "delta": (
                    round(s2 - s1, 2) if s1 is not None and s2 is not None else None
                ),
            }
        )

    return {
        "round_1": {"id": str(cpa_id_1), "title": cpa1.title if cpa1 else ""},
        "round_2": {"id": str(cpa_id_2), "title": cpa2.title if cpa2 else ""},
        "comparisons": comparisons,
    }


# ---------------------------------------------------------------------------
# GF12 Improve: PDP progress over lifecycle (from version history)
# ---------------------------------------------------------------------------


async def pdp_progress_timeline(
    db: AsyncSession, tenant_id: uuid.UUID, pdp_id: uuid.UUID
) -> list[dict]:
    """Return progress snapshots from PDP version history."""
    result = await db.execute(
        select(PDPVersion)
        .join(PDP, PDP.id == PDPVersion.pdp_id)
        .where(PDPVersion.pdp_id == pdp_id, PDP.tenant_id == tenant_id)
        .order_by(PDPVersion.version_number)
    )
    versions = result.scalars().all()

    timeline = []
    for v in versions:
        snapshot = v.snapshot or {}
        items = snapshot.get("items", [])
        total = len(items)
        passed = sum(1 for i in items if i.get("is_passed"))
        timeline.append(
            {
                "version": v.version_number,
                "status": v.status,
                "progress": round(passed / total * 100) if total else 0,
                "total_items": total,
                "passed_items": passed,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
        )

    return timeline


# ---------------------------------------------------------------------------
# Development loop — the dashboard's management view (assess → gaps →
# develop → close) plus rule-based findings that each carry a next action.
# ---------------------------------------------------------------------------

DEV_LOOP_STALE_DAYS = 180
DEV_LOOP_STUCK_REVIEW_DAYS = 14
DEV_LOOP_CLOSED_WINDOW_DAYS = 90
DEV_LOOP_DEFAULT_PASSING = 75
_FINDING_EMPLOYEE_LIMIT = 5


def _passing_bar(passing_score: int | None) -> int:
    # Identity check, not truthiness: 0 is a legitimate stored bar
    # ("no bar") and must not silently become the default 75.
    return DEV_LOOP_DEFAULT_PASSING if passing_score is None else passing_score


def _employee_display(emp: Employee) -> dict:
    user = emp.user
    name = f"{user.first_name} {user.last_name}".strip() if user else ""
    return {
        "id": str(emp.id),
        "name": name,
        "division": emp.division.name if emp.division else None,
    }


async def _active_done_results(
    db: AsyncSession, tenant_id: uuid.UUID
) -> tuple[dict[uuid.UUID, Employee], Sequence[Row], dict[uuid.UUID, list[Row]]]:
    """Active employees, the tenant's done assessments (newest first) and
    per-competence results for the done assessments of active employees.

    Shared between the company ``dev_loop`` and the personal ``my_loop``
    (ponytail: reduced in Python — a couple of rows per employee, fine at
    dashboard scale).
    """
    active_employees = (
        (
            await db.execute(
                select(Employee).where(
                    Employee.tenant_id == tenant_id, Employee.status == "active"
                )
            )
        )
        .scalars()
        .all()
    )
    active_by_id = {e.id: e for e in active_employees}

    done_rows = (
        await db.execute(
            select(
                Assessment.id,
                Assessment.employee_id,
                Assessment.finished_at,
                Assessment.passing_score,
            )
            .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
            .where(Assessment.tenant_id == tenant_id, AssessmentStatus.code == "done")
            .order_by(
                Assessment.finished_at.desc().nulls_last(), Assessment.id.desc()
            )
        )
    ).all()

    # Join instead of expanding done ids into an IN list: the id set is the
    # tenant's whole assessment history, and one bind param per id caps out
    # at asyncpg's 65535 limit long before a big tenant does.
    results_by_assessment: dict[uuid.UUID, list[Row]] = {}
    result_rows = (
        await db.execute(
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
    ).all()
    for res in result_rows:
        results_by_assessment.setdefault(res.assessment_id, []).append(res)
    return active_by_id, done_rows, results_by_assessment


def _latest_done_by_employee(
    done_rows: Sequence[Row], employee_ids: dict | set
) -> dict[uuid.UUID, Row]:
    """First (newest) done row per employee, restricted to ``employee_ids``."""
    latest: dict[uuid.UUID, Row] = {}
    for row in done_rows:
        if row.employee_id in employee_ids and row.employee_id not in latest:
            latest[row.employee_id] = row
    return latest


def _closed_against_previous(
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
        prev_bar = _passing_bar(prev.passing_score)
        for res in results_by_assessment.get(prev.id, []):
            if res.competence_id in seen:
                continue
            seen.add(res.competence_id)
            if res.percent < prev_bar and res.competence_id in passed_now:
                closed.add(res.competence_id)
    return closed


async def dev_loop(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Development-loop stages + actionable findings for the dashboard.

    Returns machine codes only — all user-facing text is rendered by the
    frontend i18n layer. ``data_version`` fingerprints the derived state
    so the AI-summary cache can detect "same data, same summary".
    """
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=DEV_LOOP_STALE_DAYS)
    stuck_cutoff = now - timedelta(days=DEV_LOOP_STUCK_REVIEW_DAYS)
    closed_cutoff = now - timedelta(days=DEV_LOOP_CLOSED_WINDOW_DAYS)

    active_by_id, done_rows, results_by_assessment = await _active_done_results(
        db, tenant_id
    )
    total_active = len(active_by_id)

    latest_done = _latest_done_by_employee(done_rows, active_by_id)

    assessed_recent = {
        emp_id
        for emp_id, row in latest_done.items()
        if row.finished_at is not None and row.finished_at >= stale_cutoff
    }

    # Gaps: results below the bar in the employee's latest done assessment.
    gap_employees: set[uuid.UUID] = set()
    gap_competences = 0
    for emp_id, row in latest_done.items():
        bar = _passing_bar(row.passing_score)
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
        latest_bar = _passing_bar(latest.passing_score)
        passed_now = {
            res.competence_id
            for res in results_by_assessment.get(latest.id, [])
            if res.percent >= latest_bar
        }
        earlier = [r for r in done_by_employee[emp_id] if r.id != latest.id]
        gaps_closed += len(
            _closed_against_previous(passed_now, earlier, results_by_assessment)
        )

    pdp_rows = (
        await db.execute(
            select(
                PDP.employee_id,
                PDP.status,
                PDP.deadline,
                PDP.updated_at,
                PDP.finished_at,
            ).where(PDP.tenant_id == tenant_id)
        )
    ).all()
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

    gaps_without_plan = gap_employees - open_pdp_employees
    uncovered = total_active - len(assessed_recent)

    def _employees_for(ids: set[uuid.UUID]) -> list[dict]:
        picked = [active_by_id[i] for i in ids if i in active_by_id]
        picked.sort(key=lambda e: (e.user.last_name if e.user else "", str(e.id)))
        return [_employee_display(e) for e in picked[:_FINDING_EMPLOYEE_LIMIT]]

    findings: list[dict] = []
    if gaps_without_plan:
        findings.append(
            {
                "code": "gaps_without_plan",
                "severity": "alert",
                "count": len(gaps_without_plan),
                "employees": _employees_for(gaps_without_plan),
                "href": "/development",
            }
        )
    if overdue_employees:
        findings.append(
            {
                "code": "pdp_overdue",
                "severity": "alert",
                "count": len(overdue_employees),
                "employees": _employees_for(overdue_employees),
                "href": "/development",
            }
        )
    if stuck_employees:
        findings.append(
            {
                "code": "pdp_stuck_review",
                "severity": "warn",
                "count": len(stuck_employees),
                "employees": _employees_for(stuck_employees),
                "href": "/development",
            }
        )
    if total_active > 0 and uncovered > 0:
        findings.append(
            {
                "code": "assessment_coverage",
                "severity": "info",
                "count": uncovered,
                "employees": [],
                "href": "/assessments",
            }
        )

    payload = {
        "stages": {
            "assessed": {
                "covered": len(assessed_recent),
                "total_active": total_active,
                "percent": (
                    round(len(assessed_recent) / total_active * 100)
                    if total_active
                    else 0
                ),
            },
            "gaps": {
                "employees": len(gap_employees),
                "competences": gap_competences,
            },
            "developing": {
                "open_pdps": open_pdp_count,
                "gap_employees_with_plan": len(gap_employees & open_pdp_employees),
            },
            "closed": {
                "gaps_closed_90d": gaps_closed,
                "plans_done_on_time_90d": plans_done_on_time,
            },
        },
        "findings": findings,
    }
    payload["data_version"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return payload


# --- On-demand AI summary over the loop snapshot ---

_AI_SUMMARY_TTL_SECONDS = 7 * 24 * 3600
# The summaries are free (BILLING_EXEMPT), so a per-tenant daily cap is the
# spend guard: without it a cheap billable mutation + regenerate loop could
# farm unlimited LLM calls (review finding). Cache hits never consume it.
# The cap scales with headcount — legitimate demand is proportional to the
# people whose loops change, and active employees are the one input that
# cannot be inflated for free (employee.create is a billable mutation).
_AI_SUMMARY_DAILY_BASE = 20
_AI_SUMMARY_DAILY_PER_EMPLOYEE = 2
# Fairness partition inside the tenant pool: the endpoints are free for
# every logged-in user, so without a per-caller slice one enthusiastic
# clicker could drain the whole tenant's daily budget for everyone else.
_AI_SUMMARY_DAILY_PER_USER = 20


def _ai_summary_cache_key(
    tenant_id: uuid.UUID,
    language: str,
    fingerprint: str,
    *,
    user_id: uuid.UUID | None = None,
) -> str:
    # Language is part of the key: switching the tenant's AI content
    # language must not serve a week of stale summaries in the old one.
    # ``user_id`` scopes the personal (my-loop) summaries per person.
    scope = f"{tenant_id}:{user_id}" if user_id is not None else str(tenant_id)
    return f"ai_summary:{scope}:{language}:{fingerprint}"


async def _summary_cache_get(key: str, label: str) -> str | None:
    try:
        async with redis_client() as r:
            return await r.get(key)
    except Exception:  # noqa: BLE001 - cache is best-effort, fail open
        logger.warning("%s AI summary cache read failed", label, exc_info=True)
        return None


async def _summary_cache_put(key: str, summary: str, label: str) -> None:
    try:
        async with redis_client() as r:
            await r.setex(key, _AI_SUMMARY_TTL_SECONDS, summary)
    except Exception:  # noqa: BLE001 - cache is best-effort, fail open
        logger.warning("%s AI summary cache write failed", label, exc_info=True)


async def _consume_ai_summary_budget(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """INCR the tenant's and the caller's daily counters; 429 above a cap.

    Tenant cap = BASE + PER_EMPLOYEE × active employees, computed per
    call — it only runs on cache misses, so the extra COUNT is negligible.
    The per-user cap is a flat constant. Redis being down degrades open
    (matching the cache contract) — the abuse vector needs a healthy
    Redis anyway, and a cache outage must not dark-launch the feature.
    """
    tenant_count = user_count = None
    try:
        async with redis_client() as client:
            day = f"{datetime.now(UTC):%Y%m%d}"
            tenant_key = f"ai_summary_budget:{tenant_id}:{day}"
            user_key = f"ai_summary_budget:{tenant_id}:{user_id}:{day}"
            async with client.pipeline(transaction=True) as pipe:
                pipe.incr(tenant_key)
                pipe.expire(tenant_key, 86400)
                pipe.incr(user_key)
                pipe.expire(user_key, 86400)
                tenant_count, _, user_count, _ = await pipe.execute()
    except Exception:  # noqa: BLE001 - budget is best-effort, fail open
        logger.warning("ai-summary budget check failed, allowing", exc_info=True)
        return
    if user_count is not None and user_count > _AI_SUMMARY_DAILY_PER_USER:
        raise AppError(
            "ai_summary_rate_limited", status.HTTP_429_TOO_MANY_REQUESTS
        )
    if tenant_count is None:
        return
    active = (
        await db.execute(
            select(func.count(Employee.id)).where(
                Employee.tenant_id == tenant_id, Employee.status == "active"
            )
        )
    ).scalar_one()
    cap = _AI_SUMMARY_DAILY_BASE + _AI_SUMMARY_DAILY_PER_EMPLOYEE * active
    if tenant_count > cap:
        raise AppError(
            "ai_summary_rate_limited", status.HTTP_429_TOO_MANY_REQUESTS
        )


async def generate_dev_loop_summary(
    db: AsyncSession, tenant_id: uuid.UUID, payload: dict
) -> str:
    """The actual LLM call — free by design (see BILLING_EXEMPT rationale)."""
    from app.modules.ai import llm_client, prompts
    from app.modules.ai_settings import service as ai_settings_service

    tenant_settings = await ai_settings_service.get_or_default(db, tenant_id)
    prompt = prompts.DEV_LOOP_SUMMARY.format(
        payload=json.dumps(
            {k: payload[k] for k in ("stages", "findings")}, indent=2, default=str
        )
    )
    try:
        summary = await llm_client.generate(
            prompt,
            system=prompts.build_system_dev_loop(tenant_settings),
            tenant_settings=tenant_settings,
            db=db,
        )
    except Exception as e:
        logger.exception("Failed to generate dev-loop summary")
        raise AppError(
            "llm_generation_failed",
            status.HTTP_502_BAD_GATEWAY,
            error=exception_summary(e),
        )
    return summary.strip()


async def _tenant_content_language(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    from app.modules.ai_settings import service as ai_settings_service

    settings_row = await ai_settings_service.get_or_default(db, tenant_id)
    return settings_row.content_language


async def dev_loop_ai_summary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    client_fingerprint: str | None = None,
) -> dict:
    """Cache dispatcher: one generation per distinct loop state.

    The summary is keyed by the ``data_version`` fingerprint — repeat
    requests over unchanged data return the cached text without an LLM
    call. When the client sends the fingerprint it got from the GET, a
    cache hit skips the whole aggregation pass; the text then matches
    the exact state the user is looking at. Redis being down degrades
    to plain generation (fail open).
    """
    language = await _tenant_content_language(db, tenant_id)
    if client_fingerprint:
        cached = await _summary_cache_get(
            _ai_summary_cache_key(tenant_id, language, client_fingerprint),
            "dev-loop",
        )
        if cached:
            return {
                "summary": cached,
                "cached": True,
                "data_version": client_fingerprint,
            }

    payload = await dev_loop(db, tenant_id)
    fingerprint = payload["data_version"]
    key = _ai_summary_cache_key(tenant_id, language, fingerprint)

    cached = await _summary_cache_get(key, "dev-loop")
    if cached:
        return {"summary": cached, "cached": True, "data_version": fingerprint}

    await _consume_ai_summary_budget(db, tenant_id, user_id)
    summary = await generate_dev_loop_summary(db, tenant_id, payload)
    await _summary_cache_put(key, summary, "dev-loop")
    return {"summary": summary, "cached": False, "data_version": fingerprint}


# ---------------------------------------------------------------------------
# Personal development loop — the employee's own dashboard (HRP-612 wave 2).
# ---------------------------------------------------------------------------

DEV_LOOP_DEADLINE_SOON_DAYS = 14
_RARE_SKILL_MAX_HOLDERS = 2
_STRENGTHS_TOP = 3


def _dict_item_display(item: DictionaryItem | None) -> dict | None:
    if item is None:
        return None
    return {
        "id": str(item.id),
        "type": item.type,
        "title": item.title,
        "i18n_key": item.i18n_key,
    }


async def my_loop(db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    """Personal development loop for the logged-in employee.

    Read-only mirror of ``dev_loop`` scoped to one person: my stages, my
    action queue, strengths, growth direction and assessment history.
    Machine codes only — the frontend renders all user-facing text.
    """
    employee = (
        await db.execute(
            select(Employee).where(
                Employee.tenant_id == tenant_id, Employee.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if employee is None:
        raise AppError("employee_profile_not_found", status.HTTP_404_NOT_FOUND)

    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=DEV_LOOP_STALE_DAYS)
    closed_cutoff = now - timedelta(days=DEV_LOOP_CLOSED_WINDOW_DAYS)
    soon_cutoff = now + timedelta(days=DEV_LOOP_DEADLINE_SOON_DAYS)

    # My done assessments (newest first) and their results with titles.
    my_done = (
        await db.execute(
            select(
                Assessment.id,
                Assessment.employee_id,
                Assessment.finished_at,
                Assessment.passing_score,
            )
            .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
            .where(
                Assessment.tenant_id == tenant_id,
                Assessment.employee_id == employee.id,
                AssessmentStatus.code == "done",
            )
            .order_by(
                Assessment.finished_at.desc().nulls_last(), Assessment.id.desc()
            )
        )
    ).all()
    my_results: dict[uuid.UUID, list[Row]] = {}
    if my_done:
        rows = (
            await db.execute(
                select(
                    AssessmentResult.assessment_id,
                    AssessmentResult.competence_id,
                    AssessmentResult.percent,
                    Competence.title,
                )
                .join(Competence, Competence.id == AssessmentResult.competence_id)
                .where(
                    AssessmentResult.assessment_id.in_([r.id for r in my_done]),
                    AssessmentResult.percent.is_not(None),
                )
            )
        ).all()
        for res in rows:
            my_results.setdefault(res.assessment_id, []).append(res)
        # Deterministic order: the query has no ORDER BY, and these lists
        # feed the payload whose hash is the AI-summary cache key — a plan
        # flip or row move must not silently invalidate the cache.
        for res_list in my_results.values():
            res_list.sort(key=lambda r: (-r.percent, str(r.competence_id)))

    latest = my_done[0] if my_done else None
    latest_results = my_results.get(latest.id, []) if latest is not None else []
    latest_bar = _passing_bar(latest.passing_score) if latest else None
    latest_by_competence = {r.competence_id: r for r in latest_results}

    def _avg(results: list[Row]) -> int | None:
        return round(sum(r.percent for r in results) / len(results)) if results else None

    # Gaps: below the bar in my latest done assessment.
    gap_items = [
        {"competence_id": str(r.competence_id), "title": r.title, "percent": r.percent}
        for r in sorted(latest_results, key=lambda r: r.percent)
        if r.percent < latest_bar
    ]

    # Confirmed closures (same rule as the company loop, one employee).
    gaps_closed = 0
    if (
        latest is not None
        and latest.finished_at is not None
        and latest.finished_at >= closed_cutoff
    ):
        passed_now = {
            r.competence_id for r in latest_results if r.percent >= latest_bar
        }
        gaps_closed = len(
            _closed_against_previous(passed_now, my_done[1:], my_results)
        )

    # My PDPs.
    my_pdps = (
        (
            await db.execute(
                select(PDP)
                .where(PDP.tenant_id == tenant_id, PDP.employee_id == employee.id)
                .order_by(PDP.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    open_pdps = [p for p in my_pdps if p.status not in PDP_FINALIZED_STATUSES]
    active_pdp = open_pdps[0] if open_pdps else None

    # Personal action queue (wire codes only).
    findings: list[dict] = []
    pending_surveys = (
        (
            await db.execute(
                select(AssessmentParticipant.assessment_id)
                .join(Assessment, Assessment.id == AssessmentParticipant.assessment_id)
                .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
                .where(
                    Assessment.tenant_id == tenant_id,
                    AssessmentParticipant.user_id == user_id,
                    AssessmentParticipant.is_completed.is_(False),
                    # "sent" = dispatched, nobody answered yet — exactly the
                    # state the reminder exists for; the first answer moves
                    # the assessment to "in_progress".
                    AssessmentStatus.code.in_(["sent", "in_progress"]),
                )
                # Deterministic: findings[].href points at [0] and the
                # payload hash is the AI-summary cache key.
                .order_by(AssessmentParticipant.assessment_id)
            )
        )
        .scalars()
        .all()
    )
    if pending_surveys:
        findings.append(
            {
                "code": "survey_pending",
                "severity": "warn",
                "count": len(pending_surveys),
                "href": f"/assessments/{pending_surveys[0]}",
            }
        )
    returned = [p for p in open_pdps if p.status == "returned"]
    if returned:
        findings.append(
            {
                "code": "pdp_returned",
                "severity": "warn",
                "count": len(returned),
                "href": "/development",
            }
        )
    overdue = [
        p for p in open_pdps if p.deadline is not None and p.deadline < now
    ]
    if overdue:
        findings.append(
            {
                "code": "pdp_overdue",
                "severity": "alert",
                "count": len(overdue),
                "href": "/development",
            }
        )
    else:
        soon = [
            p
            for p in open_pdps
            if p.deadline is not None and now <= p.deadline <= soon_cutoff
        ]
        if soon:
            findings.append(
                {
                    "code": "pdp_deadline_soon",
                    "severity": "warn",
                    "count": len(soon),
                    "href": "/development",
                }
            )
    if gap_items and not open_pdps:
        findings.append(
            {
                "code": "gap_without_plan",
                "severity": "alert",
                "count": len(gap_items),
                "href": "/development",
            }
        )
    if (
        latest is None
        or latest.finished_at is None
        or latest.finished_at < stale_cutoff
    ):
        findings.append(
            {
                "code": "assessment_stale",
                "severity": "info",
                "count": 1,
                "href": "/assessments",
            }
        )

    # Strengths: my top competences at/above the bar + rare skills across
    # the tenant. The bar filter mirrors gap_items/rare_skills — without it
    # an all-gaps employee would see their weakest scores praised as
    # strengths (and the coach LLM would congratulate them on failing).
    top = [
        {"competence_id": str(r.competence_id), "title": r.title, "percent": r.percent}
        for r in latest_results
        if r.percent >= latest_bar
    ][:_STRENGTHS_TOP]
    rare_skills: list[dict] = []
    if latest_results:
        # Lean tenant-wide pass: id-only employees, latest done assessment
        # per employee, results for those assessments only — the full
        # ``_active_done_results`` (Employee objects + every historical
        # result) is dashboard-scale overkill here (review finding).
        active_ids = set(
            (
                await db.execute(
                    select(Employee.id).where(
                        Employee.tenant_id == tenant_id,
                        Employee.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        done_rows = (
            await db.execute(
                select(
                    Assessment.id,
                    Assessment.employee_id,
                    Assessment.passing_score,
                )
                .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
                .where(
                    Assessment.tenant_id == tenant_id,
                    AssessmentStatus.code == "done",
                )
                .order_by(
                    Assessment.finished_at.desc().nulls_last(),
                    Assessment.id.desc(),
                )
            )
        ).all()
        tenant_latest = _latest_done_by_employee(done_rows, active_ids)
        holders: dict[uuid.UUID, int] = {}
        if tenant_latest:
            bar_by_assessment = {
                row.id: _passing_bar(row.passing_score)
                for row in tenant_latest.values()
            }
            passed_rows = (
                await db.execute(
                    select(
                        AssessmentResult.assessment_id,
                        AssessmentResult.competence_id,
                        AssessmentResult.percent,
                    ).where(
                        AssessmentResult.assessment_id.in_(bar_by_assessment),
                        AssessmentResult.percent.is_not(None),
                    )
                )
            ).all()
            for passed in passed_rows:
                if passed.percent >= bar_by_assessment[passed.assessment_id]:
                    holders[passed.competence_id] = (
                        holders.get(passed.competence_id, 0) + 1
                    )
        rare_skills = [
            {
                "competence_id": str(r.competence_id),
                "title": r.title,
                "percent": r.percent,
            }
            for r in latest_results
            if r.percent >= latest_bar
            and holders.get(r.competence_id, 0) <= _RARE_SKILL_MAX_HOLDERS
        ]

    # Growth: the next rung on my specialization ladder and what's missing.
    growth = None
    position = employee.position
    if position is not None and position.grade_id and position.specialization_id:
        ladder = (
            (
                await db.execute(
                    select(GradeSpecialization)
                    .where(
                        GradeSpecialization.tenant_id == tenant_id,
                        GradeSpecialization.specialization_id
                        == position.specialization_id,
                    )
                    .order_by(GradeSpecialization.sort_index)
                )
            )
            .scalars()
            .all()
        )
        current = next((g for g in ladder if g.grade_id == position.grade_id), None)
        nxt = (
            next((g for g in ladder if g.sort_index > current.sort_index), None)
            if current
            else None
        )
        if nxt is not None:
            links = (
                (
                    await db.execute(
                        select(GradeCompetenceLink).where(
                            GradeCompetenceLink.grade_specialization_id == nxt.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            next_bar = _passing_bar(nxt.passing_score)
            missing = [
                {
                    "competence_id": str(link.competence_id),
                    "title": link.competence.title,
                    "percent": (
                        latest_by_competence[link.competence_id].percent
                        if link.competence_id in latest_by_competence
                        else None
                    ),
                }
                for link in links
                if link.competence_id not in latest_by_competence
                or latest_by_competence[link.competence_id].percent < next_bar
            ]
            # Deterministic order for the fingerprint (query has no ORDER BY).
            missing.sort(key=lambda m: (m["title"], m["competence_id"]))
            growth = {
                "current_grade": _dict_item_display(position.grade),
                "specialization": _dict_item_display(position.specialization),
                "next_grade": _dict_item_display(nxt.grade),
                "missing": missing,
            }

    # History for the sparkline: oldest → newest, only dated assessments.
    history = [
        {"finished_at": row.finished_at.isoformat(), "avg_percent": avg}
        for row in reversed(my_done)
        if row.finished_at is not None
        and (avg := _avg(my_results.get(row.id, []))) is not None
    ]

    payload = {
        "employee_id": str(employee.id),
        "stages": {
            "assessed": {
                "finished_at": (
                    latest.finished_at.isoformat()
                    if latest is not None and latest.finished_at is not None
                    else None
                ),
                "avg_percent": _avg(latest_results),
            },
            "gaps": {"competences": len(gap_items), "items": gap_items},
            "developing": {
                "pdp": (
                    {
                        "id": str(active_pdp.id),
                        "title": active_pdp.title,
                        "status": active_pdp.status,
                        "progress": active_pdp.total_progress,
                        "deadline": (
                            active_pdp.deadline.isoformat()
                            if active_pdp.deadline is not None
                            else None
                        ),
                    }
                    if active_pdp is not None
                    else None
                )
            },
            "closed": {"gaps_closed_90d": gaps_closed},
        },
        "findings": findings,
        "strengths": {"top": top, "rare_skills": rare_skills},
        "growth": growth,
        "history": history,
    }
    payload["data_version"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return payload


async def generate_my_loop_summary(
    db: AsyncSession, tenant_id: uuid.UUID, payload: dict
) -> str:
    """The actual LLM call — free by design (see BILLING_EXEMPT rationale)."""
    from app.modules.ai import llm_client, prompts
    from app.modules.ai_settings import service as ai_settings_service

    tenant_settings = await ai_settings_service.get_or_default(db, tenant_id)
    prompt = prompts.MY_LOOP_SUMMARY.format(
        payload=json.dumps(
            {
                k: payload[k]
                for k in ("stages", "findings", "strengths", "growth", "history")
            },
            indent=2,
            default=str,
        )
    )
    try:
        summary = await llm_client.generate(
            prompt,
            system=prompts.build_system_my_loop(tenant_settings),
            tenant_settings=tenant_settings,
            db=db,
        )
    except Exception as e:
        logger.exception("Failed to generate my-loop summary")
        raise AppError(
            "llm_generation_failed",
            status.HTTP_502_BAD_GATEWAY,
            error=exception_summary(e),
        )
    return summary.strip()


async def my_loop_ai_summary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    client_fingerprint: str | None = None,
) -> dict:
    """Cache dispatcher for the personal summary — same contract as
    ``dev_loop_ai_summary``, keyed per user and data state."""
    language = await _tenant_content_language(db, tenant_id)
    if client_fingerprint:
        cached = await _summary_cache_get(
            _ai_summary_cache_key(
                tenant_id, language, client_fingerprint, user_id=user_id
            ),
            "my-loop",
        )
        if cached:
            return {
                "summary": cached,
                "cached": True,
                "data_version": client_fingerprint,
            }

    payload = await my_loop(db, tenant_id, user_id)
    fingerprint = payload["data_version"]
    key = _ai_summary_cache_key(tenant_id, language, fingerprint, user_id=user_id)

    cached = await _summary_cache_get(key, "my-loop")
    if cached:
        return {"summary": cached, "cached": True, "data_version": fingerprint}

    await _consume_ai_summary_budget(db, tenant_id, user_id)
    summary = await generate_my_loop_summary(db, tenant_id, payload)
    await _summary_cache_put(key, summary, "my-loop")
    return {"summary": summary, "cached": False, "data_version": fingerprint}
