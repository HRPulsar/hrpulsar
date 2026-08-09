"""HRP-528: aggregated analytics for a mass (group) assessment.

The Analytics block on the assessment-group page is built from the children
that reached status ``done`` — cancelled and still-in-flight children are
counted in ``excluded_count`` and contribute nothing to the numbers.

Nothing here re-derives the match percent: per-competence values are read
straight from the ``AssessmentResult`` rows written by
``service._recompute_assessment_results`` (the HRP-62 formula), the overall
value goes through ``service.compute_overall_percent``, and per-grade values
reuse ``recommendation.compute_grade_percents``. This module only groups,
averages and sorts.

Averages that the filter bar can reshape (average match level, matrix
"Average" columns) are deliberately *not* pre-computed here — the endpoint
ships per-employee values and the client aggregates them, so toggling a
filter does not need a round-trip. The two highlight lists (growth zones /
top competences) are unfiltered by spec, so they are computed server-side.
"""

from __future__ import annotations

import math
import uuid

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.core.s3 import get_presigned_url
from app.modules.assessment.models import (
    Assessment,
    AssessmentGroup,
    AssessmentResult,
)
from app.modules.assessment.recommendation import (
    compute_grade_percents,
    load_grade_matrix_prefetch,
)
from app.modules.assessment.service import (
    apply_assessment_scope,
    compute_overall_percent,
)

#: At most this many competences are listed as growth zones.
GROWTH_ZONE_LIMIT = 10
#: Growth zones cover competences at or below this average percent.
GROWTH_ZONE_MAX_PERCENT = 75
#: Top competences cover competences strictly above this average percent.
TOP_COMPETENCE_MIN_PERCENT = 75


def _round_half_up(value: float) -> int:
    """Round for display by school rules, matching compute_overall_percent."""
    return math.floor(value + 0.5)


def _employee_full_name(employee) -> str | None:
    user = getattr(employee, "user", None)
    if user is None:
        return None
    parts = [p for p in (user.first_name, user.last_name) if p]
    return " ".join(parts) if parts else (user.email or None)


async def _avatar_urls(db: AsyncSession, employees: list) -> dict[uuid.UUID, str]:
    """Batch presigned-URL lookup for the assessee avatars (single SELECT)."""
    from app.modules.storage.models import File

    file_ids = {
        emp.user.avatar_file_id
        for emp in employees
        if emp is not None and emp.user and emp.user.avatar_file_id
    }
    if not file_ids:
        return {}
    files = (
        (await db.execute(select(File).where(File.id.in_(file_ids)))).scalars().all()
    )
    path_by_file = {f.id: f.path for f in files}
    out: dict[uuid.UUID, str] = {}
    for emp in employees:
        if emp is None or not emp.user:
            continue
        path = path_by_file.get(emp.user.avatar_file_id)
        url = get_presigned_url(path) if path else None
        if url:
            out[emp.id] = url
    return out


def _competence_averages(
    employees: list[dict], titles: dict[uuid.UUID, str]
) -> list[dict]:
    """Mean percent per competence across every employee that has a value.

    Employees whose percent for a competence is ``None`` (all "Don't know",
    or the competence was not part of their questionnaire) drop out of the
    divisor instead of counting as zero. This single rule covers both spec
    branches: for ``current_positions`` a competence shared by several
    employees averages their values and a competence held by one employee
    keeps that employee's value; for the other criteria types it is the same
    arithmetic mean over everyone who has a computed value.
    """
    buckets: dict[uuid.UUID, list[int]] = {}
    for emp in employees:
        for row in emp["competences"]:
            if row["percent"] is None:
                continue
            buckets.setdefault(row["competence_id"], []).append(row["percent"])

    averages: list[dict] = []
    for competence_id, values in buckets.items():
        avg = compute_overall_percent(values)
        if avg is None:
            continue
        averages.append(
            {
                "competence_id": competence_id,
                "competence_title": titles.get(competence_id, ""),
                "percent": avg,
            }
        )
    return averages


