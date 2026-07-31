"""Talent card lifecycle: CRUD, search, detail, publish / complete / cancel.

Split from the former talent_market/service.py god-service
(project-review #20). ``service.py`` remains as a PEP 562 delegating
namespace so ``service.<name>`` keeps resolving to the wrapped
canonical functions.
"""

import logging
import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from fastapi import status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.access_scope import get_visible_employee_ids
from app.core.errors import AppError
from app.modules.auth.models import User
from app.modules.position.models import Position
from app.modules.talent_market import common
from app.modules.talent_market.common import _card_to_detail, _card_to_read
from app.modules.talent_market.matching import (
    _auto_populate_candidates,
    _comp_percent_from_map,
    _employee_current_position_matches_any_spec,
    _employee_experience_months,
    _employee_spec_match,
    _fetch_match_inputs,
    _last_passed_percents,
    _load_work_exp_cache,
)
from app.modules.talent_market.models import (
    TalentCandidate,
    TalentCard,
    TalentCardCompetence,
)

logger = logging.getLogger(__name__)


async def create_card(
    db: AsyncSession, tenant_id: uuid.UUID, author_id: uuid.UUID, data
) -> dict:

    # HRP-92: start_date is required by the spec; default to today when the
    # client omits it so existing API callers stay backwards-compatible.
    card = TalentCard(
        tenant_id=tenant_id,
        author_id=author_id,
        title=data.title,
        description=data.description,
        card_type=data.card_type,
        division_id=data.division_id,
        start_date=data.start_date or date.today(),
        end_date=data.end_date,
        match_percent=data.match_percent,
    )
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return _card_to_read(card)


async def search_cards(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data,
    *,
    published_only: bool = False,
    assignee_employee_id: uuid.UUID | None = None,
    candidate_only: bool = False,
    viewer_employee_id: uuid.UUID | None = None,
) -> tuple[list[dict], int]:
    query = select(TalentCard).where(TalentCard.tenant_id == tenant_id)
    count_q = select(func.count(TalentCard.id)).where(TalentCard.tenant_id == tenant_id)

    scope_clause: sa.ColumnElement[bool] | None = None
    if candidate_only and assignee_employee_id is not None:
        # HRP-209: pure-Employee viewers only see cards they're a
        # candidate on. Draft cards stay hidden unless the employee is
        # appointed on them (pre-publish nomination by the recruiter).
        # Everything else is invisible to that role.
        visible_card_ids = (
            select(TalentCandidate.card_id)
            .join(TalentCard, TalentCard.id == TalentCandidate.card_id)
            .where(
                TalentCandidate.employee_id == assignee_employee_id,
                or_(
                    TalentCard.status != "draft",
                    TalentCandidate.status == "appointed",
                ),
            )
            .scalar_subquery()
        )
        scope_clause = TalentCard.id.in_(visible_card_ids)
    elif published_only:
        if assignee_employee_id is not None:
            assigned_subq = (
                select(TalentCandidate.card_id)
                .where(TalentCandidate.employee_id == assignee_employee_id)
                .scalar_subquery()
            )
            scope_clause = or_(
                TalentCard.is_published.is_(True),
                TalentCard.id.in_(assigned_subq),
            )
        else:
            scope_clause = TalentCard.is_published.is_(True)
    if scope_clause is not None:
        query = query.where(scope_clause)
        count_q = count_q.where(scope_clause)

    if data.card_type:
        query = query.where(TalentCard.card_type == data.card_type)
        count_q = count_q.where(TalentCard.card_type == data.card_type)
    if data.status:
        query = query.where(TalentCard.status == data.status)
        count_q = count_q.where(TalentCard.status == data.status)
    if data.division_id:
        query = query.where(TalentCard.division_id == data.division_id)
        count_q = count_q.where(TalentCard.division_id == data.division_id)

    total = (await db.execute(count_q)).scalar() or 0
    # HRP-167: list ordering — active (draft/published) first by created_at
    # desc, then completed by completed_at desc, then cancelled by
    # cancelled_at desc. Each bucket uses its status-specific date so the
    # "most-recently-closed-on-top" rule reads consistently in the UI.
    status_priority = sa.case(
        (TalentCard.status.in_(["draft", "published"]), 0),
        (TalentCard.status.in_(["completed", "closed"]), 1),
        (TalentCard.status == "cancelled", 2),
        else_=3,
    )
    bucket_sort = sa.case(
        (TalentCard.status.in_(["draft", "published"]), TalentCard.created_at),
        (
            TalentCard.status.in_(["completed", "closed"]),
            sa.func.coalesce(TalentCard.completed_at, TalentCard.closed_at),
        ),
        (
            TalentCard.status == "cancelled",
            sa.func.coalesce(TalentCard.cancelled_at, TalentCard.closed_at),
        ),
        else_=TalentCard.created_at,
    )
    result = await db.execute(
        query.order_by(
            status_priority, bucket_sort.desc(), TalentCard.created_at.desc()
        )
        .offset(data.skip)
        .limit(data.limit)
    )
    cards = result.scalars().all()
    # HRP-213: per-viewer "Reacted" chip on each card preview. One small
    # query covers every visible card — the chip is False for every row
    # when the viewer has no Employee profile (admins outside the
    # tenant's employee map, platform admins, etc.).
    reacted_ids: set[uuid.UUID] = set()
    if viewer_employee_id is not None and cards:
        reacted_rows = (
            await db.execute(
                select(TalentCandidate.card_id).where(
                    TalentCandidate.employee_id == viewer_employee_id,
                    TalentCandidate.response_at.isnot(None),
                    TalentCandidate.card_id.in_([c.id for c in cards]),
                )
            )
        ).all()
        reacted_ids = {row[0] for row in reacted_rows}
    return [_card_to_read(c, reacted_by_me=c.id in reacted_ids) for c in cards], total


