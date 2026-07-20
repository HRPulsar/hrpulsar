"""HRP-153: Employee competence overview.

Builds the two-block summary rendered on the rebuilt
`/employees/{uuid}` -> Competences tab:

1. **Current position competences** -- every (competence, skill_level)
   pair the employee's position requires through its
   grade-specialization. Each row exposes:

   * ``percent`` -- the latest qualifying assessment's aggregate
     percent at the required level (``avg(breakdown[..required])``)
     or ``None`` when no Done assessment ever reached the required
     level.
   * ``level_breakdown`` -- the full per-level breakdown of the
     selected assessment (HRP-90 cascade) so the (i) popup can show
     "Skill level / Percent" rows. Empty list when nothing qualifies.

2. **Other competences** -- one row per competence that has at least
   one Done assessment whose target level exceeds the level Current
   Position already shows for the same competence (or the competence
   is not listed in Current at all). The row's ``skill_level`` is the
   highest assessed target, the ``percent`` is
   ``avg(breakdown[..that_level])`` from the latest Done assessment at
   that level, and ``level_breakdown`` carries the full cascade for the
   (i) popup.

Resolution rules per the spec + product owner clarifications (2026-05-26):

* For Current at required level R, only assessments whose targeted
  level is >= R count. Among those, pick the latest by Done timestamp
  (``finished_at``, then ``ended_at``, then ``updated_at`` as a
  fallback). Compute percent = average of breakdown rows with
  ``sort_index <= R.sort_index`` from that assessment.
* For Other, derive the competence's "best" target level (max across
  Done assessments). Skip when Current already covers the competence
  at level >= that best target. Otherwise, take the latest Done
  assessment at that best target and compute percent the same way
  (average of breakdown rows with ``sort_index <= best.sort_index``).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.assessment.models import (
    Assessment,
    AssessmentStatus,
)
from app.modules.competence.models import Competence, SkillLevel
from app.modules.employee.models import Employee
from app.modules.grade_system.models import GradeSpecialization
from app.modules.position.models import Position

_EPOCH = datetime.min


async def _required_pairs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee: Employee,
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Resolve (competence_id, skill_level_id) tuples driven by the
    employee's current position -> grade-specialization.

    Preserves the order from the GradeCompetenceLink rows so that the
    UI tree renders in a stable order. Returns an empty list when the
    position is unset or the grade-specialization has no link rows yet.
    """
    if employee.position_id is None:
        return []
    position = await db.get(Position, employee.position_id)
    if (
        position is None
        or position.tenant_id != tenant_id
        or position.grade_id is None
        or position.specialization_id is None
    ):
        return []

    gs_q = await db.execute(
        select(GradeSpecialization)
        .where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.grade_id == position.grade_id,
            GradeSpecialization.specialization_id == position.specialization_id,
        )
        .options(selectinload(GradeSpecialization.competence_links))
    )
    gs = gs_q.scalar_one_or_none()
    if gs is None:
        return []
    return [(link.competence_id, link.skill_level_id) for link in gs.competence_links]


async def _done_assessments(
    db: AsyncSession,
    employee_id: uuid.UUID,
) -> list[Assessment]:
    """Pull every assessment in status ``done`` for an employee."""
    done_q = await db.execute(
        select(AssessmentStatus.id).where(AssessmentStatus.code == "done")
    )
    done_id = done_q.scalar_one_or_none()
    if done_id is None:
        return []
    asmts_q = await db.execute(
        select(Assessment).where(
            Assessment.employee_id == employee_id,
            Assessment.status_id == done_id,
        )
    )
    return list(asmts_q.scalars().all())


def _avg_up_to(rows: list[dict], max_sort: int) -> int | None:
    """Average percent across breakdown rows with ``sort_index <= max_sort``.

    Returns ``None`` when no row qualifies. Product owner clarification
    (HRP-153 REDO, 2026-05-26) uses this formula for both the Current
    block (with ``max_sort`` = required level) and the Other block
    (with ``max_sort`` = the row's own target level).
    """
    pcts = [r["percent"] for r in rows if r["sort_index"] <= max_sort]
    if not pcts:
        return None
    return round(sum(pcts) / len(pcts))


