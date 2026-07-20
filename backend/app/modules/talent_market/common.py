"""Shared talent-market helpers: read-model converters and lifecycle email dispatch.

Split from the former talent_market/service.py god-service
(project-review #20). ``service.py`` remains as a PEP 562 delegating
namespace so ``service.<name>`` keeps resolving to the wrapped
canonical functions.
"""

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import User
from app.modules.employee.models import Employee
from app.modules.talent_market.models import (
    TalentCandidate,
    TalentCard,
)

logger = logging.getLogger(__name__)

# HRP-291: statuses where the card is closed for good — every mutation
# (details, requirements, candidate list, appointments) must be rejected.
# "closed" is the legacy pre-HRP-92 terminal value kept for historic rows.
TERMINAL_STATUSES = frozenset({"completed", "cancelled", "closed"})


def assert_card_not_terminal(card: TalentCard) -> None:
    """HRP-291: reject any mutation on a Completed / Cancelled card."""
    if card.status in TERMINAL_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Card is {card.status} — no further changes are allowed.",
        )


# ---------------------------------------------------------------------------
# HRP-211 — lifecycle email dispatch
# ---------------------------------------------------------------------------


async def _dispatch_lifecycle_emails(
    db: AsyncSession,
    card: TalentCard,
    event: str,
    *,
    only_candidate_ids: list[uuid.UUID] | None = None,
    appointed_before_cancel: list[uuid.UUID] | None = None,
    removed_employee_ids: list[uuid.UUID] | None = None,
) -> None:
    """Send the Talent Market lifecycle email batch for ``card``.

    ``event`` ∈ {"published", "candidate_added", "appointed", "completed",
    "cancelled_from_draft", "cancelled_from_published",
    "candidate_removed_from_published"}.

    ``removed_employee_ids`` carries the employee ids whose TalentCandidate
    rows were just deleted from a Published card — HRP-245 ships the
    "no longer considered" notice using this set, because by the time we
    dispatch the rows themselves are gone.

    ``only_candidate_ids`` restricts delivery to a subset of candidate
    rows — used by ``candidate_added`` (single employee) and
    ``appointed`` (the just-appointed employee + their manager).

    ``appointed_before_cancel`` carries the candidate ids that were
    appointed *immediately before* the cancel transition fired —
    cancel_card flips them off ``appointed`` before this helper runs, so
    we need the pre-state to know which managers/employees deserve the
    "appointment cancelled" mail.

    The helper is wrapped in a try/except suppression at every send
    point — email failures must never block the underlying transition.
    """
    import contextlib

    from app.core.email import enqueue_email
    from app.core.email_templates import (
        render_talent_market_appointed_manager_email,
        render_talent_market_appointed_self_email,
        render_talent_market_cancelled_generic_email,
        render_talent_market_cancelled_manager_email,
        render_talent_market_cancelled_manager_plural_email,
        render_talent_market_cancelled_self_email,
        render_talent_market_completed_email,
        render_talent_market_matched_email,
        render_talent_market_not_matched_email,
        render_talent_market_removed_candidate_email,
    )

    title = card.title
    card_id = str(card.id)
    tenant_id_str = str(card.tenant_id) if card.tenant_id else None

    candidates = list(
        (
            await db.execute(
                select(TalentCandidate).where(TalentCandidate.card_id == card.id)
            )
        )
        .scalars()
        .all()
    )

    def _candidate_filter(c: TalentCandidate) -> bool:
        if only_candidate_ids is None:
            return True
        return c.id in only_candidate_ids

    # Prefetch Employee + User for every candidate in a single round-trip so
    # the per-candidate loops below stay O(1) on DB hits. Missing employees
    # (deleted between candidate creation and dispatch) are simply absent
    # from the cache, so the fallback inside _resolve_employee handles them.
    emp_user_cache: dict[uuid.UUID, tuple[Employee, User | None]] = {}
    candidate_emp_ids = {c.employee_id for c in candidates if c.employee_id is not None}
    if candidate_emp_ids:
        prefetched = (
            (
                await db.execute(
                    select(Employee)
                    .options(selectinload(Employee.user))
                    .where(Employee.id.in_(candidate_emp_ids))
                )
            )
            .scalars()
            .all()
        )
        for prefetched_emp in prefetched:
            emp_user_cache[prefetched_emp.id] = (prefetched_emp, prefetched_emp.user)

    async def _resolve_employee(
        emp_id: uuid.UUID,
    ) -> tuple[Employee | None, User | None]:
        cached = emp_user_cache.get(emp_id)
        if cached is not None:
            return cached[0], cached[1]
        loaded = await db.get(Employee, emp_id)
        if loaded is None:
            return None, None
        usr = await db.get(User, loaded.user_id) if loaded.user_id else None
        emp_user_cache[emp_id] = (loaded, usr)
        return loaded, usr

    async def _send(email: str | None, rendered: tuple[str, str]) -> None:
        if not email:
            return
        subject, body = rendered
        with contextlib.suppress(Exception):
            enqueue_email(
                email,
                subject,
                body,
                tenant_id=tenant_id_str,
                template_code="talent_market.lifecycle",
            )

    async def _resolve_manager_user(
        emp: Employee | None,
    ) -> User | None:
        if emp is None or emp.division_id is None:
            return None
        from app.modules.company.models import Division

        div = await db.get(Division, emp.division_id)
        if div is None or div.manager_id is None:
            return None
        mgr_emp = await db.get(Employee, div.manager_id)
        if mgr_emp is None or mgr_emp.user_id is None:
            return None
        return await db.get(User, mgr_emp.user_id)

    if event in {"published", "candidate_added"}:
        for cand in candidates:
            if not _candidate_filter(cand):
                continue
            emp, usr = await _resolve_employee(cand.employee_id)
            if usr is None:
                continue
            if cand.status == "matched":
                await _send(
                    usr.email,
                    render_talent_market_matched_email(title, card_id),
                )
            elif cand.status == "not_matched":
                await _send(
                    usr.email,
                    render_talent_market_not_matched_email(title, card_id),
                )

    elif event == "appointed":
        for cand in candidates:
            if not _candidate_filter(cand):
                continue
            if cand.status != "appointed":
                continue
            emp, usr = await _resolve_employee(cand.employee_id)
            if usr is not None:
                await _send(
                    usr.email,
                    render_talent_market_appointed_self_email(title, card_id),
                )
            mgr_user = await _resolve_manager_user(emp)
            # HRP-211 redo (2026-06-09): when the employee manages their
            # own division (manager_id == self), the appointed-self email
            # already covers them — skip the duplicate manager mail.
            if mgr_user is not None and (usr is None or mgr_user.id != usr.id):
                emp_name = f"{usr.first_name} {usr.last_name}".strip() if usr else None
                await _send(
                    mgr_user.email,
                    render_talent_market_appointed_manager_email(
                        title, emp_name, card_id
                    ),
                )

    elif event == "completed":
        for cand in candidates:
            if cand.status not in {"matched", "not_matched"}:
                continue
            emp, usr = await _resolve_employee(cand.employee_id)
            if usr is None:
                continue
            await _send(
                usr.email,
                render_talent_market_completed_email(title, card_id),
            )

    elif event == "cancelled_from_draft":
        appointed_ids = set(appointed_before_cancel or [])
        for cand in candidates:
            if cand.employee_id not in appointed_ids:
                continue
            emp, usr = await _resolve_employee(cand.employee_id)
            if usr is not None:
                await _send(
                    usr.email,
                    render_talent_market_cancelled_self_email(title, card_id),
                )
            mgr_user = await _resolve_manager_user(emp)
            # HRP-211 redo (2026-06-09): self-managed employees get only
            # the appointed-self cancellation mail — drop the duplicate
            # manager copy when manager.user == employee.user.
            if mgr_user is not None and (usr is None or mgr_user.id != usr.id):
                emp_name = f"{usr.first_name} {usr.last_name}".strip() if usr else None
                await _send(
                    mgr_user.email,
                    render_talent_market_cancelled_manager_email(
                        title, emp_name, card_id
                    ),
                )

    elif event == "candidate_removed_from_published":
        # HRP-245: the candidate row is already deleted at this point, so
        # we iterate the captured employee ids directly. ``_resolve_employee``
        # falls back to ``db.get(Employee, ...)`` when the row is missing
        # from the prefetch cache, so this still resolves the user mailbox.
        for emp_id in removed_employee_ids or []:
            _emp, usr = await _resolve_employee(emp_id)
            if usr is None:
                continue
            await _send(
                usr.email,
                render_talent_market_removed_candidate_email(title, card_id),
            )

    elif event == "cancelled_from_published":
        appointed_ids = set(appointed_before_cancel or [])
        # Bucket A — appointed employees: self mail + manager mail
        # (managers get a plural mail when several of their employees
        # were appointed on the same card).
        manager_buckets: dict[uuid.UUID, list[str]] = {}
        for cand in candidates:
            if cand.employee_id not in appointed_ids:
                continue
            emp, usr = await _resolve_employee(cand.employee_id)
            if usr is not None:
                await _send(
                    usr.email,
                    render_talent_market_cancelled_self_email(title, card_id),
                )
            mgr_user = await _resolve_manager_user(emp)
            if mgr_user is None or mgr_user.id is None:
                continue
            # HRP-211 redo (2026-06-09): self-managed appointees already
            # got the cancelled-self mail above — don't bucket them under
            # the manager flow or they end up with two letters.
            if usr is not None and mgr_user.id == usr.id:
                continue
            emp_name = f"{usr.first_name} {usr.last_name}".strip() if usr else None
            manager_buckets.setdefault(mgr_user.id, []).append(
                emp_name or "your employee"
            )
        for mgr_id, names in manager_buckets.items():
            mgr_user = await db.get(User, mgr_id)
            if mgr_user is None:
                continue
            if len(names) == 1:
                rendered = render_talent_market_cancelled_manager_email(
                    title, names[0], card_id
                )
            else:
                rendered = render_talent_market_cancelled_manager_plural_email(
                    title, names, card_id
                )
            await _send(mgr_user.email, rendered)
        # Bucket B — matched / not_matched: a "Cancelled" notice.
        for cand in candidates:
            if cand.status not in {"matched", "not_matched"}:
                continue
            emp, usr = await _resolve_employee(cand.employee_id)
            if usr is None:
                continue
            await _send(
                usr.email,
                render_talent_market_cancelled_generic_email(title, card_id),
            )