async def get_card_detail(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    card_id: uuid.UUID,
    *,
    current_user: User | None = None,
) -> dict:
    result = await db.execute(
        select(TalentCard)
        .options(
            selectinload(TalentCard.specializations),
            selectinload(TalentCard.competences),
            selectinload(TalentCard.requirements),
            selectinload(TalentCard.candidates),
        )
        .where(TalentCard.id == card_id, TalentCard.tenant_id == tenant_id)
    )
    card = result.scalar_one_or_none()
    if not card:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    # HRP-209: pure-Employee viewers can only open cards they're
    # attached to (Draft only when appointed). Managers + admins keep
    # full visibility.
    if current_user is not None:
        from app.core.access_scope import (
            get_current_employee,
            get_managed_division_ids,
            is_employee_only,
        )

        if is_employee_only(current_user):
            emp = await get_current_employee(db, current_user)
            managed = (
                await get_managed_division_ids(db, current_user.tenant_id, emp.id)
                if emp
                else []
            )
            if not managed:
                if emp is None:
                    raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
                cand = next(
                    (ca for ca in card.candidates if ca.employee_id == emp.id),
                    None,
                )
                if cand is None:
                    raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
                if card.status == "draft" and cand.status != "appointed":
                    raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    # HRP-149: viewer-scoped profile-link gating. Skip the lookup when no
    # user is in context (background callers) — defaults to "everyone
    # visible" via `_card_to_detail`'s `None` semantics.
    visible: set[uuid.UUID] | None = None
    viewer_employee_id: uuid.UUID | None = None
    reacted_by_me = False
    if current_user is not None:
        visible = await get_visible_employee_ids(db, current_user)
        # HRP-209: the detail response needs to flag the viewer's own
        # candidate row (is_me) so the UI can render "it's me", gate
        # drawer arrows, and hide Appoint for self.
        from app.core.access_scope import get_current_employee as _gce

        viewer_emp = await _gce(db, current_user)
        if viewer_emp is not None:
            viewer_employee_id = viewer_emp.id
            # HRP-213: card-level reacted_by_me — True when the viewer's
            # candidate row has a response_at stamp. The detail page
            # uses this to mirror the list-preview chip and to decide
            # whether to render the React button.
            for ca in card.candidates:
                if ca.employee_id == viewer_emp.id and ca.response_at is not None:
                    reacted_by_me = True
                    break
    # HRP-173: per-candidate breakdown for the Match column. Skipped on
    # cards with empty Candidates so we don't pay the per-employee
    # matcher cost when there's nothing to score.
    breakdown_by_emp: dict[uuid.UUID, dict] = {}
    if card.candidates:
        breakdown_by_emp = await _compute_candidates_breakdown(
            db, card, [ca.employee_id for ca in card.candidates]
        )
    return _card_to_detail(
        card,
        visible_employee_ids=visible,
        breakdown_by_emp=breakdown_by_emp,
        viewer_employee_id=viewer_employee_id,
        reacted_by_me=reacted_by_me,
    )