async def compute_competence_overview(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee: Employee,
) -> dict:
    # Lazy import -- the assessment service imports from many modules; a
    # top-level import here would introduce a circular import via
    # employee.service -> assessment.service.
    from app.modules.assessment.breakdown_service import (
        compute_per_level_breakdowns_batch,
    )

    required_pairs = await _required_pairs(db, tenant_id, employee)
    required_map: dict[uuid.UUID, uuid.UUID] = dict(required_pairs)

    assessments = await _done_assessments(db, employee.id)

    # Batched in one shot so the page render is bounded by a handful of
    # SQL statements regardless of how many done assessments the employee
    # has -- see HRP-153 review notes.
    breakdowns = await compute_per_level_breakdowns_batch(db, assessments)

    # Per-competence list of "candidate" assessments. Each candidate carries
    # the assessment's effective *target* level (highest sort_index reached
    # in the cascade-trimmed breakdown) and the full breakdown rows so we
    # can both pick the right candidate and feed the (i) popup.
    per_comp: dict[uuid.UUID, list[dict]] = {}
    for a in assessments:
        breakdown_per_comp = breakdowns.get(a.id, {})
        completed_at = a.finished_at or a.ended_at or a.updated_at
        for comp_id, rows in breakdown_per_comp.items():
            if not rows:
                continue
            sorted_rows = sorted(rows, key=lambda r: r["sort_index"])
            top = sorted_rows[-1]
            per_comp.setdefault(comp_id, []).append(
                {
                    "assessment_id": a.id,
                    "completed_at": completed_at,
                    "target_level_id": top["skill_level_id"],
                    "target_level_title": top["skill_level_title"],
                    "target_level_sort": top["sort_index"],
                    "rows": sorted_rows,
                }
            )

    # Sort each competence's candidates newest-first; we'll filter and
    # pick the first qualifying one below.
    for lst in per_comp.values():
        lst.sort(
            key=lambda x: (x["completed_at"] or _EPOCH, str(x["assessment_id"])),
            reverse=True,
        )

    # Bulk-load comps + levels referenced by either block so the row
    # builders don't issue per-row SQL.
    comp_ids: set[uuid.UUID] = set(required_map.keys()) | set(per_comp.keys())
    level_ids: set[uuid.UUID] = set(required_map.values())
    for candidates in per_comp.values():
        for cand in candidates:
            level_ids.add(cand["target_level_id"])
            for row in cand["rows"]:
                level_ids.add(row["skill_level_id"])

    comps_by_id: dict[uuid.UUID, Competence] = {}
    if comp_ids:
        comp_q = await db.execute(select(Competence).where(Competence.id.in_(comp_ids)))
        comps_by_id = {c.id: c for c in comp_q.scalars().all()}

    levels_by_id: dict[uuid.UUID, SkillLevel] = {}
    if level_ids:
        sl_q = await db.execute(select(SkillLevel).where(SkillLevel.id.in_(level_ids)))
        levels_by_id = {sl.id: sl for sl in sl_q.scalars().all()}

    def _breakdown_payload(rows: list[dict]) -> list[dict]:
        # Re-shape the breakdown rows for the API response. Keeps only
        # the fields the (i) popup needs and drops the trailing internal
        # sort key once we've ordered by it.
        return [
            {
                "skill_level_id": r["skill_level_id"],
                "skill_level_title": r["skill_level_title"],
                "skill_level_sort_index": r["sort_index"],
                "percent": r["percent"],
            }
            for r in rows
        ]

    current_rows: list[dict] = []
    for comp_id, level_id in required_pairs:
        comp = comps_by_id.get(comp_id)
        sl = levels_by_id.get(level_id)
        req_sort = sl.sort_index if sl else 0

        qualifying = [
            c
            for c in per_comp.get(comp_id, [])
            if c["target_level_sort"] >= req_sort
        ]
        chosen = qualifying[0] if qualifying else None
        percent = _avg_up_to(chosen["rows"], req_sort) if chosen else None
        breakdown_payload = _breakdown_payload(chosen["rows"]) if chosen else []

        current_rows.append(
            {
                "competence_id": comp_id,
                "competence_title": comp.title if comp else "",
                "group_id": comp.group_id if comp else None,
                "skill_level_id": level_id,
                "skill_level_title": sl.title if sl else "",
                "skill_level_sort_index": req_sort,
                "percent": percent,
                "assessment_id": chosen["assessment_id"] if chosen else None,
                "completed_at": chosen["completed_at"] if chosen else None,
                "level_breakdown": breakdown_payload,
            }
        )

    other_rows: list[dict] = []
    for comp_id, candidates in per_comp.items():
        if not candidates:
            continue
        # Highest assessed target level across all Done assessments for
        # this competence. Picking the level first keeps the row at the
        # level the employee actually demonstrated, not just the latest
        # attempt at a weaker level (per product owner's REDO note 2.c).
        best_sort = max(c["target_level_sort"] for c in candidates)

        # Skip from Other only when Current is already showing the same
        # competence at the same level (i.e., a redundant row would
        # appear). HRP-217: when the only assessment sits below the
        # required level, Current renders an empty slot at the required
        # level, so Other still needs to surface the lower-level result
        # the employee actually has.
        if comp_id in required_map:
            required_level = levels_by_id.get(required_map[comp_id])
            required_sort = required_level.sort_index if required_level else 0
            if required_sort == best_sort:
                continue

        # Latest Done assessment at the best level wins -- candidates is
        # already sorted newest-first, so just take the first match.
        chosen = next(c for c in candidates if c["target_level_sort"] == best_sort)
        comp = comps_by_id.get(comp_id)
        target_sl = levels_by_id.get(chosen["target_level_id"])
        percent = _avg_up_to(chosen["rows"], best_sort)
        other_rows.append(
            {
                "competence_id": comp_id,
                "competence_title": comp.title if comp else "",
                "group_id": comp.group_id if comp else None,
                "skill_level_id": chosen["target_level_id"],
                "skill_level_title": target_sl.title if target_sl else chosen["target_level_title"],
                "skill_level_sort_index": best_sort,
                "percent": percent,
                "assessment_id": chosen["assessment_id"],
                "completed_at": chosen["completed_at"],
                "level_breakdown": _breakdown_payload(chosen["rows"]),
            }
        )

    other_rows.sort(key=lambda r: (r["competence_title"].lower(),))

    return {"current_position": current_rows, "other": other_rows}
