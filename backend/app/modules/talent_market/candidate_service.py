"""Talent card candidates: pool listing, breakdown, attach / appoint / remove, reactions.

Split from the former talent_market/service.py god-service
(project-review #20). ``service.py`` remains as a PEP 562 delegating
namespace so ``service.<name>`` keeps resolving to the wrapped
canonical functions.
"""

import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.modules.assessment.models import (
    Assessment,
    AssessmentCompetence,
    AssessmentResult,
)
from app.modules.auth.models import User
from app.modules.competence.models import Competence, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Employee, WorkExperience
from app.modules.position.models import Position
from app.modules.talent_market import common
from app.modules.talent_market.common import _candidate_to_read
from app.modules.talent_market.matching import (
    _comp_gap_rows,
    _comp_percent_from_map,
    _compute_match_score,
    _current_position_matches_spec,
    _done_status_id,
    _employee_current_position,
    _employee_current_position_matches_any_spec,
    _employee_experience_months,
    _employee_qualifies,
    _employee_spec_match,
    _fetch_match_inputs,
    _last_passed_percents,
    _load_work_exp_cache,
    _unique_comp_rows,
)
from app.modules.talent_market.models import (
    TalentCandidate,
    TalentCard,
    TalentCardSpecialization,
)

logger = logging.getLogger(__name__)