def _split_highlights(averages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Growth zones (<= 75%, worst first) and top competences (> 75%)."""
    growth = sorted(
        (a for a in averages if a["percent"] <= GROWTH_ZONE_MAX_PERCENT),
        key=lambda a: (a["percent"], a["competence_title"]),
    )[:GROWTH_ZONE_LIMIT]
    top = sorted(
        (a for a in averages if a["percent"] > TOP_COMPETENCE_MIN_PERCENT),
        key=lambda a: (-a["percent"], a["competence_title"]),
    )
    return growth, top


async def get_group_analytics(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    visible_employee_ids: set[uuid.UUID] | None = None,
    participant_user_id: uuid.UUID | None = None,
    restrict_to_active: bool = False,
    hide_results_for_employee: bool = False,
) -> dict:
    """Aggregated analytics for one assessment group. Read-only.

    ``hide_results_for_employee`` is the same flag ``service.get_results``
    takes: with it set, only assessees inside ``visible_employee_ids``
    contribute, so an employee-only caller never reads the numbers of a
    colleague whose questionnaire they merely answered.
    """
    group = await db.get(AssessmentGroup, group_id)
    if not group or group.tenant_id != tenant_id:
        raise AppError("assessment_group_not_found", status.HTTP_404_NOT_FOUND)

    children_query = (
        select(Assessment)
        .options(
            selectinload(Assessment.status),
            selectinload(Assessment.employee),
        )
        .where(Assessment.group_id == group_id)
        .order_by(Assessment.created_at)
    )
    children_query = apply_assessment_scope(
        children_query,
        visible_employee_ids=visible_employee_ids,
        participant_user_id=participant_user_id,
        restrict_to_active=restrict_to_active,
    )
    children = list((await db.execute(children_query)).scalars().all())

    # Mirror get_assessment_group: a scope-restricted caller that can see no
    # child must not be able to confirm the group exists through this route.
    if (visible_employee_ids is not None or restrict_to_active) and not children:
        raise AppError("assessment_group_not_found", status.HTTP_404_NOT_FOUND)

    # HRP-243 parity. ``apply_assessment_scope`` admits a child on either arm:
    # the assessee is inside the caller's subtree OR the caller is one of the
    # respondents. The second arm is what lets a rank-and-file employee open a
    # colleague's 360 questionnaire — it must not also hand them that
    # colleague's numbers. ``get_results`` refuses exactly this case (employee
    # sees results only for their own, closed assessment), so the aggregation
    # here drops every child the caller reaches only as a respondent: nothing
    # but assessees inside their own scope survives. The "closed" half of the
    # ``get_results`` gate is already covered — only ``done`` children are
    # aggregated at all.
    #
    # Dropping the rows before anything else is computed keeps ``done_count`` /
    # ``excluded_count`` and every derived list (competences, grades,
    # divisions, highlights) from re-exposing what the employee row hides.
    # ``visible_employee_ids is None`` means "no scope restriction", which only
    # happens for admin/HR — callers that never set this flag; treating it as
    # "nothing visible" keeps the fallback on the safe side.
    if hide_results_for_employee:
        allowed_employee_ids = visible_employee_ids or set()
        children = [a for a in children if a.employee_id in allowed_employee_ids]

    done = [a for a in children if a.status is not None and a.status.code == "done"]
    is_all_grades = group.criteria_type == "target_position" and group.grade_id is None

    empty: dict = {
        "group_id": group_id,
        "criteria_type": group.criteria_type,
        "is_all_grades": is_all_grades,
        "done_count": 0,
        "excluded_count": len(children),
        "employees": [],
        "competences": [],
        "grades": [],
        "divisions": [],
        "specializations": [],
        "growth_zones": [],
        "top_competences": [],
    }
    if not done:
        return empty

    # --- per-competence percents, straight off the stored result rows ---
    done_ids = [a.id for a in done]
    result_rows = list(
        (
            await db.execute(
                select(AssessmentResult).where(
                    AssessmentResult.assessment_id.in_(done_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    results_by_assessment: dict[uuid.UUID, list[AssessmentResult]] = {}
    for row in result_rows:
        results_by_assessment.setdefault(row.assessment_id, []).append(row)

    competence_ids = {row.competence_id for row in result_rows}
    titles: dict[uuid.UUID, str] = {}
    if competence_ids:
        from app.modules.competence.models import Competence

        competences = (
            (
                await db.execute(
                    select(Competence).where(Competence.id.in_(competence_ids))
                )
            )
            .scalars()
            .all()
        )
        titles = {c.id: c.title for c in competences}

    avatars = await _avatar_urls(db, [a.employee for a in done])

    # --- per-grade percents (All grades only — that is the one layout that
    # renders a grade matrix and a grade chart) ---
    grade_rows_by_assessment: dict[uuid.UUID, list] = {}
    grade_refs: dict[uuid.UUID, dict] = {}
    if is_all_grades:
        # One bulk load for the whole wave instead of ~9 queries per child:
        # the grade/competence-link/skill-level scaffolding is shared by every
        # child of the group, and the per-assessment rows (participants,
        # answers, indicators) come back in a single ``IN (…)`` each. The math
        # itself still runs through compute_grade_percents, one call per child.
        grade_prefetch = await load_grade_matrix_prefetch(db, tenant_id, done)
        for assessment in done:
            items = await compute_grade_percents(
                db, tenant_id, assessment, prefetch=grade_prefetch
            )
            if not items:
                continue
            grade_rows_by_assessment[assessment.id] = items
            for item in items:
                grade_refs.setdefault(
                    item.grade_id,
                    {
                        "grade_id": item.grade_id,
                        "grade_title": item.grade_title,
                        "grade_i18n_key": None,
                        "sort_index": item.sort_index,
                    },
                )
        if grade_refs:
            from app.modules.dictionary.models import DictionaryItem

            dict_items = (
                (
                    await db.execute(
                        select(DictionaryItem).where(
                            DictionaryItem.id.in_(list(grade_refs))
                        )
                    )
                )
                .scalars()
                .all()
            )
            for dict_item in dict_items:
                ref = grade_refs.get(dict_item.id)
                if ref is not None:
                    ref["grade_i18n_key"] = dict_item.i18n_key
                    ref["grade_title"] = dict_item.title

    employees: list[dict] = []
    divisions: dict[uuid.UUID, str] = {}
    specializations: dict[uuid.UUID, dict] = {}

    for assessment in done:
        employee = assessment.employee
        if employee is None:
            continue
        rows = results_by_assessment.get(assessment.id, [])
        percent = compute_overall_percent([r.percent for r in rows])
        # "All Don't know" is a statement about the answers, so it needs at
        # least one competence to be a statement at all. A done child without
        # a single AssessmentResult row (criteria never set, or the results
        # were wiped) also lands on ``percent is None`` — that is "no result",
        # not "answered Don't know everywhere", and must not be labelled as
        # the latter in the matrix.
        all_dont_know = bool(rows) and percent is None

        position = getattr(employee, "position", None)
        spec = position.specialization if position else None
        grade = position.grade if position else None
        division = getattr(employee, "division", None)

        if division is not None:
            divisions[division.id] = division.name
        if spec is not None:
            specializations[spec.id] = {
                "specialization_id": spec.id,
                "specialization_title": spec.title,
                "specialization_i18n_key": spec.i18n_key,
            }

        employees.append(
            {
                "assessment_id": assessment.id,
                "employee_id": employee.id,
                "full_name": _employee_full_name(employee),
                "avatar_url": avatars.get(employee.id),
                "division_id": division.id if division else None,
                "division_name": division.name if division else None,
                "specialization_id": spec.id if spec else None,
                "specialization_title": spec.title if spec else None,
                "specialization_i18n_key": spec.i18n_key if spec else None,
                "grade_id": grade.id if grade else None,
                "grade_title": grade.title if grade else None,
                "grade_i18n_key": grade.i18n_key if grade else None,
                "position_title": employee.position_title,
                "percent": percent,
                # Every competence came back without a value — the assessee
                # was answered entirely with "Don't know". Such employees stay
                # visible in the matrices but drop out of every average.
                "all_dont_know": all_dont_know,
                "competences": [
                    {"competence_id": r.competence_id, "percent": r.percent}
                    for r in sorted(rows, key=lambda r: titles.get(r.competence_id, ""))
                ],
                # ``percent is None`` has to null the grade row too. HRP-170
                # deliberately feeds a competence with no usable answers into
                # the grade average as 0% (that is the recommendation verdict's
                # rule and must not change), so an assessee answered entirely
                # with "Don't know" comes back as a non-excluded 0.0 rather
                # than as an excluded row. Passing that through would paint a
                # red 0% chip and drag every grade average down, against the
                # spec's "displayed but not counted". The test is ``percent is
                # None`` rather than ``all_dont_know`` on purpose: a child with
                # no result rows at all has nothing to back a grade chip
                # either.
                "grades": [
                    {
                        "grade_id": item.grade_id,
                        "percent": (
                            None
                            if item.excluded or percent is None
                            else _round_half_up(item.percent)
                        ),
                    }
                    for item in grade_rows_by_assessment.get(assessment.id, [])
                ],
            }
        )

    averages = _competence_averages(employees, titles)
    growth_zones, top_competences = _split_highlights(averages)

    return {
        "group_id": group_id,
        "criteria_type": group.criteria_type,
        "is_all_grades": is_all_grades,
        "done_count": len(done),
        "excluded_count": len(children) - len(done),
        "employees": employees,
        "competences": [
            {"competence_id": cid, "competence_title": title}
            for cid, title in sorted(titles.items(), key=lambda kv: kv[1])
        ],
        "grades": sorted(grade_refs.values(), key=lambda g: g["sort_index"]),
        "divisions": [
            {"division_id": did, "division_name": name}
            for did, name in sorted(divisions.items(), key=lambda kv: kv[1] or "")
        ],
        "specializations": sorted(
            specializations.values(),
            key=lambda s: s["specialization_title"] or "",
        ),
        "growth_zones": growth_zones,
        "top_competences": top_competences,
    }