def _card_to_read(c: TalentCard, *, reacted_by_me: bool = False) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "description": c.description,
        "card_type": c.card_type,
        "status": c.status,
        "author_id": c.author_id,
        "division_id": c.division_id,
        "is_published": c.is_published,
        "tenant_id": c.tenant_id,
        "published_at": c.published_at,
        # `closed_at` stays on the response for legacy clients; HRP-92 REDO
        # adds `completed_at` / `cancelled_at` so the UI can render
        # assessment-style "Completed: yyyy-mm-dd" / "Cancelled: yyyy-mm-dd"
        # labels.
        "closed_at": c.closed_at,
        "completed_at": c.completed_at,
        "cancelled_at": c.cancelled_at,
        "start_date": c.start_date,
        "end_date": c.end_date,
        "match_percent": c.match_percent,
        "created_at": c.created_at,
        # HRP-242: drives the "last match: today / yesterday / Month dd"
        # label in the Candidates block header.
        "last_matched_at": c.last_matched_at,
        # HRP-213: per-viewer flag — True when the current employee has
        # already reacted on this card. Default False for callers that
        # don't carry a viewer (background fan-out, internal helpers).
        "reacted_by_me": reacted_by_me,
    }


def _card_to_detail(
    c: TalentCard,
    *,
    visible_employee_ids: set[uuid.UUID] | None = None,
    breakdown_by_emp: dict[uuid.UUID, dict] | None = None,
    viewer_employee_id: uuid.UUID | None = None,
    reacted_by_me: bool = False,
) -> dict:
    """Card detail with embedded candidates.

    `visible_employee_ids` gates `can_view_profile` on each candidate per
    HRP-149: `None` (admin / hr / platform_admin) → every candidate is
    linkable; an empty / scoped set narrows the link to the manager's
    division subtree or to the employee's own row. The argument
    defaults to `None` so internal callers that don't have a User in
    context (e.g. background pool rebuilds) keep the legacy behaviour.

    `breakdown_by_emp` carries the HRP-173 per-axis match data
    ({employee_id: {comp_match, comp_qualifies, exp_months,
    exp_qualifies}}). When omitted, candidates render with all the new
    fields falsy / null — kept that way so background callers don't pay
    the cost of computing it.
    """
    data = _card_to_read(c, reacted_by_me=reacted_by_me)
    data["specializations"] = [
        {
            "id": s.id,
            "specialization_id": s.specialization_id,
            "grade_id": s.grade_id,
            "min_experience_years": s.min_experience_years,
        }
        for s in c.specializations
    ]
    data["competences"] = [
        {
            "id": co.id,
            "competence_id": co.competence_id,
            "skill_level_id": co.skill_level_id,
            "match_percent": co.match_percent,
        }
        for co in c.competences
    ]
    data["requirements"] = [
        {
            "id": r.id,
            "description": r.description,
            "min_experience_years": r.min_experience_years,
        }
        for r in c.requirements
    ]
    has_comp = len(c.competences) > 0
    has_spec = len(c.specializations) > 0

    def _basis_for(score: int | None) -> str:
        if has_comp:
            return "competence" if score is not None else "none"
        if has_spec:
            return "specialization"
        return "none"

    def _can_view(employee_id: uuid.UUID) -> bool:
        return visible_employee_ids is None or employee_id in visible_employee_ids

    candidate_dicts: list[dict] = []
    for ca in c.candidates:
        bd = (breakdown_by_emp or {}).get(ca.employee_id, {})
        candidate_dicts.append(
            _candidate_to_read(
                ca,
                (
                    f"{ca.employee.user.first_name} {ca.employee.user.last_name}"
                    if ca.employee and ca.employee.user
                    else None
                ),
                basis=_basis_for(ca.match_score),
                can_view_profile=_can_view(ca.employee_id),
                comp_match=bd.get("comp_match"),
                comp_qualifies=bd.get("comp_qualifies", False),
                exp_months=bd.get("exp_months"),
                exp_qualifies=bd.get("exp_qualifies", False),
                has_comp_requirement=has_comp,
                has_spec_requirement=has_spec,
                exp_via_current_position=bd.get("exp_via_current_position", False),
                is_me=(
                    viewer_employee_id is not None
                    and ca.employee_id == viewer_employee_id
                ),
                position_title=ca.employee.position_title if ca.employee else None,
                employee_status=ca.employee.status if ca.employee else None,
            )
        )

    # HRP-173 ranking inside the Candidates block: qualifying candidates
    # first, sorted by competence percent desc → name asc; then manual
    # picks / nominees that no longer qualify (still appointed candidates,
    # too) with the same secondary key. We treat anything with the
    # full-qualifies flag (status == matched in pool terms) as "primary"
    # and everything else as "secondary". This keeps appointed candidates
    # who fell below the threshold visible but at the bottom.
    def _fully_qualifies(item: dict) -> bool:
        # Qualifying = competence pass AND (no specs OR spec pass)
        if has_comp and not item.get("comp_qualifies"):
            return False
        if has_spec and not item.get("exp_qualifies"):
            return False
        # If neither axis is set we can't really qualify anyone via auto
        # rules — manual picks land in the secondary bucket.
        return has_comp or has_spec

    def _sort_key(item: dict) -> tuple:
        pct = item.get("comp_match")
        primary = 0 if _fully_qualifies(item) else 1
        # Use comp_match desc; fall back to legacy match_score for
        # specialization-only cards where comp_match is absent.
        score = pct if pct is not None else (item.get("match_score") or 0)
        # HRP-213 Task 2 redo: experience is part of "all else being
        # equal" — a candidate with qualifying/longer experience ranks
        # above a reacted candidate with less, and the reaction only
        # breaks ties between rows equal on both percent and experience.
        exp_rank = 0 if item.get("exp_qualifies") else 1
        exp_months = item.get("exp_months") or 0
        # Reactors break the remaining ties in front of non-reactors;
        # 0 sorts before 1 so the reacted row wins when score +
        # experience + name otherwise collide.
        reacted_first = 0 if item.get("response_at") else 1
        name = (item.get("employee_name") or "").lower()
        return (primary, -score, exp_rank, -exp_months, reacted_first, name)

    candidate_dicts.sort(key=_sort_key)
    data["candidates"] = candidate_dicts
    return data