async def list_candidate_pool(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
    *,
    include_attached: bool = False,
) -> list[dict]:
    """HRP-95/HRP-129: rankable employee list for the Change/Add picker.

    By default excludes employees already attached as candidates on this
    card (Add dialog). With `include_attached=True` the Change dialog
    can pre-check existing rows. Result is sorted by match score
    descending (frontend's default view) but a stable secondary key by
    name keeps ties deterministic in tests.

    `status` reflects the HRP-129 qualification rule: an employee is
    "matched" when they clear the Required Specializations *and* their
    competence average is at or above the card's Match% threshold.
    """
    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)

    # HRP-214: in Change mode the picker also shows appointed candidates
    # so the recruiter can see the row (checkbox pre-checked + locked).
    # We track which attached employees are appointed so the UI can lock
    # their selection regardless of the recomputed match status.
    if include_attached:
        existing_emp_ids: set[uuid.UUID] = set()
        appointed_emp_ids: set[uuid.UUID] = {
            r[0]
            for r in (
                await db.execute(
                    select(TalentCandidate.employee_id).where(
                        TalentCandidate.card_id == card_id,
                        TalentCandidate.status == "appointed",
                    )
                )
            ).all()
        }
    else:
        existing_emp_ids = {
            r[0]
            for r in (
                await db.execute(
                    select(TalentCandidate.employee_id).where(
                        TalentCandidate.card_id == card_id
                    )
                )
            ).all()
        }
        appointed_emp_ids = set()

    employees = (
        (
            await db.execute(
                select(Employee)
                .where(Employee.tenant_id == tenant_id)
                .options(selectinload(Employee.user))
            )
        )
        .scalars()
        .all()
    )

    comp_rows, spec_rows = await _fetch_match_inputs(db, card_id)
    # HRP-665: "N of M" counts competences, not requirement rows. Resolved
    # once per card, outside the per-employee loop.
    unique_comp_rows = await _unique_comp_rows(db, comp_rows)
    work_exp_cache = await _load_work_exp_cache(
        db, [e.id for e in employees], spec_rows
    )
    last_map: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    if comp_rows:
        required_pairs = {(r.competence_id, r.skill_level_id) for r in comp_rows}
        last_map = await _last_passed_percents(
            db, [e.id for e in employees], required_pairs
        )
    # HRP-210: shared cache for the current-position fallback (one row
    # per employee), populated as the loop hits employees that didn't
    # already qualify via WorkExperience.
    current_pos_cache: dict[uuid.UUID, Position | None] = {}

    threshold = card.match_percent if card.match_percent is not None else 80
    items: list[dict] = []
    for emp in employees:
        if emp.id in existing_emp_ids:
            continue
        ok, score = await _employee_qualifies(
            db,
            card,
            emp.id,
            comp_rows=comp_rows,
            spec_rows=spec_rows,
            last_by_comp=last_map.get(emp.id, {}),
            work_exp_cache=work_exp_cache,
            current_pos_cache=current_pos_cache,
        )
        if comp_rows:
            basis = "competence" if score is not None else "none"
        elif spec_rows:
            basis = "specialization"
        else:
            basis = "none"
        if emp.id in appointed_emp_ids:
            # HRP-214: appointed candidates always render as Appointed in
            # the picker — their checkbox is locked (UI), so the matched/
            # not_matched evaluation isn't shown for them.
            status_val = "appointed"
        else:
            status_val = "matched" if ok else "not_matched"
        if emp.user:
            name = f"{emp.user.first_name} {emp.user.last_name}".strip()
        else:
            name = str(emp.id)
        # HRP-173: per-axis breakdown so the picker can colour-code the
        # Competencies + Experience cells independently. comp_match is the
        # projected competence percent (None when no qualifying assessment);
        # exp_months is total tenure on matching positions (None when no
        # spec requirement or no matching WorkExperience row).
        comp_match: int | None = None
        comp_met: int | None = None
        if comp_rows:
            comp_match = _comp_percent_from_map(comp_rows, last_map.get(emp.id, {}))
            # HRP-657: same "N of M cleared" reason the Candidates table
            # shows, so the picker explains its ranking too.
            comp_met = len(unique_comp_rows) - len(
                _comp_gap_rows(unique_comp_rows, last_map.get(emp.id, {}), threshold)
            )
        comp_qualifies = comp_match is not None and comp_match >= threshold
        exp_months: int | None = None
        exp_qualifies = False
        exp_via_current_position = False
        if spec_rows:
            exp_months = await _employee_experience_months(
                db, emp.id, spec_rows, work_exp_cache=work_exp_cache
            )
            exp_qualifies = await _employee_spec_match(
                db,
                emp.id,
                spec_rows,
                work_exp_cache=work_exp_cache,
                current_pos_cache=current_pos_cache,
            )
            # HRP-210: surface the current-position fallback so the
            # picker chip switches from red "no experience" to greyed
            # "has experience" and the drawer labels the row
            # accordingly.
            if exp_months is None and await _employee_current_position_matches_any_spec(
                db, emp.id, spec_rows, current_pos_cache=current_pos_cache
            ):
                exp_via_current_position = True
        items.append(
            {
                "employee_id": emp.id,
                "name": name or str(emp.id),
                "status": status_val,
                "match_score": score if score is not None else 0,
                "basis": basis,
                "comp_match": comp_match,
                "comp_qualifies": comp_qualifies,
                "comp_met": comp_met,
                "comp_total": len(unique_comp_rows) if comp_rows else None,
                "exp_months": exp_months,
                "exp_qualifies": exp_qualifies,
                "has_comp_requirement": bool(comp_rows),
                "has_spec_requirement": bool(spec_rows),
                "exp_via_current_position": exp_via_current_position,
                # HRP-258: feed ``EmployeeSummaryLine`` on the picker row.
                "position_title": emp.position_title,
                "employee_status": emp.status,
            }
        )

    # HRP-173 ranking in Add / Change picker:
    #   bucket 0 — fully qualifying candidates (comp pass AND, when card
    #              has Required Specs, exp pass): comp_match desc → name
    #   bucket 1 — comp-only passers (good on competence, fails on exp):
    #              comp_match desc → name
    #   bucket 2 — exp-only passers (good on exp, fails on comp):
    #              exp_months desc → name
    #   bucket 3 — everyone else: comp_match desc (fall back to match_score)
    #              → name
    def _bucket(item: dict) -> int:
        has_comp = item["has_comp_requirement"]
        has_spec = item["has_spec_requirement"]
        comp_pass = bool(item["comp_qualifies"])
        exp_pass = bool(item["exp_qualifies"])
        if has_comp and has_spec:
            if comp_pass and exp_pass:
                return 0
            if comp_pass:
                return 1
            if exp_pass:
                return 2
            return 3
        if has_comp:
            return 0 if comp_pass else 3
        if has_spec:
            return 0 if exp_pass else 3
        return 3

    def _sort_key(item: dict) -> tuple:
        bucket = _bucket(item)
        name = item["name"].lower()
        if bucket == 2:
            # exp-only passer: secondary key is exp_months desc
            months = item["exp_months"] if item["exp_months"] is not None else 0
            return (bucket, -months, name)
        pct = (
            item["comp_match"]
            if item["comp_match"] is not None
            else item["match_score"]
        )
        return (bucket, -pct, name)

    items.sort(key=_sort_key)
    return items