async def _compute_candidates_breakdown(
    db: AsyncSession,
    card: TalentCard,
    employee_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict]:
    """HRP-173: bulk-compute the per-axis match breakdown for a card's
    candidates. Returns {employee_id: {comp_match, comp_qualifies,
    exp_months, exp_qualifies}}.

    Shares the prefetch helpers `_fetch_match_inputs`, `_load_work_exp_cache`
    and `_last_passed_percents` with the auto-pool builder so the matcher
    fans out across employees with constant SQL, not N+1.
    """
    if not employee_ids:
        return {}
    comp_rows, spec_rows = await _fetch_match_inputs(db, card.id)
    work_exp_cache = await _load_work_exp_cache(db, employee_ids, spec_rows)
    last_map: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    if comp_rows:
        required_pairs = {(r.competence_id, r.skill_level_id) for r in comp_rows}
        last_map = await _last_passed_percents(db, employee_ids, required_pairs)
    threshold = card.match_percent if card.match_percent is not None else 80
    current_pos_cache: dict[uuid.UUID, Position | None] = {}
    out: dict[uuid.UUID, dict] = {}
    for emp_id in employee_ids:
        comp_match: int | None = None
        if comp_rows:
            comp_match = _comp_percent_from_map(comp_rows, last_map.get(emp_id, {}))
        comp_qualifies = comp_match is not None and comp_match >= threshold
        exp_months: int | None = None
        exp_qualifies = False
        exp_via_current_position = False
        if spec_rows:
            exp_months = await _employee_experience_months(
                db, emp_id, spec_rows, work_exp_cache=work_exp_cache
            )
            exp_qualifies = await _employee_spec_match(
                db,
                emp_id,
                spec_rows,
                work_exp_cache=work_exp_cache,
                current_pos_cache=current_pos_cache,
            )
            # HRP-210: surface the current-position fallback for the
            # Candidates table's Match cell (mirrors the picker logic).
            if (
                exp_months is None
                and await _employee_current_position_matches_any_spec(
                    db, emp_id, spec_rows, current_pos_cache=current_pos_cache
                )
            ):
                exp_via_current_position = True
        out[emp_id] = {
            "comp_match": comp_match,
            "comp_qualifies": comp_qualifies,
            "exp_months": exp_months,
            "exp_qualifies": exp_qualifies,
            "exp_via_current_position": exp_via_current_position,
        }
    return out


async def update_card(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID, data
) -> dict:

    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    common.assert_card_not_terminal(card)
    patch = data.model_dump(exclude_unset=True)
    # HRP-128: explicit null on match_percent is a no-op — the column is
    # NOT NULL and we treat "omit" and "null" the same on update. Also
    # locks the field once the card is published (mirrors the requirements
    # blocks publish-lock).
    if patch.get("match_percent") is None and "match_percent" in patch:
        patch.pop("match_percent")
    if "match_percent" in patch and card.is_published:
        raise AppError(
            "tm_match_percent_read_only",
            status.HTTP_409_CONFLICT,
        )
    # HRP-92: cross-field date validation after merging the patch — the
    # schema only sees the partial payload, but end_date can be invalid
    # against the existing start_date (and vice versa).
    if "start_date" in patch or "end_date" in patch:
        new_start = patch.get("start_date", card.start_date)
        new_end = patch.get("end_date", card.end_date)
        if new_start is None:
            raise AppError("tm_start_date_required", status.HTTP_400_BAD_REQUEST)
        if new_end is not None and new_end < new_start:
            raise AppError(
                "tm_end_date_before_start_date",
                status.HTTP_400_BAD_REQUEST,
            )
    match_changed = (
        "match_percent" in patch and patch["match_percent"] != card.match_percent
    )
    for field, value in patch.items():
        setattr(card, field, value)
    await db.commit()
    await db.refresh(card)
    # HRP-129: changing the card-level threshold can promote/demote
    # nominees → recompute the auto-pool so the Candidates block stays
    # consistent with the new bar.
    if match_changed:
        await _auto_populate_candidates(db, tenant_id, card_id)
        card = await db.get(TalentCard, card_id)
        if card is None:
            raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    return _card_to_read(card)


async def delete_card(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID
) -> None:
    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    # HRP-291: terminal cards are frozen history — the list page already
    # hides the action menu on them (HRP-148), the API now agrees.
    common.assert_card_not_terminal(card)
    await db.delete(card)
    await db.commit()


