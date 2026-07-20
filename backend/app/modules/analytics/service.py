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

import io
import uuid

from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assessment.models import (
    CPA,
    PDP,
    Assessment,
    AssessmentResult,
    AssessmentStatus,
    PDPVersion,
)
from app.modules.company.models import Division, SpecializationDivision
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Compensation, Employee


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
    from app.modules.auth.models import User

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
