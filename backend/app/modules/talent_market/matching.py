"""Candidate matching engine: spec / competence / experience scoring and auto-population.

Split from the former talent_market/service.py god-service
(project-review #20). ``service.py`` remains as a PEP 562 delegating
namespace so ``service.<name>`` keeps resolving to the wrapped
canonical functions.
"""

import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.assessment.models import (
    Assessment,
    AssessmentCompetence,
    AssessmentResult,
    AssessmentStatus,
)
from app.modules.competence.models import SkillLevel
from app.modules.employee.models import Employee, WorkExperience
from app.modules.position.models import Position
from app.modules.talent_market.models import (
    TalentCandidate,
    TalentCard,
    TalentCardCompetence,
    TalentCardSpecialization,
)

logger = logging.getLogger(__name__)


async def _fetch_match_inputs(
    db: AsyncSession, card_id: uuid.UUID
) -> tuple[list[TalentCardCompetence], list[TalentCardSpecialization]]:
    """One-shot fetch of card-level requirements used by the matcher.

    Pulling these once per card (instead of once per employee) is what makes
    `list_candidate_pool` scale on tenants with hundreds of employees.

    Returns:
      * comp_rows: the Required Competence links (may be empty).
      * spec_rows: the Required Specialization links (may be empty).
    """
    comp_rows = (
        (
            await db.execute(
                select(TalentCardCompetence).where(
                    TalentCardCompetence.card_id == card_id
                )
            )
        )
        .scalars()
        .all()
    )
    spec_rows = (
        (
            await db.execute(
                select(TalentCardSpecialization).where(
                    TalentCardSpecialization.card_id == card_id
                )
            )
        )
        .scalars()
        .all()
    )
    return list(comp_rows), list(spec_rows)


async def _done_status_id(db: AsyncSession) -> uuid.UUID | None:
    """Cache-friendly lookup of the `done` assessment status id."""
    return (
        await db.execute(
            select(AssessmentStatus.id).where(AssessmentStatus.code == "done")
        )
    ).scalar_one_or_none()


