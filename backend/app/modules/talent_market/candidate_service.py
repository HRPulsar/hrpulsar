"""Talent card candidates: pool listing, breakdown, attach / appoint / remove, reactions.

Split from the former talent_market/service.py god-service
(project-review #20). ``service.py`` remains as a PEP 562 delegating
namespace so ``service.<name>`` keeps resolving to the wrapped
canonical functions.
"""

import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import User
from app.modules.competence.models import Competence, SkillLevel
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee.models import Employee, WorkExperience
from app.modules.position.models import Position
from app.modules.talent_market import common
from app.modules.talent_market.common import _candidate_to_read
from app.modules.talent_market.matching import (
    _comp_percent_from_map,
    _compute_match_score,
    _current_position_matches_spec,
    _employee_current_position,
    _employee_current_position_matches_any_spec,
    _employee_experience_months,
    _employee_qualifies,
    _employee_spec_match,
    _fetch_match_inputs,
    _last_passed_percents,
    _load_work_exp_cache,
)
from app.modules.talent_market.models import (
    TalentCandidate,
    TalentCard,
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")

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
        if comp_rows:
            comp_match = _comp_percent_from_map(comp_rows, last_map.get(emp.id, {}))
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
            if (
                exp_months is None
                and await _employee_current_position_matches_any_spec(
                    db, emp.id, spec_rows, current_pos_cache=current_pos_cache
                )
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    emp = await db.get(Employee, employee_id)
    if not emp or emp.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    if emp.user is None:
        await db.refresh(emp, ["user"])
    emp_name: str | None = None
    if emp.user is not None:
        emp_name = f"{emp.user.first_name} {emp.user.last_name}".strip() or None

    comp_rows, spec_rows = await _fetch_match_inputs(db, card_id)
    threshold = card.match_percent if card.match_percent is not None else 80

    # Per-competence projected percent for the chosen Done assessments.
    last_map: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    if comp_rows:
        required_pairs = {(r.competence_id, r.skill_level_id) for r in comp_rows}
        last_map = await _last_passed_percents(db, [employee_id], required_pairs)
    per_comp = last_map.get(employee_id, {})

    # Resolve competence + skill level titles in one go to avoid N+1.
    comp_ids = {r.competence_id for r in comp_rows}
    sl_ids = {r.skill_level_id for r in comp_rows if r.skill_level_id is not None}
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
    sl_titles: dict[uuid.UUID, str] = {}
    if sl_ids:
        rows = (
            await db.execute(
                select(SkillLevel.id, SkillLevel.title).where(SkillLevel.id.in_(sl_ids))
            )
        ).all()
        sl_titles = {r[0]: r[1] for r in rows}

    competences_payload: list[dict] = []
    for r in comp_rows:
        actual = per_comp.get(r.competence_id)
        qualifies = actual is not None and actual >= threshold
        competences_payload.append(
            {
                "competence_id": r.competence_id,
                "competence_title": comp_titles.get(r.competence_id) or "—",
                "required_skill_level_id": r.skill_level_id,
                "required_skill_level_title": (
                    sl_titles.get(r.skill_level_id) if r.skill_level_id else None
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
    dict_titles: dict[uuid.UUID, str] = {}
    if spec_dict_ids:
        rows = (
            await db.execute(
                select(DictionaryItem.id, DictionaryItem.title).where(
                    DictionaryItem.id.in_(spec_dict_ids)
                )
            )
        ).all()
        dict_titles = {r[0]: r[1] for r in rows}

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
                "specialization_title": dict_titles.get(spec.specialization_id) or "—",
                "grade_id": spec.grade_id,
                "grade_title": (
                    dict_titles.get(spec.grade_id)
                    if spec.grade_id is not None
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
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
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Employee {emp_id} not found",
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    common.assert_card_not_terminal(card)

    candidate = await db.get(TalentCandidate, candidate_id)
    if not candidate or candidate.card_id != card_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")

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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    if card.status != "published":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Card is not open for reactions",
        )
    emp = await get_current_employee(db, user)
    if emp is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No employee profile")
    row = (
        await db.execute(
            select(TalentCandidate).where(
                TalentCandidate.card_id == card_id,
                TalentCandidate.employee_id == emp.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
    if row.status == "appointed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Appointed candidates cannot react",
        )
    if row.response_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already reacted")
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
    from app.modules.company.models import Division

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
                    subject, body = render_talent_market_reacted_manager_email(
                        card.title, emp_name, str(card.id)
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