async def _other_level_results(
    db: AsyncSession,
    employee_id: uuid.UUID,
    competence_ids: set[uuid.UUID],
) -> dict[uuid.UUID, tuple[str, str | None, int]]:
    """HRP-695: {competence_id: (level title, level i18n_key, percent)} —
    the employee's best Done assessment of that competence at a level the
    matcher did not count.

    Reference data for the match drawer; it never reaches the scoring
    path. "Best" mirrors the Competences tab (HRP-153): the highest
    assessed level wins, the latest assessment breaks the tie. Levelless
    assessments are absent by construction (the join needs a
    ``skill_level_id``) — those already count toward the match.

    ponytail: reads the assessment's own ``AssessmentResult.percent``
    instead of re-projecting the per-level breakdown. A reference line
    does not need the cascade average, and the projection would cost a
    breakdown batch on every drawer open. Swap in
    ``compute_per_level_breakdowns_batch`` if the two numbers ever have
    to agree to the point.
    """
    if not competence_ids:
        return {}
    done_id = await _done_status_id(db)
    if done_id is None:
        return {}
    rows = (
        await db.execute(
            select(
                AssessmentCompetence.competence_id,
                SkillLevel.title,
                SkillLevel.i18n_key,
                SkillLevel.sort_index,
                Assessment.finished_at,
                AssessmentResult.percent,
            )
            .join(Assessment, Assessment.id == AssessmentCompetence.assessment_id)
            .join(
                AssessmentResult,
                and_(
                    AssessmentResult.assessment_id == Assessment.id,
                    AssessmentResult.competence_id
                    == AssessmentCompetence.competence_id,
                ),
            )
            .join(SkillLevel, SkillLevel.id == AssessmentCompetence.skill_level_id)
            .where(
                Assessment.status_id == done_id,
                Assessment.employee_id == employee_id,
                AssessmentCompetence.competence_id.in_(competence_ids),
                AssessmentResult.percent.isnot(None),
            )
            # Deterministic tie-break: without it, two done assessments at
            # the same level and timestamp resolve by planner row order.
            .order_by(
                SkillLevel.sort_index,
                Assessment.finished_at,
                Assessment.id,
            )
        )
    ).all()

    best: dict[uuid.UUID, tuple] = {}
    for comp_id, title, i18n_key, sort_index, finished_at, percent in rows:
        # ``finished_at is not None`` sits before the stamp itself so a
        # NULL one is never compared against a real datetime.
        rank = (sort_index or 0, finished_at is not None, finished_at or datetime.min)
        if comp_id not in best or rank > best[comp_id][0]:
            best[comp_id] = (rank, (title, i18n_key, int(percent)))
    return {comp_id: payload for comp_id, (_, payload) in best.items()}