def _candidate_to_read(
    candidate: TalentCandidate,
    emp_name: str | None,
    *,
    basis: str | None = None,
    can_view_profile: bool = True,
    comp_match: int | None = None,
    comp_qualifies: bool = False,
    exp_months: int | None = None,
    exp_qualifies: bool = False,
    has_comp_requirement: bool = False,
    has_spec_requirement: bool = False,
    exp_via_current_position: bool = False,
    is_me: bool = False,
    position_title: str | None = None,
    employee_status: str | None = None,
) -> dict:
    """Single shape for every endpoint that returns a TalentCandidate row.

    HRP-149: keeps `employee_name` in the response so the UI can render
    "Name Last name" instead of falling back to the uuid; the matching
    `can_view_profile` flag is computed by the caller per viewer role
    (admin → always True; manager → own division subtree; employee →
    self only) and gates the profile link in the UI.
    HRP-129: `basis` describes how the score was derived — `competence`
    when the card carries Required Competences (and the matcher ran on
    them), `specialization` when only Required Specializations gate the
    pool, or `none` when neither is set (manual pick) or no qualifying
    assessment exists.
    HRP-173: `comp_*` and `exp_*` mirror the pool item fields so the
    card-detail Candidates table can apply the same colour rules.
    `has_*_requirement` lets the UI know which axes the card actually
    cares about without re-reading the card payload.
    """
    return {
        "id": candidate.id,
        "employee_id": candidate.employee_id,
        "employee_name": emp_name,
        "can_view_profile": can_view_profile,
        "status": candidate.status,
        "match_score": candidate.match_score,
        "basis": basis,
        "comp_match": comp_match,
        "comp_qualifies": comp_qualifies,
        "exp_months": exp_months,
        "exp_qualifies": exp_qualifies,
        "has_comp_requirement": has_comp_requirement,
        "has_spec_requirement": has_spec_requirement,
        "exp_via_current_position": exp_via_current_position,
        "is_me": is_me,
        "position_title": position_title,
        "employee_status": employee_status,
        "assessment_id": candidate.assessment_id,
        "pdp_id": candidate.pdp_id,
        "response_at": candidate.response_at,
        "appointed_at": candidate.appointed_at,
    }