async def publish_card(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID
) -> dict:
    """Move a card to `published`.

    HRP-87 invariant: a card cannot be published until its Required
    Competencies block has at least one row. HRP-150 adds a second
    invariant: at least one Candidate must be attached (auto-pool or
    manual). The Required Specializations block stays optional.
    """
    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    if card.status != "draft":
        raise AppError(
            "tm_card_publish_invalid_status",
            status.HTTP_409_CONFLICT,
            state=card.status,
        )
    # HRP-212: recruiters can't accidentally publish a card whose End date
    # has already slipped — today counts as the future. Forces a date edit
    # before the publish action goes through.
    if card.end_date is not None and card.end_date < date.today():
        raise AppError(
            "tm_end_date_in_past",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    has_competence = (
        await db.execute(
            select(func.count(TalentCardCompetence.id)).where(
                TalentCardCompetence.card_id == card_id
            )
        )
    ).scalar() or 0
    if not has_competence:
        raise AppError(
            "tm_publish_requires_competence",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    has_candidate = (
        await db.execute(
            select(func.count(TalentCandidate.id)).where(
                TalentCandidate.card_id == card_id
            )
        )
    ).scalar() or 0
    if not has_candidate:
        raise AppError(
            "tm_publish_requires_candidate",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    card.is_published = True
    card.status = "published"
    card.published_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(card)
    # HRP-211: fan out the "you're a (matched) candidate" emails to
    # everyone on the candidate list. Email failures are absorbed inside
    # the dispatcher so publish never rolls back on a flaky mailer.
    await common._dispatch_lifecycle_emails(db, card, "published")
    return _card_to_read(card)


async def complete_card(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID
) -> dict:
    """HRP-150: terminal transition Published → Completed.

    Requires at least one candidate already marked `appointed` — the
    product flow is "the role is filled, close the card." HRP-92 REDO
    stamps `completed_at` (alongside the legacy `closed_at`) so the
    list/detail pages surface "Completed: yyyy-mm-dd".
    """
    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    if card.status != "published":
        raise AppError(
            "tm_card_complete_invalid_status",
            status.HTTP_409_CONFLICT,
            state=card.status,
        )
    appointed = (
        await db.execute(
            select(func.count(TalentCandidate.id)).where(
                TalentCandidate.card_id == card_id,
                TalentCandidate.status == "appointed",
            )
        )
    ).scalar() or 0
    if not appointed:
        raise AppError(
            "tm_complete_requires_appointed",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    now = datetime.now(timezone.utc)
    card.status = "completed"
    card.completed_at = now
    card.closed_at = now
    await db.commit()
    await db.refresh(card)
    # HRP-211: announce the closure to every matched / not_matched
    # candidate (appointed candidates already know — they're the ones
    # filling the role).
    await common._dispatch_lifecycle_emails(db, card, "completed")
    return _card_to_read(card)


async def cancel_card(
    db: AsyncSession, tenant_id: uuid.UUID, card_id: uuid.UUID
) -> dict:
    """HRP-150: terminal transition Draft|Published → Cancelled.

    No additional invariants — cancelling a card is the recruiter's call
    when the role is dropped or paused indefinitely. HRP-92 REDO stamps
    `cancelled_at` (alongside the legacy `closed_at`) so the UI can
    surface "Cancelled: yyyy-mm-dd".
    """
    card = await db.get(TalentCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise AppError("tm_card_not_found", status.HTTP_404_NOT_FOUND)
    if card.status not in {"draft", "published"}:
        raise AppError(
            "tm_card_cancel_invalid_status",
            status.HTTP_409_CONFLICT,
            state=card.status,
        )
    prev_status = card.status
    # HRP-211: snapshot the appointed candidates BEFORE the cancel
    # transition, so the dispatcher can tell who deserves the "your
    # appointment cancelled" mail even though their candidate row keeps
    # the appointed status (we don't roll appointments back here).
    appointed_emp_ids: list[uuid.UUID] = [
        r[0]
        for r in (
            await db.execute(
                select(TalentCandidate.employee_id).where(
                    TalentCandidate.card_id == card_id,
                    TalentCandidate.status == "appointed",
                )
            )
        ).all()
    ]
    now = datetime.now(timezone.utc)
    card.status = "cancelled"
    card.cancelled_at = now
    card.closed_at = now
    await db.commit()
    await db.refresh(card)
    event = (
        "cancelled_from_draft" if prev_status == "draft" else "cancelled_from_published"
    )
    await common._dispatch_lifecycle_emails(
        db, card, event, appointed_before_cancel=appointed_emp_ids
    )
    return _card_to_read(card)