async def get_candidate_breakdown(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> dict:
    """HRP-172: per-competence + per-spec breakdown feeding the match
    drawer (shadcn Sheet) on the card detail page.

    Reads the matcher's per-comp percent map and projects it to the
    required level via ``_last_passed_percents`` (HRP-129 REDO), then
    computes the per-spec experience-tenure summary via
    ``_employee_experience_months``. Returns the same data shape the
    Sheet renders directly — `actual_*` fields stay None when the
    employee has nothing matching the requirement.
    """
    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    emp = await db.get(Employee, employee_id)
    if not emp or emp.tenant_id != tenant_id:
        raise AppError("employee_not_found", status.HTTP_404_NOT_FOUND)
    if emp.user is None:
        await db.refresh(emp, ["user"])
    emp_name: str | None = None
    if emp.user is not None:
        emp_name = f"{emp.user.first_name} {emp.user.last_name}".strip() or None

    comp_rows, spec_rows = await _fetch_match_inputs(db, card_id)
    # HRP-665: the drawer lists competences, not requirement rows — the
    # same de-dup behind the Match cell's "N of M" and the gap plan, or a
    # card requiring one competence at two levels opens "1 of 4" onto a
    # list of 8. ``required_pairs`` below deliberately keeps every
    # (competence, level) pair — see _unique_comp_rows' docstring.
    unique_comp_rows = await _unique_comp_rows(db, comp_rows)
    threshold = card.match_percent if card.match_percent is not None else 80

    # Per-competence projected percent for the chosen Done assessments.
    last_map: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    if comp_rows:
        required_pairs = {(r.competence_id, r.skill_level_id) for r in comp_rows}
        last_map = await _last_passed_percents(db, [employee_id], required_pairs)
    per_comp = last_map.get(employee_id, {})

    # Resolve competence + skill level titles in one go to avoid N+1.
    comp_ids = {r.competence_id for r in unique_comp_rows}
    sl_ids = {
        r.skill_level_id for r in unique_comp_rows if r.skill_level_id is not None
    }
    comp_titles: dict[uuid.UUID, str] = {}
    if comp_ids:
        rows = (
            await db.execute(
                select(Competence.id, Competence.title).where(
                    Competence.id.in_(comp_ids)
                )
            )
        ).all()
        comp_titles = {r[0]: r[1] for r in rows}
    # HRP-479: carry i18n_key alongside the title so origin rows localize
    # in the match drawer (tenant rows keep a NULL key → verbatim).
    sl_titles: dict[uuid.UUID, tuple[str, str | None]] = {}
    if sl_ids:
        sl_rows = (
            await db.execute(
                select(SkillLevel.id, SkillLevel.title, SkillLevel.i18n_key).where(
                    SkillLevel.id.in_(sl_ids)
                )
            )
        ).all()
        sl_titles = {r[0]: (r[1], r[2]) for r in sl_rows}

    # HRP-695: a Done assessment of a required competence taken at a
    # *different* level never reaches the matcher — ``_last_passed_percents``
    # only counts the required level or higher — so the drawer read
    # "no assessment" while the employee had, say, an L3 result at 82%.
    # Shown as a reference line under the requirement; the percent above,
    # and the card's match score, stay exactly what the matcher computed.
    other_level = await _other_level_results(
        db,
        employee_id,
        {
            r.competence_id
            for r in unique_comp_rows
            if per_comp.get(r.competence_id) is None
        },
    )

    competences_payload: list[dict] = []
    for r in unique_comp_rows:
        actual = per_comp.get(r.competence_id)
        qualifies = actual is not None and actual >= threshold
        other = other_level.get(r.competence_id) if actual is None else None
        competences_payload.append(
            {
                "other_level_title": other[0] if other else None,
                "other_level_i18n_key": other[1] if other else None,
                "other_level_percent": other[2] if other else None,
                "competence_id": r.competence_id,
                "competence_title": comp_titles.get(r.competence_id) or "—",
                "required_skill_level_id": r.skill_level_id,
                "required_skill_level_title": (
                    sl_titles[r.skill_level_id][0]
                    if r.skill_level_id and r.skill_level_id in sl_titles
                    else None
                ),
                "required_skill_level_i18n_key": (
                    sl_titles[r.skill_level_id][1]
                    if r.skill_level_id and r.skill_level_id in sl_titles
                    else None
                ),
                "card_match_percent": threshold,
                "actual_percent": actual,
                "qualifies": qualifies,
            }
        )

    # Per-spec experience block — mirror the structure but split per row
    # so the drawer can highlight which spec was the bottleneck.
    spec_dict_ids: set[uuid.UUID] = set()
    for spec in spec_rows:
        spec_dict_ids.add(spec.specialization_id)
        if spec.grade_id is not None:
            spec_dict_ids.add(spec.grade_id)
    dict_titles: dict[uuid.UUID, tuple[str, str | None]] = {}
    if spec_dict_ids:
        dict_rows = (
            await db.execute(
                select(
                    DictionaryItem.id, DictionaryItem.title, DictionaryItem.i18n_key
                ).where(DictionaryItem.id.in_(spec_dict_ids))
            )
        ).all()
        dict_titles = {r[0]: (r[1], r[2]) for r in dict_rows}

    work_exps: list[WorkExperience] = []
    if spec_rows:
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
    today = date.today()
    # HRP-210: per-spec current-position fallback. Loaded lazily inside
    # the loop so cards that already match via WorkExperience don't pay
    # the extra Employee/Position fetch.
    current_pos_cache: dict[uuid.UUID, Position | None] = {}
    specs_payload: list[dict] = []
    for spec in spec_rows:
        matching_ids = [
            we.id
            for we in work_exps
            if we.position
            and we.position.specialization_id == spec.specialization_id
            and we.position.grade_id == spec.grade_id
        ]
        actual_months: int | None = None
        if matching_ids:
            total_days = 0
            for we in work_exps:
                if we.id not in matching_ids:
                    continue
                end = we.end_date or today
                if end > we.start_date:
                    total_days += (end - we.start_date).days
            actual_months = max(int(total_days // 30), 0)
        current_position_match = False
        # Only consult the current-position fallback when WorkExperience
        # came up empty for this spec — the drawer prefers tenure-based
        # numbers when they're available.
        # HRP-210 redo (2026-06-09): the drawer must show "Current
        # position" whenever the employee's current Position lines up
        # with the spec, even when the spec carries a non-zero
        # min_experience_years. Qualifies still respects the minimum.
        if actual_months is None:
            pos = await _employee_current_position(
                db, employee_id, current_pos_cache=current_pos_cache
            )
            if _current_position_matches_spec(pos, spec):
                current_position_match = True
        if spec.min_experience_years is None or spec.min_experience_years == 0:
            qualifies = actual_months is not None or current_position_match
        else:
            qualifies = (
                actual_months is not None
                and actual_months >= spec.min_experience_years * 12
            )
        specs_payload.append(
            {
                "specialization_id": spec.specialization_id,
                "specialization_title": (
                    dict_titles[spec.specialization_id][0]
                    if spec.specialization_id in dict_titles
                    else "—"
                ),
                "specialization_i18n_key": (
                    dict_titles[spec.specialization_id][1]
                    if spec.specialization_id in dict_titles
                    else None
                ),
                "grade_id": spec.grade_id,
                "grade_title": (
                    dict_titles[spec.grade_id][0]
                    if spec.grade_id is not None and spec.grade_id in dict_titles
                    else None
                ),
                "grade_i18n_key": (
                    dict_titles[spec.grade_id][1]
                    if spec.grade_id is not None and spec.grade_id in dict_titles
                    else None
                ),
                "required_years": spec.min_experience_years,
                "actual_months": actual_months,
                "qualifies": qualifies,
                "current_position_match": current_position_match,
            }
        )

    return {
        "employee_id": employee_id,
        "employee_name": emp_name,
        "card_match_percent": threshold,
        "competences": competences_payload,
        "specializations": specs_payload,
    }


async def add_candidate(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID, data
) -> dict:

    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    common.assert_card_not_terminal(card)

    # HRP-95: compute and persist match_score at add time so the row stays
    # comparable later even after the card requirements drift.
    match_score, _basis = await _compute_match_score(db, card, data.employee_id)
    # HRP-214: status now mirrors the qualification check so the
    # Candidates table renders matched / not_matched directly. Cards
    # with no requirements yet (`_employee_qualifies` returns False)
    # fall back to `not_matched`.
    comp_rows, spec_rows = await _fetch_match_inputs(db, card_id)
    ok, _ = await _employee_qualifies(
        db, card, data.employee_id, comp_rows=comp_rows, spec_rows=spec_rows
    )
    status_val = "matched" if ok else "not_matched"

    candidate = TalentCandidate(
        card_id=card_id,
        employee_id=data.employee_id,
        status=status_val,
        match_score=match_score,
    )
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)

    emp = await db.get(Employee, candidate.employee_id)
    emp_name = (
        f"{emp.user.first_name} {emp.user.last_name}" if emp and emp.user else None
    )

    # HRP-211: adding a candidate to a Published card emails them.
    # Draft additions stay silent — the publish transition will fan
    # out once the card goes public.
    if card.status == "published":
        await common._dispatch_lifecycle_emails(
            db,
            card,
            "candidate_added",
            only_candidate_ids=[candidate.id],
        )

    return _candidate_to_read(
        candidate,
        emp_name,
        position_title=emp.position_title if emp else None,
        employee_status=emp.status if emp else None,
    )


async def add_candidates_bulk(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID, data
) -> list[dict]:
    """HRP-95: attach multiple employees from the picker dialog.

    Employees already on the card are silently skipped so resubmitting the
    same selection (e.g. the user clicks Add twice) isn't an error.
    Match score is computed and stored per row.
    """
    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    common.assert_card_not_terminal(card)

    existing_emp_ids = {
        r[0]
        for r in (
            await db.execute(
                select(TalentCandidate.employee_id).where(
                    TalentCandidate.card_id == card_id
                )
            )
        ).all()
    }

    # HRP-95: prefetch once — same N+1 reasoning as list_candidate_pool.
    comp_rows, spec_rows = await _fetch_match_inputs(db, card_id)
    last_map: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    if comp_rows and data.employee_ids:
        required_pairs = {(r.competence_id, r.skill_level_id) for r in comp_rows}
        last_map = await _last_passed_percents(
            db, list(data.employee_ids), required_pairs
        )
    # HRP-214: prefetch the work-exp cache once so each row's
    # qualification check doesn't re-issue the same SQL N times.
    work_exp_cache = await _load_work_exp_cache(db, list(data.employee_ids), spec_rows)

    out: list[dict] = []
    for emp_id in data.employee_ids:
        if emp_id in existing_emp_ids:
            continue
        emp = await db.get(Employee, emp_id)
        if not emp or emp.tenant_id != tenant_id:
            # Reject the whole batch — the UI should never send a foreign id.
            raise AppError(
                "tm_employee_id_not_found",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                employee_id=emp_id,
            )
        if comp_rows:
            score = _comp_percent_from_map(comp_rows, last_map.get(emp_id, {}))
        else:
            score = None
        # HRP-214: status mirrors current qualification per row.
        ok, _ = await _employee_qualifies(
            db,
            card,
            emp_id,
            comp_rows=comp_rows,
            spec_rows=spec_rows,
            last_by_comp=last_map.get(emp_id, {}),
            work_exp_cache=work_exp_cache,
        )
        candidate = TalentCandidate(
            card_id=card_id,
            employee_id=emp_id,
            status="matched" if ok else "not_matched",
            match_score=score,
        )
        db.add(candidate)
        await db.flush()
        existing_emp_ids.add(emp_id)
        emp_name = f"{emp.user.first_name} {emp.user.last_name}" if emp.user else None
        out.append(
            _candidate_to_read(
                candidate,
                emp_name,
                position_title=emp.position_title,
                employee_status=emp.status,
            )
        )

    # HRP-242: any manual edit through the picker counts as a recompute
    # for the "last match" label — stamp even when the diff turned out
    # empty so a no-op Save still refreshes the header.
    card.last_matched_at = datetime.now(timezone.utc)
    await db.commit()
    # HRP-211: bulk-added candidates on a Published card all get the
    # email; on a Draft card we stay silent (publish fans out later).
    if card.status == "published" and out:
        await common._dispatch_lifecycle_emails(
            db,
            card,
            "candidate_added",
            only_candidate_ids=[row["id"] for row in out],
        )
    return out


async def delete_candidate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> None:
    """HRP-95: drop a candidate row by employee id.

    Used by the Change-candidates picker on Save: the dialog diffs the
    pre-selected and final sets and the unchecked rows fall through to
    this endpoint. Looks up by ``(card_id, employee_id)`` because the UI
    only carries employee ids — TalentCandidate.id is not exposed on the
    picker.
    """
    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    common.assert_card_not_terminal(card)
    row = (
        await db.execute(
            select(TalentCandidate).where(
                TalentCandidate.card_id == card_id,
                TalentCandidate.employee_id == employee_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError("candidate_not_found", status.HTTP_404_NOT_FOUND)
    # HRP-245: notify the dropped employee when the card is already
    # Published. Capture the employee id before delete so we can resolve
    # the user after commit; the dispatcher branch is the same shape as
    # appointed/cancelled and absorbs any email-side errors internally.
    notify_employee_id = row.employee_id if card.status == "published" else None
    await db.delete(row)
    # HRP-242: removing a candidate via the Change picker is also a
    # manual recompute — refresh the stamp so the header label stays
    # in sync with the current Candidates view.
    card.last_matched_at = datetime.now(timezone.utc)
    await db.commit()

    if notify_employee_id is not None:
        # HRP-245 review fix: the dispatcher does DB lookups and template
        # renders that could raise long after the row is already deleted;
        # don't let those bubble up as a 500 on the DELETE endpoint.
        try:
            await common._dispatch_lifecycle_emails(
                db,
                card,
                "candidate_removed_from_published",
                removed_employee_ids=[notify_employee_id],
            )
        except Exception:
            logger.exception(
                "Talent Market candidate-removed dispatch failed for card_id=%s, employee_id=%s",
                card_id,
                notify_employee_id,
            )


async def appoint_candidate(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID, candidate_id: uuid.UUID
) -> dict:
    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    common.assert_card_not_terminal(card)

    candidate = await db.get(TalentCandidate, candidate_id)
    if not candidate or candidate.card_id != card_id:
        raise AppError("candidate_not_found", status.HTTP_404_NOT_FOUND)

    candidate.status = "appointed"
    candidate.appointed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(candidate)

    emp = await db.get(Employee, candidate.employee_id)
    emp_name = (
        f"{emp.user.first_name} {emp.user.last_name}" if emp and emp.user else None
    )
    emp_position_title = emp.position_title if emp else None
    emp_status_val = emp.status if emp else None

    # HRP-211: appointee + their manager get the appointment mail.
    await common._dispatch_lifecycle_emails(
        db, card, "appointed", only_candidate_ids=[candidate.id]
    )

    return _candidate_to_read(
        candidate,
        emp_name,
        position_title=emp_position_title,
        employee_status=emp_status_val,
    )


async def _pick_plan_specialization(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    spec_rows: list[TalentCardSpecialization],
    gaps: list,
) -> TalentCardSpecialization | None:
    """HRP-665: which Required Specialization the gap plan is built against.

    The pick is not cosmetic — it selects the material override set
    (``get_materials_for_specialization``) and the grade the plan header
    shows. Taking ``spec_rows[0]`` off an unordered query meant a card with
    two Required Specializations stamped a different material set on
    identical inputs from one call to the next.

    Prefer the ladder that actually covers the most of the employee's gaps;
    ``max`` keeps the first of equal candidates and ``_fetch_match_inputs``
    orders rows by id, so ties resolve the same way every time.
    """
    if len(spec_rows) < 2:
        return spec_rows[0] if spec_rows else None

    from app.modules.grade_system.models import (
        GradeCompetenceLink,
        GradeSpecialization,
    )

    gap_ids = {row.competence_id for row in gaps}
    covered: dict[tuple[uuid.UUID, uuid.UUID | None], set[uuid.UUID]] = {}
    grade_ids = {s.grade_id for s in spec_rows if s.grade_id is not None}
    if grade_ids:
        rows = (
            await db.execute(
                select(
                    GradeSpecialization.specialization_id,
                    GradeSpecialization.grade_id,
                    GradeCompetenceLink.competence_id,
                )
                .join(
                    GradeCompetenceLink,
                    GradeCompetenceLink.grade_specialization_id
                    == GradeSpecialization.id,
                )
                .where(
                    GradeSpecialization.tenant_id == tenant_id,
                    GradeSpecialization.grade_id.in_(grade_ids),
                    GradeSpecialization.specialization_id.in_(
                        {s.specialization_id for s in spec_rows}
                    ),
                )
            )
        ).all()
        for spec_id, grade_id, comp_id in rows:
            covered.setdefault((spec_id, grade_id), set()).add(comp_id)

    return max(
        spec_rows,
        key=lambda s: len(
            covered.get((s.specialization_id, s.grade_id), set()) & gap_ids
        ),
    )


async def create_candidate_development_plan(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
    candidate_id: uuid.UUID,
    author_id: uuid.UUID,
    data,
) -> dict:
    """HRP-665: build a development plan from the candidate's competence gaps.

    The plan items are exactly the card's Required Competences whose
    projected percent is below the card's Match% threshold (or that the
    employee has never been assessed on) — required vs current, nothing
    else. The created plan is linked back through the long-declared
    ``TalentCandidate.pdp_id`` column.

    Delegates to ``pdp_service.create_pdp`` through the module (not a
    from-import) so the billing wrapper installed at startup is the one
    that runs — the plan is charged once, as ``pdp.create``, and the
    active-plan cap (409 ``pdp_active_limit_reached``) applies here too.

    Appointment order does not matter: a candidate can get the plan before
    or after ``appoint_candidate`` — neither touches the other's column.
    """
    from app.modules.assessment import pdp_service
    from app.modules.assessment.schemas import CompetenceCriteriaItem, PDPCreate

    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    common.assert_card_not_terminal(card)

    candidate = await db.get(TalentCandidate, candidate_id)
    if not candidate or candidate.card_id != card_id:
        raise AppError("candidate_not_found", status.HTTP_404_NOT_FOUND)
    if candidate.pdp_id is not None:
        raise AppError("tm_candidate_plan_exists", status.HTTP_409_CONFLICT)

    comp_rows, spec_rows = await _fetch_match_inputs(db, card_id)
    if not comp_rows:
        raise AppError("tm_no_required_competences", status.HTTP_409_CONFLICT)
    threshold = card.match_percent if card.match_percent is not None else 80
    required_pairs = {(r.competence_id, r.skill_level_id) for r in comp_rows}
    last_map = await _last_passed_percents(db, [candidate.employee_id], required_pairs)
    # HRP-665: one gap per competence — a card requiring the same
    # competence through two grade ladders used to produce two identical
    # PDP items, each with its own material set.
    gaps = _comp_gap_rows(
        await _unique_comp_rows(db, comp_rows),
        last_map.get(candidate.employee_id, {}),
        threshold,
    )
    if not gaps:
        raise AppError("tm_no_competence_gaps", status.HTTP_409_CONFLICT)

    # The target Specialization picks the material override set and shows
    # on the plan header.
    spec = await _pick_plan_specialization(db, tenant_id, spec_rows, gaps)

    # The back-link rides inside create_pdp's own commit: the plan, the
    # billing charge and ``candidate.pdp_id`` land atomically, so an
    # interruption between "plan committed" and "candidate linked" can no
    # longer strand a paid orphan plan behind the pdp_id-is-None guard
    # above (HRP-654 review).
    async def _link_candidate(plan) -> None:
        candidate.pdp_id = plan.id

    pdp = await pdp_service.create_pdp(
        db,
        tenant_id,
        author_id,
        PDPCreate(
            title=(data.title if data and data.title else card.title)[:100],
            employee_id=candidate.employee_id,
            specialization_id=spec.specialization_id if spec else None,
            grade_id=spec.grade_id if spec else None,
            competences=[
                CompetenceCriteriaItem(
                    competence_id=row.competence_id,
                    skill_level_id=row.skill_level_id,
                )
                for row in gaps
            ],
        ),
        before_commit=_link_candidate,
    )

    await db.refresh(candidate)

    emp = await db.get(Employee, candidate.employee_id)
    emp_name = (
        f"{emp.user.first_name} {emp.user.last_name}" if emp and emp.user else None
    )
    return _candidate_to_read(
        candidate,
        emp_name,
        pdp_status=pdp["status"],
        position_title=emp.position_title if emp else None,
        employee_status=emp.status if emp else None,
    )


# ---------------------------------------------------------------------------
# HRP-213 — React (employee response on a Published card)
# ---------------------------------------------------------------------------


async def react_to_card(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
    user: User,
) -> dict:
    """HRP-213: an employee reacts to a Published card they're a
    candidate on.

    Idempotency rules from the spec:
      * Card must be Published.
      * Caller must have an Employee row in the same tenant.
      * Caller must be a TalentCandidate on the card and NOT in the
        ``appointed`` bucket — those rows hide the React action.
      * Already-reacted rows (response_at is set) are rejected with
        409 so the UI never shows React twice for the same candidate.

    Stamps ``response_at`` on the candidate row, then enqueues the
    "Your employee has reacted" mail to the manager (if any).
    """
    from app.core.access_scope import get_current_employee

    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    if card.status != "published":
        raise AppError(
            "tm_card_not_open_for_reactions",
            status.HTTP_409_CONFLICT,
        )
    emp = await get_current_employee(db, user)
    if emp is None:
        raise AppError("tm_no_employee_profile", status.HTTP_403_FORBIDDEN)
    row = (
        await db.execute(
            select(TalentCandidate).where(
                TalentCandidate.card_id == card_id,
                TalentCandidate.employee_id == emp.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError("candidate_not_found", status.HTTP_404_NOT_FOUND)
    if row.status == "appointed":
        raise AppError(
            "tm_appointed_cannot_react",
            status.HTTP_409_CONFLICT,
        )
    if row.response_at is not None:
        raise AppError("tm_already_reacted", status.HTTP_409_CONFLICT)
    row.response_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)

    # Manager-side email. Mirrors the appointed/cancelled flows — when
    # the employee manages their own division (self-managed), skip the
    # extra mail; the employee already knows they reacted.
    import contextlib as _cl

    from app.core.email import enqueue_email
    from app.core.email_templates import (
        render_talent_market_reacted_manager_email,
    )
    from app.core.i18n import resolve_locale
    from app.modules.company.models import Division, Tenant

    if emp.division_id is not None:
        div = await db.get(Division, emp.division_id)
        if div is not None and div.manager_id is not None:
            mgr_emp = await db.get(Employee, div.manager_id)
            if mgr_emp is not None and mgr_emp.user_id is not None:
                mgr_user = await db.get(User, mgr_emp.user_id)
                if mgr_user is not None and mgr_user.id != user.id and mgr_user.email:
                    emp_name = (
                        f"{user.first_name} {user.last_name}".strip()
                        if user.first_name or user.last_name
                        else None
                    )
                    # i18n F4: the letter is rendered for the manager, not
                    # for the reacting employee — Manager.language first,
                    # then the card's tenant default.
                    tenant = (
                        await db.get(Tenant, card.tenant_id)
                        if card.tenant_id is not None
                        else None
                    )
                    subject, body = render_talent_market_reacted_manager_email(
                        card.title,
                        emp_name,
                        str(card.id),
                        locale=resolve_locale(
                            user_language=mgr_user.language,
                            tenant_default=(
                                tenant.default_locale if tenant is not None else None
                            ),
                        ),
                    )
                    with _cl.suppress(Exception):
                        enqueue_email(
                            mgr_user.email,
                            subject,
                            body,
                            tenant_id=str(card.tenant_id) if card.tenant_id else None,
                            template_code="talent_market.lifecycle",
                        )

    emp_name = f"{emp.user.first_name} {emp.user.last_name}" if emp.user else None
    return _candidate_to_read(
        row,
        emp_name,
        is_me=True,
        position_title=emp.position_title,
        employee_status=emp.status,
    )