async def _employee_experience_months(
    db: AsyncSession,
    employee_id: uuid.UUID,
    spec_rows: list[TalentCardSpecialization],
    *,
    work_exp_cache: dict[uuid.UUID, list[WorkExperience]] | None = None,
) -> int | None:
    """HRP-173: total months of experience the employee has on positions
    matching any of the card's Required Specializations.

    Returns ``None`` when the card carries no specs (no signal to compute)
    or the employee has no matching WorkExperience rows at all. Returns
    ``0`` when there are matches but their net tenure is non-positive
    (start_date in the future, etc).
    """
    if not spec_rows:
        return None
    if work_exp_cache is not None and employee_id in work_exp_cache:
        work_exps = work_exp_cache[employee_id]
    else:
        work_exps = list(
            (
                await db.execute(
                    select(WorkExperience)
                    .options(selectinload(WorkExperience.position))
                    .where(WorkExperience.employee_id == employee_id)
                )
            )
            .scalars()
            .all()
        )
        if work_exp_cache is not None:
            work_exp_cache[employee_id] = work_exps
    today = date.today()
    matching_ids: set[uuid.UUID] = set()
    for spec in spec_rows:
        for we in work_exps:
            if not we.position:
                continue
            if (
                we.position.specialization_id == spec.specialization_id
                and we.position.grade_id == spec.grade_id
            ):
                matching_ids.add(we.id)
    if not matching_ids:
        return None
    total_days = 0
    for we in work_exps:
        if we.id not in matching_ids:
            continue
        end = we.end_date or today
        if end > we.start_date:
            total_days += (end - we.start_date).days
    months = int(total_days // 30)
    return max(months, 0)


async def _employee_current_position_matches_any_spec(
    db: AsyncSession,
    employee_id: uuid.UUID,
    spec_rows: list[TalentCardSpecialization],
    *,
    current_pos_cache: dict[uuid.UUID, Position | None] | None = None,
) -> bool:
    """HRP-210: does the employee's current Position match any of the
    Required Specializations on the card?

    Used as a fallback for the Match cell's Experience axis when the
    employee has no qualifying ``WorkExperience`` row — keeps employees
    who only just joined visible to the recruiter as "current position
    matches" (greyed) rather than "no experience" (red).
    """
    if not spec_rows:
        return False
    pos = await _employee_current_position(
        db, employee_id, current_pos_cache=current_pos_cache
    )
    if pos is None:
        return False
    return any(_current_position_matches_spec(pos, spec) for spec in spec_rows)


async def _employee_current_position(
    db: AsyncSession,
    employee_id: uuid.UUID,
    *,
    current_pos_cache: dict[uuid.UUID, Position | None] | None = None,
) -> Position | None:
    """HRP-210: resolve the employee's current Position.

    Looked up via ``Employee.position_id``. Returns ``None`` when the
    employee has no current position attached. The cache lets callers
    that fan out across many employees pay one SQL per ``Position`` ID
    instead of N+1.
    """
    if current_pos_cache is not None and employee_id in current_pos_cache:
        return current_pos_cache[employee_id]
    emp = await db.get(Employee, employee_id)
    if not emp or emp.position_id is None:
        if current_pos_cache is not None:
            current_pos_cache[employee_id] = None
        return None
    pos = await db.get(Position, emp.position_id)
    if current_pos_cache is not None:
        current_pos_cache[employee_id] = pos
    return pos


def _current_position_matches_spec(
    pos: Position | None, spec: TalentCardSpecialization
) -> bool:
    """HRP-210: does the employee's current Position line up with the
    card's Required Specialization (spec_id, grade_id) tuple?"""
    if pos is None:
        return False
    return (
        pos.specialization_id == spec.specialization_id
        and pos.grade_id == spec.grade_id
    )


async def _employee_spec_match(
    db: AsyncSession,
    employee_id: uuid.UUID,
    spec_rows: list[TalentCardSpecialization],
    *,
    work_exp_cache: dict[uuid.UUID, list[WorkExperience]] | None = None,
    current_pos_cache: dict[uuid.UUID, Position | None] | None = None,
) -> bool:
    """HRP-129 + HRP-210: does the employee satisfy at least one Required
    Specialization?

    A spec row is satisfied when:

    * the employee has held a position with the same
      ``(specialization_id, grade_id)`` pair via the WorkExperience block,
      AND the tenure clears ``min_experience_years`` (or the floor isn't
      set); OR
    * HRP-210 fallback — there's no matching WorkExperience row but the
      employee's *current* Position (via ``Employee.position_id``) lines
      up with the spec, AND the spec has no ``min_experience_years``
      floor (current position alone can't prove a multi-year tenure).

    Empty ``spec_rows`` short-circuits to True so the caller can fold
    this in alongside the competence check without special-casing.
    """
    if not spec_rows:
        return True

    if work_exp_cache is not None and employee_id in work_exp_cache:
        work_exps = work_exp_cache[employee_id]
    else:
        work_exps = list(
            (
                await db.execute(
                    select(WorkExperience)
                    .options(selectinload(WorkExperience.position))
                    .where(WorkExperience.employee_id == employee_id)
                )
            )
            .scalars()
            .all()
        )
        if work_exp_cache is not None:
            work_exp_cache[employee_id] = work_exps

    today = date.today()
    current_pos: Position | None | object = _UNRESOLVED
    for spec in spec_rows:
        matching = [
            we
            for we in work_exps
            if we.position
            and we.position.specialization_id == spec.specialization_id
            and we.position.grade_id == spec.grade_id
        ]
        if matching:
            if spec.min_experience_years is None or spec.min_experience_years == 0:
                return True
            total_days = 0
            for we in matching:
                end = we.end_date or today
                if end > we.start_date:
                    total_days += (end - we.start_date).days
            years = total_days / 365.25
            if years >= spec.min_experience_years:
                return True
            continue
        # HRP-210 fallback: no WorkExperience match → check current_position.
        # Current position alone can't satisfy a min_experience_years floor.
        if spec.min_experience_years not in (None, 0):
            continue
        if current_pos is _UNRESOLVED:
            current_pos = await _employee_current_position(
                db, employee_id, current_pos_cache=current_pos_cache
            )
        if _current_position_matches_spec(current_pos, spec):  # type: ignore[arg-type]
            return True
    return False


_UNRESOLVED = object()


async def _last_passed_percents(
    db: AsyncSession,
    employee_ids: list[uuid.UUID],
    required_pairs: set[tuple[uuid.UUID, uuid.UUID | None]],
) -> dict[uuid.UUID, dict[uuid.UUID, int]]:
    """Return {employee_id: {competence_id: percent}} from the last `done`
    assessment per (employee, required competence) where the assessment also
    covered that competence at the required skill level or higher.

    HRP-129 rules:
    * only `done` assessments count;
    * if several `done` assessments cover the same competence, the *latest*
      one wins (sorted by `finished_at desc`), even if its percent is lower;
    * skill-level filter (per HRP-90 mechanic): an assessment counts toward
      a Required Competence when its `AssessmentCompetence.skill_level_id`
      sits at or above the required level on the SkillLevel.sort_index
      ladder. Below → ignored. Required level with no skill_level_id falls
      back to plain competence matching.

    HRP-129 REDO: when the assessment ran at a level *higher* than required,
    project the result down to the required level using the per-level
    breakdown (HRP-90 cascade) — average of breakdown rows with
    ``sort_index <= required_sort``. This matches the Employee Competences
    tab (HRP-153) and the spec example in the product owner's 2026-05-27 comment.
    Falls back to ``AssessmentResult.percent`` when no breakdown is
    available (assessment without answers/scale — only seen in synthetic
    test fixtures; real Done assessments always carry the breakdown).
    """
    if not employee_ids or not required_pairs:
        return {}
    done_id = await _done_status_id(db)
    if done_id is None:
        return {}
    required_comp_ids = {pair[0] for pair in required_pairs}
    required_sl_ids = {sl for _, sl in required_pairs if sl is not None}

    sl_sort: dict[uuid.UUID, int] = {}
    if required_sl_ids:
        sl_rows = (
            await db.execute(
                select(SkillLevel.id, SkillLevel.sort_index).where(
                    SkillLevel.id.in_(required_sl_ids)
                )
            )
        ).all()
        sl_sort.update({row[0]: row[1] for row in sl_rows})

    stmt = (
        select(
            Assessment.id,
            Assessment.employee_id,
            AssessmentCompetence.competence_id,
            AssessmentCompetence.skill_level_id,
            SkillLevel.sort_index,
            Assessment.finished_at,
            AssessmentResult.percent,
        )
        .join(
            AssessmentCompetence,
            AssessmentCompetence.assessment_id == Assessment.id,
        )
        .outerjoin(
            AssessmentResult,
            and_(
                AssessmentResult.assessment_id == Assessment.id,
                AssessmentResult.competence_id == AssessmentCompetence.competence_id,
            ),
        )
        .outerjoin(SkillLevel, SkillLevel.id == AssessmentCompetence.skill_level_id)
        .where(Assessment.status_id == done_id)
        .where(Assessment.employee_id.in_(employee_ids))
        .where(AssessmentCompetence.competence_id.in_(required_comp_ids))
    )
    rows = (await db.execute(stmt)).all()

    required_by_comp: dict[uuid.UUID, list[uuid.UUID | None]] = {}
    for comp_id, sl_id in required_pairs:
        required_by_comp.setdefault(comp_id, []).append(sl_id)

    # Strictest required sort per comp (highest sort_index wins) — used both
    # to filter assessments and to drive the projection cutoff.
    required_sort_by_comp: dict[uuid.UUID, int | None] = {}
    for comp_id, sl_id_list in required_by_comp.items():
        strict: int | None = None
        any_null = False
        for sl_id in sl_id_list:
            if sl_id is None:
                any_null = True
                continue
            rs = sl_sort.get(sl_id)
            if rs is None:
                continue
            if strict is None or rs > strict:
                strict = rs
        # A NULL required level means "any level counts"; the projection
        # should average every breakdown row. Mark with None.
        required_sort_by_comp[comp_id] = None if any_null else strict

    # Filter assessment rows by skill-level guard and group by
    # (employee, competence) → ordered list of (assessment_id, finished_at,
    # result.percent fallback).
    candidates: dict[
        tuple[uuid.UUID, uuid.UUID], list[tuple[uuid.UUID, datetime | None, int | None]]
    ] = {}
    for asmt_id, emp_id, comp_id, sl_id, sl_sort_index, finished_at, pct in rows:
        sl_id_options = required_by_comp.get(comp_id)
        if not sl_id_options:
            continue
        passes = False
        for required_sl_id in sl_id_options:
            if required_sl_id is None:
                passes = True
                break
            required_sort = sl_sort.get(required_sl_id)
            if required_sort is None:
                if sl_id == required_sl_id:
                    passes = True
                    break
                continue
            if sl_id == required_sl_id:
                passes = True
                break
            if sl_sort_index is None:
                continue
            if sl_sort_index >= required_sort:
                passes = True
                break
        if not passes:
            continue
        fallback = int(pct) if pct is not None else None
        candidates.setdefault((emp_id, comp_id), []).append(
            (asmt_id, finished_at, fallback)
        )

    if not candidates:
        return {}

    # Sort each (employee, competence) bucket newest-first and pick the
    # latest. We compute breakdowns only for the assessments we'll actually
    # read percent from — saves work when an employee has dozens of Done
    # assessments but the matcher only consults the latest per Required row.
    chosen: dict[tuple[uuid.UUID, uuid.UUID], tuple[uuid.UUID, int | None]] = {}
    needed_asmt_ids: set[uuid.UUID] = set()
    for key, lst in candidates.items():
        lst.sort(
            key=lambda t: (t[1] or datetime.min, str(t[0])),
            reverse=True,
        )
        asmt_id, _, fallback = lst[0]
        chosen[key] = (asmt_id, fallback)
        needed_asmt_ids.add(asmt_id)

    # HRP-129 REDO: compute per-level breakdowns for the chosen assessments
    # so we can project results from a higher-level assessment to the
    # required level (average only rows with sort_index <= required_sort).
    # Lazy import — talent_market imports lower in the dependency graph
    # than assessment service.
    from app.modules.assessment.breakdown_service import (
        compute_per_level_breakdowns_batch,
    )

    breakdowns: dict[uuid.UUID, dict[uuid.UUID, list[dict]]] = {}
    if needed_asmt_ids:
        asmts_for_breakdown = list(
            (
                await db.execute(
                    select(Assessment).where(Assessment.id.in_(needed_asmt_ids))
                )
            )
            .scalars()
            .all()
        )
        breakdowns = await compute_per_level_breakdowns_batch(db, asmts_for_breakdown)

    out: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    for (emp_id, comp_id), (asmt_id, fallback) in chosen.items():
        required_sort = required_sort_by_comp.get(comp_id)
        breakdown_rows = breakdowns.get(asmt_id, {}).get(comp_id, [])
        projected: int | None = None
        if breakdown_rows:
            if required_sort is None:
                pcts = [r["percent"] for r in breakdown_rows]
            else:
                pcts = [
                    r["percent"]
                    for r in breakdown_rows
                    if r["sort_index"] <= required_sort
                ]
            if pcts:
                projected = round(sum(pcts) / len(pcts))
        score = projected if projected is not None else fallback
        if score is None:
            continue
        out.setdefault(emp_id, {})[comp_id] = score

    return out


def _comp_percent_from_map(
    comp_rows: list[TalentCardCompetence],
    last_by_comp: dict[uuid.UUID, int],
) -> int | None:
    """HRP-129: average % match across Required Competences.

    Per the spec examples in the ticket:
    * if the employee has at least one matching `done` assessment among the
      Required Competences, average percent across *all* required rows
      (competences without a matching assessment contribute 0);
    * if there's not a single matching assessment, the score is not computed
      and the helper returns None — the candidate is excluded.

    Math rounding is half-up (62.5 → 63), as in the worked example
    (100+80+70+0)/4 = 62.5 → 63. Python's built-in `round` uses banker's
    rounding for ties, so we add a half before truncation instead.
    """
    if not comp_rows:
        return None
    if not last_by_comp:
        return None
    total = 0
    for link in comp_rows:
        total += last_by_comp.get(link.competence_id, 0)
    n = len(comp_rows)
    # Integer arithmetic for deterministic half-up rounding.
    return (total * 2 + n) // (2 * n)


async def _compute_match_score(
    db: AsyncSession,
    card: TalentCard,
    employee_id: uuid.UUID,
    *,
    comp_rows: list[TalentCardCompetence] | None = None,
    spec_rows: list[TalentCardSpecialization] | None = None,
    _inputs_loaded: bool = False,
) -> tuple[int | None, str]:
    """HRP-129: deterministic match score for one employee against one card.

    Returns `(score, basis)` where:
    * `score` is the average competence percent (0..100) or None when the
      employee hasn't taken a single matching `done` assessment;
    * `basis` is `"competence"` when at least one matching assessment fed
      the average, `"specialization"` when the card only has Required
      Specializations (no competences) and the employee clears them, and
      `"none"` otherwise.

    Callers that fan out across many employees on the same card should
    prefetch requirements via `_fetch_match_inputs` and pass them in to
    avoid the per-call DB hit for card-level rows that don't change between
    employees (N+1).
    """
    if not _inputs_loaded:
        comp_rows, spec_rows = await _fetch_match_inputs(db, card.id)
    comp_rows = comp_rows or []
    spec_rows = spec_rows or []

    if comp_rows:
        required_pairs = {(r.competence_id, r.skill_level_id) for r in comp_rows}
        last_map = await _last_passed_percents(db, [employee_id], required_pairs)
        per_comp = last_map.get(employee_id, {})
        score = _comp_percent_from_map(comp_rows, per_comp)
        if score is None:
            return None, "none"
        return score, "competence"

    if spec_rows:
        matched = await _employee_spec_match(db, employee_id, spec_rows)
        return (100 if matched else 0), "specialization"

    return None, "none"


async def _employee_qualifies(
    db: AsyncSession,
    card: TalentCard,
    employee_id: uuid.UUID,
    *,
    comp_rows: list[TalentCardCompetence],
    spec_rows: list[TalentCardSpecialization],
    last_by_comp: dict[uuid.UUID, int] | None = None,
    work_exp_cache: dict[uuid.UUID, list[WorkExperience]] | None = None,
    current_pos_cache: dict[uuid.UUID, Position | None] | None = None,
) -> tuple[bool, int | None]:
    """HRP-129: does this employee qualify for the card's auto-pool?

    Returns `(qualifies, score)`. `qualifies` requires that the employee
    clears the spec match (or no specs are set) *and* the competence
    average is at or above the card-level Match% threshold.
    `score` is the same competence percent the matcher computes — None when
    not a single `done` assessment covered any Required Competence.
    """
    if not comp_rows and not spec_rows:
        # A card with no requirements at all matches nobody — recruiter
        # hasn't told us what they're looking for yet.
        return False, None

    spec_ok = await _employee_spec_match(
        db,
        employee_id,
        spec_rows,
        work_exp_cache=work_exp_cache,
        current_pos_cache=current_pos_cache,
    )
    if not spec_ok:
        return False, None

    if not comp_rows:
        # No competence requirements: only the spec match gates the pool.
        return True, None

    if last_by_comp is None:
        required_pairs = {(r.competence_id, r.skill_level_id) for r in comp_rows}
        last_map = await _last_passed_percents(db, [employee_id], required_pairs)
        last_by_comp = last_map.get(employee_id, {})

    score = _comp_percent_from_map(comp_rows, last_by_comp)
    if score is None:
        return False, None
    threshold = card.match_percent if card.match_percent is not None else 80
    return score >= threshold, score


async def _load_work_exp_cache(
    db: AsyncSession,
    employee_ids: list[uuid.UUID],
    spec_rows: list[TalentCardSpecialization],
) -> dict[uuid.UUID, list[WorkExperience]]:
    """HRP-129: prefetch WorkExperience rows for the spec matcher.

    Returns an empty cache (which `_employee_spec_match` treats as
    "lookup on demand") when no Required Specializations are on the card —
    no point loading work history we won't read.
    """
    cache: dict[uuid.UUID, list[WorkExperience]] = {}
    if not spec_rows or not employee_ids:
        return {e: [] for e in employee_ids}
    rows = (
        (
            await db.execute(
                select(WorkExperience)
                .options(selectinload(WorkExperience.position))
                .where(WorkExperience.employee_id.in_(employee_ids))
            )
        )
        .scalars()
        .all()
    )
    for r in rows:
        cache.setdefault(r.employee_id, []).append(r)
    for e in employee_ids:
        cache.setdefault(e, [])
    return cache


async def _auto_populate_candidates(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
) -> None:
    """HRP-129 + HRP-214: recompute the Candidates auto-pool for the card.

    Triggered on requirement-block changes (Required Specializations,
    Required Competences) and on card creation. The pool is rebuilt in
    place over the existing `TalentCandidate` rows so downstream flows
    (appoint, respond, billing) stay on the same model.

    HRP-214 semantics for the per-row ``status``:
    * ``matched`` — employee qualifies for the card (auto-added rows
      start here; existing ``not_matched`` rows get promoted when they
      cross the threshold).
    * ``not_matched`` — manual pick from the Change/Add dialog that
      doesn't currently qualify. Stays in the pool until the recruiter
      removes it (auto-prune below only touches ``matched`` rows).
    * ``appointed`` — terminal; never overwritten by the recompute.

    A ``matched`` row that no longer qualifies is dropped (auto-prune,
    same as the legacy ``nominated`` behaviour); a row that DID qualify
    and was added manually as ``not_matched`` gets promoted to
    ``matched`` instead of being added a second time.
    """
    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        return

    comp_rows, spec_rows = await _fetch_match_inputs(db, card_id)

    employees = (
        (await db.execute(select(Employee).where(Employee.tenant_id == tenant_id)))
        .scalars()
        .all()
    )

    work_exp_cache = await _load_work_exp_cache(
        db, [e.id for e in employees], spec_rows
    )
    last_map: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    if comp_rows:
        required_pairs = {(r.competence_id, r.skill_level_id) for r in comp_rows}
        last_map = await _last_passed_percents(
            db, [e.id for e in employees], required_pairs
        )

    existing_rows = (
        (
            await db.execute(
                select(TalentCandidate).where(TalentCandidate.card_id == card_id)
            )
        )
        .scalars()
        .all()
    )
    existing_by_emp: dict[uuid.UUID, TalentCandidate] = {
        r.employee_id: r for r in existing_rows
    }

    qualifying_ids: set[uuid.UUID] = set()
    new_scores: dict[uuid.UUID, int | None] = {}
    for emp in employees:
        ok, score = await _employee_qualifies(
            db,
            card,
            emp.id,
            comp_rows=comp_rows,
            spec_rows=spec_rows,
            last_by_comp=last_map.get(emp.id, {}),
            work_exp_cache=work_exp_cache,
        )
        if ok:
            qualifying_ids.add(emp.id)
            new_scores[emp.id] = score

    # Auto-prune: rows in the `matched` bucket that no longer qualify
    # come off the pool (HRP-214 keeps the legacy `nominated` shrink
    # behaviour for auto-added rows). Manual `not_matched` picks stay.
    for row in existing_rows:
        if row.status != "matched":
            continue
        if row.employee_id not in qualifying_ids:
            await db.delete(row)

    # Insert new auto-picks, refresh scores for surviving matched rows,
    # and promote manual `not_matched` rows that now qualify.
    for emp_id in qualifying_ids:
        score = new_scores.get(emp_id)
        if emp_id in existing_by_emp:
            row = existing_by_emp[emp_id]
            if row.status == "matched":
                row.match_score = score
            elif row.status == "not_matched":
                row.status = "matched"
                row.match_score = score
            continue
        db.add(
            TalentCandidate(
                card_id=card_id,
                employee_id=emp_id,
                status="matched",
                match_score=score,
            )
        )

    # HRP-242: stamp the recompute timestamp so the Candidates block
    # header can render "today / yesterday / Month dd" labels.
    card.last_matched_at = datetime.now(timezone.utc)
    await db.commit()
