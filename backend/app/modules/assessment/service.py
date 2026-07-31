import logging
import math
import secrets
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import status
from sqlalchemy import ColumnElement, and_, case, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.core import billing_hooks
from app.core.errors import AppError

# Answer-scale utilities + CRUD and per-level breakdown math live in dedicated
# leaf modules (split out of this god-service). Re-exported here so router and
# existing ``assessment.service.<name>`` call sites keep their import path.
from app.modules.assessment.answer_scale_service import (  # noqa: F401
    _build_levels,
    _build_scoring_options,
    _load_scale_full,
    _scale_detail_dict,
    _validate_levels_payload,
    _validate_options_payload,
    create_answer_scale,
    delete_answer_scale,
    get_answer_scale,
    list_scales,
    snapshot_scale_for_assessment,
    update_answer_scale,
)
from app.modules.assessment.breakdown_service import (  # noqa: F401
    _compute_breakdown_for_assessment,
    _compute_per_level_breakdown,
    compute_per_level_breakdowns_batch,
)
from app.modules.assessment.models import (
    CPA,
    AnswerOption,
    AnswerScale,
    AnswerScaleLevel,
    Assessment,
    AssessmentAnswer,
    AssessmentCalibratedTotal,
    AssessmentCompetence,
    AssessmentGroup,
    AssessmentParticipant,
    AssessmentResult,
    AssessmentStatus,
    AssessmentType,
    CPACriteria,
    CPAParticipant,
    ExternalReviewer,
)

logger = logging.getLogger(__name__)

# --- Helpers ---


async def _get_status_by_code(db: AsyncSession, code: str) -> AssessmentStatus:
    result = await db.execute(
        select(AssessmentStatus).where(AssessmentStatus.code == code)
    )
    s = result.scalar_one_or_none()
    if not s:
        raise AppError(
            "assessment_invalid_status_code",
            status.HTTP_400_BAD_REQUEST,
            value=code,
        )
    return s


async def _get_type_by_code(db: AsyncSession, code: str) -> AssessmentType:
    result = await db.execute(select(AssessmentType).where(AssessmentType.code == code))
    t = result.scalar_one_or_none()
    if not t:
        raise AppError(
            "assessment_invalid_type_code",
            status.HTTP_400_BAD_REQUEST,
            value=code,
        )
    return t


TERMINAL_STATUSES = ("done", "cancelled")


def _deadline_in_past(deadline: datetime | None) -> bool:
    """HRP-83: refuse to launch an assessment whose deadline already elapsed.

    HRP-164: compare on calendar dates (UTC). Deadlines are picked as a day,
    not a wall-clock instant, so "today" must stay valid until midnight UTC
    rolls the date forward — earlier the same-day check tripped because
    storing the deadline at 00:00 UTC made `deadline < now()` true after a
    few hours.
    """
    if deadline is None:
        return False
    aware = (
        deadline
        if deadline.tzinfo is not None
        else deadline.replace(tzinfo=timezone.utc)
    )
    return aware.date() < datetime.now(timezone.utc).date()


def compute_overall_percent(percents: Iterable[int | None]) -> int | None:
    """Mean of per-competence percents, math-rounded (half-up) to int.

    Returns None when no competence has a percent yet (assessment not finished
    or scale missing). Half-up rounding matches the "school rules" the QA
    spec calls out — distinct from Python's banker's round() on .5.
    """
    values = [p for p in percents if p is not None]
    if not values:
        return None
    avg = sum(values) / len(values)
    return math.floor(avg + 0.5)


# HRP-37: hard cap on concurrent active assessments per employee. QA REDO
# tightened the threshold from 5 to 3 — past three concurrent reviews the
# assessee's queue starts hiding work behind scrolling and role averages
# go noisy on a small respondent pool.
MAX_ACTIVE_ASSESSMENTS_PER_EMPLOYEE = 3


async def _assert_not_terminal(db: AsyncSession, assessment: Assessment) -> None:
    if assessment.status is None:
        s = await db.get(AssessmentStatus, assessment.status_id)
        code = s.code if s else None
    else:
        code = assessment.status.code
    if code in TERMINAL_STATUSES:
        raise AppError(
            "assessment_terminal_status",
            status.HTTP_400_BAD_REQUEST,
            state=code,
        )


async def _assert_criteria_editable(db: AsyncSession, assessment: Assessment) -> None:
    """Criteria (incl. passing_score) may only change while the assessment
    is still in draft. Once it is sent the threshold and competence set are
    frozen for participants (per the passing-score spec)."""
    if assessment.status is None:
        s = await db.get(AssessmentStatus, assessment.status_id)
        code = s.code if s else None
    else:
        code = assessment.status.code
    if code != "draft":
        raise AppError(
            "assessment_criteria_locked",
            status.HTTP_400_BAD_REQUEST,
            state=code,
        )


def _user_full_name(user) -> str | None:
    if user:
        return f"{user.first_name} {user.last_name}"
    return None


def _employee_name(employee) -> str | None:
    if employee and employee.user:
        return f"{employee.user.first_name} {employee.user.last_name}"
    return None


async def _resolve_dict_titles(
    db: AsyncSession,
    specialization_id: uuid.UUID | None,
    grade_id: uuid.UUID | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Look up dictionary titles for a specialization/grade pair.

    Returns (specialization_title, grade_title, specialization_i18n_key,
    grade_i18n_key). Each is None if the input id is None or the row
    doesn't exist. The keys (HRP-479) let the frontend localize origin
    rows next to the denormalized titles.
    """
    from app.modules.dictionary.models import DictionaryItem

    spec_title: str | None = None
    grade_title: str | None = None
    spec_key: str | None = None
    grade_key: str | None = None
    if specialization_id is not None:
        item = await db.get(DictionaryItem, specialization_id)
        spec_title = item.title if item else None
        spec_key = item.i18n_key if item else None
    if grade_id is not None:
        item = await db.get(DictionaryItem, grade_id)
        grade_title = item.title if item else None
        grade_key = item.i18n_key if item else None
    return spec_title, grade_title, spec_key, grade_key


# HRP-84: lifecycle email dispatch ------------------------------------------
#
# Emit `Evaluate ...` invitations on Sent (and on late-add), and report the
# final state (`completed` / `cancelled`) per role. Email side-effects are
# swallowed at the edge — the Resend/SMTP adapter already retries, and the
# notification must never block a status transition.


async def _participant_email_payloads(
    db: AsyncSession,
    assessment_id: uuid.UUID,
) -> list[tuple["AssessmentParticipant", str | None, str | None, str | None]]:
    """Return ``(participant, email, full_name, user_language)`` rows for
    every participant in ``assessment_id`` who has a deliverable email
    address.

    External reviewers carry the email on their own row; logged-in users
    pull it from ``users``. Participants with no email are dropped so
    downstream code can iterate without re-checking.

    ``user_language`` is the recipient's own preference (i18n F4) and is
    None for external reviewers, who have no account — they fall back to
    the tenant default one level down the chain.
    """
    from app.modules.auth.models import User as AuthUser

    rows = await db.execute(
        select(AssessmentParticipant).where(
            AssessmentParticipant.assessment_id == assessment_id
        )
    )
    participants = list(rows.scalars().all())
    user_ids = {p.user_id for p in participants if p.user_id}
    user_by_id: dict[uuid.UUID, AuthUser] = {}
    if user_ids:
        u_rows = await db.execute(select(AuthUser).where(AuthUser.id.in_(user_ids)))
        user_by_id = {u.id: u for u in u_rows.scalars().all()}

    ext_ids = {p.external_reviewer_id for p in participants if p.external_reviewer_id}
    ext_by_id: dict[uuid.UUID, ExternalReviewer] = {}
    if ext_ids:
        e_rows = await db.execute(
            select(ExternalReviewer).where(ExternalReviewer.id.in_(ext_ids))
        )
        ext_by_id = {e.id: e for e in e_rows.scalars().all()}

    out: list[tuple[AssessmentParticipant, str | None, str | None, str | None]] = []
    for p in participants:
        email: str | None = None
        name: str | None = None
        language: str | None = None
        if p.user_id and p.user_id in user_by_id:
            u = user_by_id[p.user_id]
            email = u.email
            name = _user_full_name(u)
            language = u.language
        elif p.external_reviewer_id and p.external_reviewer_id in ext_by_id:
            er = ext_by_id[p.external_reviewer_id]
            email = er.email
            name = er.name
        if email:
            out.append((p, email, name, language))
    return out


async def _send_role_email(
    *,
    role: str,
    email: str,
    title: str,
    employee_name: str | None,
    event: str,
    deadline: str | None,
    tenant_id: uuid.UUID | None,
    db: AsyncSession | None = None,
    recipient_user_id: uuid.UUID | None = None,
    assessment_id: uuid.UUID | None = None,
    locale: str | None = None,
) -> None:
    """Render and enqueue the email matching ``(role, event)``.

    Unknown role/event combinations are silently ignored — the only call
    sites pass values from a closed set, so a miss means the helper is
    being asked for something we don't notify on (e.g. observer roles).

    HRP-84 REDO: when ``db`` and ``recipient_user_id`` are supplied, also
    persists an in-app Notification row so the bell in the header reflects
    the same event. Missing template or DB write failures are swallowed —
    in-app delivery never blocks the email path.

    i18n F4: ``locale`` is the *recipient's* resolved locale, computed by
    the dispatcher (one tenant lookup per batch). Callers that have no
    recipient context — and therefore no ``db`` to read the tenant from —
    leave it unset and get the deployment default.
    """
    from app.core.email import enqueue_email
    from app.core.email_templates import (
        render_assessment_assigned_email,
        render_assessment_completed_email,
        render_assessment_manager_cancelled_email,
        render_assessment_manager_completed_email,
        render_assessment_manager_evaluate_email,
        render_assessment_peer_cancelled_email,
        render_assessment_self_cancelled_email,
        render_assessment_self_evaluate_email,
    )
    from app.core.i18n import resolve_locale

    subject: str | None = None
    body: str | None = None
    template_code: str | None = None
    recipient_locale = locale or resolve_locale()

    asmt_id_str = str(assessment_id) if assessment_id else None
    if event == "evaluate":
        if role == "self":
            subject, body = render_assessment_self_evaluate_email(
                title, deadline, assessment_id=asmt_id_str, locale=recipient_locale
            )
            template_code = "assessment.self_evaluate"
        elif role == "manager":
            subject, body = render_assessment_manager_evaluate_email(
                title,
                employee_name,
                deadline,
                assessment_id=asmt_id_str,
                locale=recipient_locale,
            )
            template_code = "assessment.manager_evaluate"
        elif role in ("peer", "subordinate", "external"):
            subject, body = render_assessment_assigned_email(
                title, deadline, assessment_id=asmt_id_str, locale=recipient_locale
            )
            template_code = "assessment.evaluate_employee"
    elif event == "completed":
        if role == "self":
            subject, body = render_assessment_completed_email(
                title, assessment_id=asmt_id_str, locale=recipient_locale
            )
            template_code = "assessment.self_completed"
        elif role == "manager":
            subject, body = render_assessment_manager_completed_email(
                title,
                employee_name,
                assessment_id=asmt_id_str,
                locale=recipient_locale,
            )
            template_code = "assessment.manager_completed"
    elif event == "cancelled":
        # HRP-84 REDO: cancellation emails also go to peer / subordinate /
        # external participants who haven't completed the survey — they're
        # mid-flight reviewers whose pending work just got pulled, so
        # silently leaving them out (the previous behaviour) hid the
        # change from the inbox they're actively using. Self and manager
        # keep their bespoke copy.
        if role == "self":
            subject, body = render_assessment_self_cancelled_email(
                title, assessment_id=asmt_id_str, locale=recipient_locale
            )
            template_code = "assessment.self_cancelled"
        elif role == "manager":
            subject, body = render_assessment_manager_cancelled_email(
                title,
                employee_name,
                assessment_id=asmt_id_str,
                locale=recipient_locale,
            )
            template_code = "assessment.manager_cancelled"
        elif role in ("peer", "subordinate", "external"):
            subject, body = render_assessment_peer_cancelled_email(
                title,
                employee_name,
                assessment_id=asmt_id_str,
                locale=recipient_locale,
            )
            template_code = "assessment.peer_cancelled"

    if subject is None or body is None:
        return
    import contextlib

    with contextlib.suppress(Exception):
        # never block a transition on email failures
        enqueue_email(
            email,
            subject,
            body,
            tenant_id=str(tenant_id) if tenant_id else None,
            template_code=template_code,
        )

    # HRP-84 REDO: also drop an in-app Notification row so the bell sees
    # the event. The mailer above already covered email channel; this
    # path is purely DB-backed (no second send). Skipped when the caller
    # didn't pass db/user_id — keeps the helper usable from places that
    # only care about email (eg. external reviewers without a User row).
    if db is None or recipient_user_id is None or template_code is None:
        return
    try:
        from app.modules.notification.models import Notification
        from app.modules.notification.service import get_template_for_locale

        # i18n F4: the bell text follows the recipient's locale too, with
        # the en row as fallback when the locale has no translation yet.
        tmpl = await get_template_for_locale(db, template_code, recipient_locale)
        if tmpl is None:
            return
        notif = Notification(
            tenant_id=tenant_id,
            template_id=tmpl.id,
            recipient_id=recipient_user_id,
            status="sent",
            context={
                "title": title,
                "employee_name": employee_name,
                "deadline": deadline,
                "event": event,
                "role": role,
            },
            sent_at=datetime.now(timezone.utc),
        )
        db.add(notif)
        await db.flush()
    except Exception:  # noqa: BLE001 — in-app delivery never blocks the flow
        return


async def _dispatch_lifecycle_emails(
    db: AsyncSession,
    assessment: Assessment,
    event: str,
    *,
    only_participant_id: uuid.UUID | None = None,
) -> None:
    """Send the lifecycle email batch for ``assessment``.

    ``event`` ∈ {"evaluate", "completed", "cancelled"}. When
    ``only_participant_id`` is set, restrict delivery to that single
    participant (used by the late-add HRP-84 case). Other events fan out
    across every participant whose role gets a notification.
    """
    title = assessment.title or "Assessment"
    employee_name = _employee_name(getattr(assessment, "employee", None))
    if employee_name is None and assessment.employee_id is not None:
        from app.modules.employee.models import Employee

        emp = await db.get(Employee, assessment.employee_id)
        employee_name = _employee_name(emp) if emp else None

    # i18n F4: one tenant lookup per batch — every recipient resolves its
    # own locale on top of this default (User.language wins when set).
    # i18n F7: the deadline is formatted per recipient inside the loop —
    # month names follow each recipient's locale.
    from app.core.i18n import format_date, resolve_locale
    from app.modules.company.models import Tenant

    tenant_default: str | None = None
    if assessment.tenant_id is not None:
        tenant = await db.get(Tenant, assessment.tenant_id)
        tenant_default = tenant.default_locale if tenant else None

    rows = await _participant_email_payloads(db, assessment.id)
    for participant, email, _, user_language in rows:
        if only_participant_id is not None and participant.id != only_participant_id:
            continue
        # HRP-84 REDO: cancellation now includes peer / subordinate / external
        # participants who haven't completed the survey. Already-completed
        # reviewers are silent — their work is done and the cancellation
        # doesn't change anything actionable for them.
        if (
            event == "cancelled"
            and participant.role in ("peer", "subordinate", "external")
            and participant.is_completed
        ):
            continue
        locale = resolve_locale(
            user_language=user_language, tenant_default=tenant_default
        )
        await _send_role_email(
            role=participant.role,
            email=email,  # type: ignore[arg-type]
            title=title,
            employee_name=employee_name,
            event=event,
            deadline=(
                format_date(assessment.ended_at, locale)
                if assessment.ended_at
                else None
            ),
            tenant_id=assessment.tenant_id,
            db=db,
            recipient_user_id=participant.user_id,
            assessment_id=assessment.id,
            locale=locale,
        )


def _assessment_to_read(a: Assessment) -> dict:
    employee = getattr(a, "employee", None)
    return {
        "id": a.id,
        "title": a.title,
        "employee_id": a.employee_id,
        "employee_name": _employee_name(employee),
        # HRP-333: feed EmployeeSummaryLine — current position + status
        # chip next to the assessee wherever the assessment is listed.
        "employee_position_title": employee.position_title if employee else None,
        "employee_status": employee.status if employee else None,
        "type_code": a.assessment_type.code if a.assessment_type else None,
        "type_title": a.assessment_type.title if a.assessment_type else None,
        "status_code": a.status.code if a.status else None,
        "status_title": a.status.title if a.status else None,
        "specialization_id": a.specialization_id,
        "grade_id": a.grade_id,
        "scale_id": a.scale_id,
        "initiator_id": a.initiator_id,
        "approver_id": a.approver_id,
        "cpa_id": a.cpa_id,
        "group_id": a.group_id,
        "tenant_id": a.tenant_id,
        "started_at": a.started_at,
        "ended_at": a.ended_at,
        "finished_at": a.finished_at,
        "criteria_type": a.criteria_type,
        "passing_score": a.passing_score,
        "created_at": a.created_at,
        # HRP-185: surface the calibration flag so the UI can lock the
        # Take this assessment / Evaluate buttons while a reviewer is
        # editing Totals.
        "calibration_in_progress": getattr(a, "calibration_in_progress", False),
    }


# --- Assessment CRUD ---


async def _auto_assign_self(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> None:
    """Always add the assessed employee as a self-participant."""
    from app.modules.employee.models import Employee

    emp = await db.get(Employee, employee_id)
    if not emp or not emp.user_id:
        return
    db.add(
        AssessmentParticipant(
            assessment_id=assessment_id,
            user_id=emp.user_id,
            role="self",
        )
    )


async def _auto_assign_manager(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> None:
    """GF6: If the employee belongs to a division with a manager, auto-add as reviewer."""
    from app.modules.company.models import Division
    from app.modules.employee.models import Employee

    emp = await db.get(Employee, employee_id)
    if not emp or not emp.division_id:
        return
    div = await db.get(Division, emp.division_id)
    if not div or not div.manager_id or div.manager_id == emp.id:
        return
    # Get manager's user_id
    manager = await db.get(Employee, div.manager_id)
    if not manager:
        return
    # Check not already a participant
    existing = await db.execute(
        select(AssessmentParticipant).where(
            AssessmentParticipant.assessment_id == assessment_id,
            AssessmentParticipant.user_id == manager.user_id,
        )
    )
    if existing.scalar_one_or_none():
        return
    db.add(
        AssessmentParticipant(
            assessment_id=assessment_id,
            user_id=manager.user_id,
            role="manager",
        )
    )


async def create_assessment(
    db: AsyncSession, tenant_id: uuid.UUID, initiator_id: uuid.UUID, data
) -> dict:
    atype = await _get_type_by_code(db, data.type_code)
    draft = await _get_status_by_code(db, "draft")

    # HRP-37: cap concurrent active assessments per employee.
    active_count_q = (
        select(func.count(Assessment.id))
        .join(AssessmentStatus, Assessment.status_id == AssessmentStatus.id)
        .where(
            Assessment.tenant_id == tenant_id,
            Assessment.employee_id == data.employee_id,
            AssessmentStatus.code.notin_(TERMINAL_STATUSES),
        )
    )
    active_count = (await db.execute(active_count_q)).scalar() or 0
    if active_count >= MAX_ACTIVE_ASSESSMENTS_PER_EMPLOYEE:
        raise AppError(
            "assessment_active_limit_reached",
            status.HTTP_409_CONFLICT,
            active_count=active_count,
            limit=MAX_ACTIVE_ASSESSMENTS_PER_EMPLOYEE,
        )

    a = Assessment(
        tenant_id=tenant_id,
        title=data.title,
        employee_id=data.employee_id,
        type_id=atype.id,
        status_id=draft.id,
        specialization_id=data.specialization_id,
        grade_id=data.grade_id,
        scale_id=data.scale_id,
        initiator_id=initiator_id,
        approver_id=data.approver_id,
        ended_at=data.ended_at,
    )
    db.add(a)
    await db.flush()

    # Always add the assessed employee as a self-participant
    await _auto_assign_self(db, a.id, data.employee_id)

    # GF6: For 180/360, auto-assign division manager as reviewer
    if atype.code in ("180", "360"):
        await _auto_assign_manager(db, tenant_id, a.id, data.employee_id)

    await db.commit()

    result = await db.execute(
        select(Assessment)
        .options(
            selectinload(Assessment.assessment_type),
            selectinload(Assessment.status),
            selectinload(Assessment.employee),
        )
        .where(Assessment.id == a.id)
    )
    return _assessment_to_read(result.scalar_one())


def apply_assessment_scope(
    query,
    *,
    visible_employee_ids: set[uuid.UUID] | None,
    participant_user_id: uuid.UUID | None,
    restrict_to_active: bool,
):
    """HRP-113: single source of truth for the HRP-40 access-control predicate
    on ``Assessment`` queries.

    Adds two filters to ``query``:

    * ``visible_employee_ids`` (admin = ``None`` → no scope filter; restricted
      caller = a set): keep rows where the assessee is in the caller's subtree
      OR the caller participates in the assessment. ``participant_user_id``
      may be ``None`` for non-human service tokens — the participant arm then
      matches nothing and only the subtree clause contributes.
    * ``restrict_to_active``: drop Draft assessments — regular employees must
      not see in-flight criteria/scale changes even if they are a participant.

    Centralising this avoids the class of bug HRP-40 follow-ups had to chase:
    ``list_assessments`` / ``get_assessment_detail`` /
    ``list_assessments_grouped`` / ``get_assessment_group`` each owned a copy
    and any divergence was a quiet access-control leak.
    """
    from sqlalchemy import or_

    if visible_employee_ids is not None:
        participant_subq = select(AssessmentParticipant.assessment_id).where(
            AssessmentParticipant.user_id == participant_user_id
        )
        query = query.where(
            or_(
                Assessment.employee_id.in_(visible_employee_ids),
                Assessment.id.in_(participant_subq),
            )
        )
    if restrict_to_active:
        active_status_subq = select(AssessmentStatus.id).where(
            AssessmentStatus.code != "draft"
        )
        query = query.where(Assessment.status_id.in_(active_status_subq))
    return query


async def list_assessments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 50,
    visible_employee_ids: set[uuid.UUID] | None = None,
    participant_user_id: uuid.UUID | None = None,
    restrict_to_active: bool = False,
) -> tuple[list[dict], int]:
    base = select(Assessment).where(Assessment.tenant_id == tenant_id)
    count_q = select(func.count(Assessment.id)).where(Assessment.tenant_id == tenant_id)

    base = apply_assessment_scope(
        base,
        visible_employee_ids=visible_employee_ids,
        participant_user_id=participant_user_id,
        restrict_to_active=restrict_to_active,
    )
    count_q = apply_assessment_scope(
        count_q,
        visible_employee_ids=visible_employee_ids,
        participant_user_id=participant_user_id,
        restrict_to_active=restrict_to_active,
    )

    if employee_id:
        # HRP-40: a restricted caller cannot escape their scope by passing
        # `?employee_id=<other-employee>` — the AND with scope_clause already
        # filters by both, so cross-employee fetch returns the participant
        # subset only (assessments the caller actually rates).
        base = base.where(Assessment.employee_id == employee_id)
        count_q = count_q.where(Assessment.employee_id == employee_id)

    total = (await db.execute(count_q)).scalar() or 0

    # HRP-166: group rows by status (active → done → cancelled), then order
    # within each group by the date the UI surfaces — created_at for active,
    # finished_at for terminal rows (it's stamped on both done/cancelled
    # transitions).
    status_priority = case(
        (AssessmentStatus.code == "done", 1),
        (AssessmentStatus.code == "cancelled", 2),
        else_=0,
    )
    group_date = case(
        (
            AssessmentStatus.code.in_(("done", "cancelled")),
            Assessment.finished_at,
        ),
        else_=Assessment.created_at,
    )
    query = (
        base.join(AssessmentStatus, Assessment.status_id == AssessmentStatus.id)
        .options(
            selectinload(Assessment.assessment_type),
            selectinload(Assessment.status),
            selectinload(Assessment.employee),
        )
        .order_by(status_priority, group_date.desc(), Assessment.id.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return [_assessment_to_read(a) for a in result.scalars().all()], total


async def get_assessment_detail(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment_id: uuid.UUID,
    *,
    visible_employee_ids: set[uuid.UUID] | None = None,
    participant_user_id: uuid.UUID | None = None,
    restrict_to_active: bool = False,
    hide_results_for_employee: bool = False,
) -> dict:
    # HRP-113: route the same scope/Draft predicate as list/grouped/group
    # endpoints through the shared helper so a restricted caller cannot
    # observe another tenant's assessment (or a Draft they only participate
    # in) by hitting the detail URL directly.
    detail_q = (
        select(Assessment)
        .options(
            selectinload(Assessment.assessment_type),
            selectinload(Assessment.status),
            selectinload(Assessment.employee),
            selectinload(Assessment.participants),
            selectinload(Assessment.competences),
            selectinload(Assessment.results).selectinload(AssessmentResult.level),
        )
        .where(Assessment.id == assessment_id, Assessment.tenant_id == tenant_id)
    )
    detail_q = apply_assessment_scope(
        detail_q,
        visible_employee_ids=visible_employee_ids,
        participant_user_id=participant_user_id,
        restrict_to_active=restrict_to_active,
    )
    result = await db.execute(detail_q)
    a = result.scalar_one_or_none()
    if not a:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)

    data = _assessment_to_read(a)
    # HRP-329: saved calibration closes the questionnaire for good — the
    # UI renders Take/Evaluate disabled off this flag, with a tooltip
    # naming the reason, mirroring the server gate.
    data["has_calibrated_totals"] = await _has_calibrated_totals(db, a.id)
    # HRP-85: map each participant to their employee row so the UI can
    # render them as a link to /employees/{id} when the viewer is allowed
    # to open that profile. External reviewers and orphaned users (no
    # Employee row) stay plain text.
    from app.modules.employee.models import Employee

    participant_user_ids = [p.user_id for p in a.participants if p.user_id]
    user_to_employee: dict[uuid.UUID, uuid.UUID] = {}
    # HRP-333: position + status ride along so the Participants table can
    # render the shared EmployeeSummaryLine (externals stay None).
    employee_summary_by_user: dict[uuid.UUID, tuple[str | None, str | None]] = {}
    if participant_user_ids:
        rows = await db.execute(
            select(
                Employee.user_id,
                Employee.id,
                Employee.position_title,
                Employee.status,
            ).where(
                Employee.tenant_id == tenant_id,
                Employee.user_id.in_(participant_user_ids),
            )
        )
        for row in rows.all():
            user_to_employee[row[0]] = row[1]
            employee_summary_by_user[row[0]] = (row[2], row[3])

    def _can_view_profile(emp_id: uuid.UUID | None) -> bool:
        if emp_id is None:
            return False
        if visible_employee_ids is None:
            return True
        return emp_id in visible_employee_ids

    participants_payload: list[dict] = []
    for p in a.participants:
        emp_id = user_to_employee.get(p.user_id) if p.user_id else None
        emp_position, emp_status = (
            employee_summary_by_user.get(p.user_id, (None, None))
            if p.user_id
            else (None, None)
        )
        participants_payload.append(
            {
                "id": p.id,
                "user_id": p.user_id,
                "user_name": (
                    _user_full_name(p.user)
                    if p.user_id
                    else (p.external_reviewer.name if p.external_reviewer else None)
                ),
                "employee_id": emp_id,
                "position_title": emp_position,
                "employee_status": emp_status,
                "can_view_profile": _can_view_profile(emp_id),
                "external_reviewer_id": p.external_reviewer_id,
                "role": p.role,
                "is_completed": p.is_completed,
                "external_name": (
                    p.external_reviewer.name if p.external_reviewer else None
                ),
                "external_email": (
                    p.external_reviewer.email if p.external_reviewer else None
                ),
            }
        )
    data["participants"] = participants_payload
    data["competence_ids"] = [c.competence_id for c in a.competences]
    data["competences"] = [
        {
            "competence_id": c.competence_id,
            "competence_title": c.competence.title if c.competence else "",
            "skill_level_id": c.skill_level_id,
            "skill_level_title": c.skill_level.title if c.skill_level else None,
            "skill_level_i18n_key": (c.skill_level.i18n_key if c.skill_level else None),
        }
        for c in a.competences
    ]
    (
        data["specialization_title"],
        data["grade_title"],
        data["specialization_i18n_key"],
        data["grade_i18n_key"],
    ) = await _resolve_dict_titles(db, a.specialization_id, a.grade_id)
    if a.scale_id is not None:
        scale = await _load_scale_full(db, a.scale_id)
        data["scale"] = await _scale_detail_dict(db, scale) if scale else None
    else:
        data["scale"] = None
    data["recommendation"] = a.recommendation_payload
    per_level_map = await _compute_per_level_breakdown(db, a)
    # HRP-243: Employee-only callers (no admin/manager) see the Results
    # block only when they are the assessee (the ``self`` participant) AND
    # the assessment has reached Done. Peers / subordinates never see
    # results for an assessment they merely participated in, and the
    # assessee themselves doesn't see them until the workflow is closed.
    suppress_results = False
    if hide_results_for_employee and participant_user_id is not None:
        is_self_participant = any(
            p.role == "self" and p.user_id == participant_user_id
            for p in a.participants
        )
        status_code = a.status.code if a.status is not None else None
        if not is_self_participant or status_code != "done":
            suppress_results = True
    if suppress_results:
        data["results"] = []
        data["overall_percent"] = None
        data["recommendation"] = None
    else:
        data["results"] = [
            {
                "id": r.id,
                "competence_id": r.competence_id,
                "avg_score": r.avg_score,
                "calibrated_score": r.calibrated_score,
                "percent": r.percent,
                "level": (
                    {
                        "id": r.level.id,
                        "percent_from": r.level.percent_from,
                        "percent_to": r.level.percent_to,
                        "system_code": r.level.system_code,
                        "system_title": r.level.system_title,
                        "description": r.level.description,
                        "sort_index": r.level.sort_index,
                    }
                    if r.level
                    else None
                ),
                "per_level_results": per_level_map.get(r.competence_id, []),
            }
            for r in a.results
        ]
        data["overall_percent"] = compute_overall_percent(r.percent for r in a.results)
    return data


async def change_status(
    db: AsyncSession, tenant_id: uuid.UUID, assessment_id: uuid.UUID, new_code: str
) -> dict:
    result = await db.execute(
        select(Assessment)
        .options(
            selectinload(Assessment.status), selectinload(Assessment.assessment_type)
        )
        .where(Assessment.id == assessment_id, Assessment.tenant_id == tenant_id)
    )
    a = result.scalar_one_or_none()
    if not a:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)

    new_status = await _get_status_by_code(db, new_code)

    # Terminal statuses cannot be modified
    if a.status.code in TERMINAL_STATUSES:
        raise AppError(
            "assessment_terminal_status",
            status.HTTP_400_BAD_REQUEST,
            state=a.status.code,
        )

    # Validate sequence progression (must increment)
    if new_status.sequence <= a.status.sequence and new_code != "cancelled":
        raise AppError(
            "assessment_invalid_transition",
            status.HTTP_400_BAD_REQUEST,
            from_status=a.status.code,
            to_status=new_code,
        )

    # Draft → Sent requires both evaluation criteria and a rating scale.
    # Criteria takes priority in the message so the user fixes the harder
    # gap first.
    if a.status.code == "draft" and new_code == "sent":
        if not a.criteria_type:
            raise AppError(
                "assessment_criteria_not_selected",
                status.HTTP_400_BAD_REQUEST,
            )
        if a.scale_id is None:
            raise AppError(
                "assessment_scale_not_selected",
                status.HTTP_400_BAD_REQUEST,
            )
        # HRP-83: refuse to launch with an expired deadline so the assignee
        # never lands on an assessment that's already overdue. Returns
        # 409 because the request is well-formed — the conflict is with
        # the stored deadline state, not the payload.
        if _deadline_in_past(a.ended_at):
            raise AppError(
                "assessment_deadline_in_past",
                status.HTTP_409_CONFLICT,
            )

    # Manual on_review requires at least one completed participant. The
    # auto-flow (all participants done) takes its own path through
    # _maybe_mark_participant_completed and bypasses change_status.
    if new_code == "on_review":
        completed_q = await db.execute(
            select(func.count())
            .select_from(AssessmentParticipant)
            .where(
                AssessmentParticipant.assessment_id == a.id,
                AssessmentParticipant.is_completed.is_(True),
            )
        )
        if (completed_q.scalar() or 0) == 0:
            raise AppError(
                "assessment_on_review_requires_completed_participant",
                status.HTTP_400_BAD_REQUEST,
            )

    # Done is reachable only via on_review. Sequence numbers allow the
    # forward hop (in_progress=2 → done=6) but the product flow demands
    # the calibration checkpoint — auto-completion routes through
    # on_review already, so legitimate flows are unaffected.
    if new_code == "done" and a.status.code != "on_review":
        raise AppError(
            "assessment_done_requires_on_review",
            status.HTTP_400_BAD_REQUEST,
        )

    # HRP-192: Sent → In progress is auto-driven by the first submitted
    # answer (see _maybe_mark_participant_completed); operators cannot
    # nudge an assessment forward without participants because they would
    # bypass the lifecycle invariant the auto-flow relies on. The
    # constraint is global — `in_progress` is never a valid manual target
    # — so the UI also greys the option out in Change status / Change
    # status (all) and removes the "in progress" button from Details.
    if new_code == "in_progress":
        raise AppError(
            "assessment_manual_transition_not_allowed",
            status.HTTP_400_BAD_REQUEST,
        )

    prev_code = a.status.code
    a.status_id = new_status.id
    # Refresh the relationship so downstream helpers (recommendation engine,
    # _assessment_to_read) see the new status without a separate reload.
    a.status = new_status

    if new_code == "sent" and prev_code == "draft" and a.scale_id is not None:
        await snapshot_scale_for_assessment(db, a)

    # HRP-84: notify every participant when the assessment goes live.
    notify_event: str | None = None
    if new_code == "sent" and prev_code == "draft":
        notify_event = "evaluate"
    elif new_code == "done":
        notify_event = "completed"
    elif new_code == "cancelled" and prev_code in ("sent", "in_progress", "on_review"):
        notify_event = "cancelled"

    if new_code == "in_progress" and not a.started_at:
        a.started_at = datetime.now(timezone.utc)
    elif new_code == "on_review":
        # Preliminary results so reviewers can calibrate before "done".
        await _recompute_assessment_results(db, a)
        # HRP-170: surface the Recommended grade chart at On Review too;
        # the math runs on the same preliminary data the reviewer is about
        # to calibrate against.
        from app.modules.assessment.recommendation import compute_grade_recommendation

        await compute_grade_recommendation(db, tenant_id, a)
    elif new_code == "done":
        a.finished_at = datetime.now(timezone.utc)
        await _recompute_assessment_results(db, a)
        from app.modules.assessment.recommendation import compute_grade_recommendation

        await compute_grade_recommendation(db, tenant_id, a)
    elif new_code == "cancelled":
        if not a.finished_at:
            # HRP-161: surface the cancellation date in the UI in place of the
            # (now moot) deadline. Mirrors the HRP-132 PDP treatment — both
            # terminal codes pin ``finished_at`` so the field also doubles as
            # "when did this assessment end".
            a.finished_at = datetime.now(timezone.utc)
        # HRP-170: refresh the chart for a cancellation that crossed the
        # On Review checkpoint so the cached payload reflects the final
        # state. Pre-review cancellations are filtered out inside the
        # engine (no AssessmentResult rows yet).
        if prev_code == "on_review":
            from app.modules.assessment.recommendation import (
                compute_grade_recommendation,
            )

            await compute_grade_recommendation(db, tenant_id, a)

    await db.commit()

    # HRP-84: lifecycle notifications run after the commit so a delivery
    # failure can't roll back the status change.
    if notify_event is not None:
        await _dispatch_lifecycle_emails(db, a, notify_event)

    result2 = await db.execute(
        select(Assessment)
        .options(
            selectinload(Assessment.assessment_type),
            selectinload(Assessment.status),
            selectinload(Assessment.employee),
        )
        .where(Assessment.id == a.id)
    )
    return _assessment_to_read(result2.scalar_one())


class _UpdateSentinel:
    pass


_UPDATE_SENTINEL = _UpdateSentinel()


async def update_assessment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment_id: uuid.UUID,
    *,
    title: str | None | _UpdateSentinel = _UPDATE_SENTINEL,
    ended_at: datetime | None | _UpdateSentinel = _UPDATE_SENTINEL,
) -> dict:
    """Inline edit for non-terminal assessments (title and deadline).

    Each kwarg is tri-state: pass the sentinel (default) to leave the
    field untouched, pass `None` to clear it (only meaningful for
    `ended_at` — title is required, so `None` is rejected), or a value
    to overwrite.
    """
    result = await db.execute(
        select(Assessment)
        .options(selectinload(Assessment.status))
        .where(Assessment.id == assessment_id, Assessment.tenant_id == tenant_id)
    )
    a = result.scalar_one_or_none()
    if not a:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)
    await _assert_not_terminal(db, a)

    if not isinstance(title, _UpdateSentinel):
        if title is None or not title.strip():
            raise AppError("assessment_title_empty", status.HTTP_400_BAD_REQUEST)
        a.title = title
    if not isinstance(ended_at, _UpdateSentinel):
        a.ended_at = ended_at

    await db.commit()

    refreshed = await db.execute(
        select(Assessment)
        .options(
            selectinload(Assessment.assessment_type),
            selectinload(Assessment.status),
            selectinload(Assessment.employee),
        )
        .where(Assessment.id == a.id)
    )
    return _assessment_to_read(refreshed.scalar_one())


# --- Participants ---


async def add_participant(
    db: AsyncSession, tenant_id: uuid.UUID, assessment_id: uuid.UUID, data
) -> dict:
    a = await db.get(Assessment, assessment_id)
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)
    await _assert_not_terminal(db, a)

    # Resolve employee_id → user_id
    from app.modules.auth.models import User
    from app.modules.employee.models import Employee

    emp = await db.get(Employee, data.employee_id)
    if not emp or emp.tenant_id != tenant_id:
        raise AppError("employee_not_found", status.HTTP_404_NOT_FOUND)

    # Guard against orphaned employee.user_id references — without this the
    # INSERT below trips a FK violation at commit time (seen in production
    # when employee.user_id pointed at a deleted user row).
    user = await db.get(User, emp.user_id) if emp.user_id else None
    if user is None:
        raise AppError(
            "employee_has_no_user_account",
            status.HTTP_404_NOT_FOUND,
        )

    # HRP-18: one human can occupy at most one participant slot per assessment
    # — adding the same user again (any role) makes the average per-role math
    # double-count and lets a single rater submit multiple ballots.
    dup = await db.execute(
        select(AssessmentParticipant.id).where(
            AssessmentParticipant.assessment_id == assessment_id,
            AssessmentParticipant.user_id == emp.user_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise AppError(
            "assessment_employee_already_participant",
            status.HTTP_409_CONFLICT,
        )

    p = AssessmentParticipant(
        assessment_id=assessment_id,
        user_id=emp.user_id,
        role=data.role,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)

    # HRP-84: notify a participant added after the assessment is live so
    # they don't miss the window. Draft-stage adds are silent — the
    # broadcast on Draft → Sent will catch everyone.
    if a.status is None:
        await db.refresh(a, ["status"])
    if a.status is not None and a.status.code in ("sent", "in_progress", "on_review"):
        await _dispatch_lifecycle_emails(db, a, "evaluate", only_participant_id=p.id)

    user_name = _user_full_name(user)

    return {
        "id": p.id,
        "user_id": p.user_id,
        "user_name": user_name,
        "external_reviewer_id": None,
        "role": p.role,
        "is_completed": p.is_completed,
        "external_name": None,
        "external_email": None,
    }


# --- Competences / Criteria ---


async def add_competences(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment_id: uuid.UUID,
    competence_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    """Legacy: append competences without level. Kept for backwards compatibility."""
    a = await db.get(Assessment, assessment_id)
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)
    await _assert_not_terminal(db, a)

    if a.criteria_type is None:
        a.criteria_type = "competences"
    elif a.criteria_type != "competences":
        raise AppError(
            "assessment_criteria_type_not_competences",
            status.HTTP_400_BAD_REQUEST,
        )

    for cid in competence_ids:
        db.add(AssessmentCompetence(assessment_id=assessment_id, competence_id=cid))
    await db.commit()
    return competence_ids


async def _resolve_target_position_competences(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    specialization_id: uuid.UUID,
    grade_id: uuid.UUID | None,
) -> list[tuple[uuid.UUID, uuid.UUID | None]]:
    """Return [(competence_id, skill_level_id)] from grade-specialization links.

    grade_id=None means "all grades": union over all grades of the specialization,
    keep highest skill level per competence.
    """
    from app.modules.competence.models import SkillLevel
    from app.modules.grade_system.models import (
        GradeCompetenceLink,
        GradeSpecialization,
    )

    spec_q = select(GradeSpecialization).where(
        GradeSpecialization.tenant_id == tenant_id,
        GradeSpecialization.specialization_id == specialization_id,
    )
    if grade_id is not None:
        spec_q = spec_q.where(GradeSpecialization.grade_id == grade_id)
    spec_rows = (await db.execute(spec_q)).scalars().all()
    if not spec_rows:
        return []

    spec_ids = [s.id for s in spec_rows]
    links_q = (
        select(GradeCompetenceLink, SkillLevel.sort_index)
        .join(SkillLevel, SkillLevel.id == GradeCompetenceLink.skill_level_id)
        .where(GradeCompetenceLink.grade_specialization_id.in_(spec_ids))
    )
    by_comp: dict[uuid.UUID, tuple[uuid.UUID, int]] = {}
    for link, sort_idx in (await db.execute(links_q)).all():
        cur = by_comp.get(link.competence_id)
        if cur is None or sort_idx > cur[1]:
            by_comp[link.competence_id] = (link.skill_level_id, sort_idx)
    return [(cid, lvl) for cid, (lvl, _) in by_comp.items()]


async def _resolve_current_position_competences_for_employee(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> list[tuple[uuid.UUID, uuid.UUID | None]]:
    """For a single employee, look up competences from their current position
    (specialization + grade derived via Employee.position)."""
    from app.modules.employee.models import Employee
    from app.modules.position.models import Position

    emp = await db.get(Employee, employee_id)
    if not emp or not emp.position_id:
        return []
    pos = await db.get(Position, emp.position_id)
    if not pos or not pos.specialization_id:
        return []
    return await _resolve_target_position_competences(
        db, tenant_id, pos.specialization_id, pos.grade_id
    )


async def _validate_specialization_has_competences(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    specialization_id: uuid.UUID,
    grade_id: uuid.UUID | None,
) -> None:
    items = await _resolve_target_position_competences(
        db, tenant_id, specialization_id, grade_id
    )
    if not items:
        raise AppError(
            "assessment_specialization_no_competences",
            status.HTTP_400_BAD_REQUEST,
        )


DEFAULT_PASSING_SCORE = 75


async def _resolve_passing_score(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data,
) -> int | None:
    """Resolve the snapshot ``passing_score`` for an assessment per spec §1.4.

    target_position: explicit > grade_specializations default > 75.
    current_positions: explicit > 75 (HRP-183 — the chart is now built for
        current positions too, so the threshold is meaningful).
    competences: always NULL — Individual competences doesn't produce a
        recommendation, so the criteria sheet hides the input (HRP-183).
    """
    explicit = getattr(data, "passing_score", None)
    if data.criteria_type == "competences":
        return None
    if explicit is not None:
        return explicit

    if data.criteria_type != "target_position":
        return DEFAULT_PASSING_SCORE

    if data.grade_id is not None and data.specialization_id is not None:
        from app.modules.grade_system.models import GradeSpecialization

        row = await db.execute(
            select(GradeSpecialization.passing_score).where(
                GradeSpecialization.tenant_id == tenant_id,
                GradeSpecialization.specialization_id == data.specialization_id,
                GradeSpecialization.grade_id == data.grade_id,
            )
        )
        ref = row.scalar_one_or_none()
        if ref is not None:
            return ref

    return DEFAULT_PASSING_SCORE


async def _apply_criteria_to_assessment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment: Assessment,
    data,
    passing_score: int | None,
) -> None:
    """Mutate the given Assessment in-place per CriteriaUpdate. Caller commits."""
    # Wipe previous links
    existing = await db.execute(
        select(AssessmentCompetence).where(
            AssessmentCompetence.assessment_id == assessment.id
        )
    )
    for ac in existing.scalars().all():
        await db.delete(ac)
    await db.flush()

    assessment.criteria_type = data.criteria_type
    assessment.passing_score = passing_score

    if data.criteria_type == "current_positions":
        assessment.specialization_id = None
        assessment.grade_id = None
        items = await _resolve_current_position_competences_for_employee(
            db, tenant_id, assessment.employee_id
        )
        for cid, lvl in items:
            db.add(
                AssessmentCompetence(
                    assessment_id=assessment.id,
                    competence_id=cid,
                    skill_level_id=lvl,
                )
            )
    elif data.criteria_type == "target_position":
        if data.specialization_id is None:
            raise AppError(
                "assessment_specialization_id_required",
                status.HTTP_400_BAD_REQUEST,
            )
        await _validate_specialization_has_competences(
            db, tenant_id, data.specialization_id, data.grade_id
        )
        assessment.specialization_id = data.specialization_id
        assessment.grade_id = data.grade_id
        items = await _resolve_target_position_competences(
            db, tenant_id, data.specialization_id, data.grade_id
        )
        for cid, lvl in items:
            db.add(
                AssessmentCompetence(
                    assessment_id=assessment.id,
                    competence_id=cid,
                    skill_level_id=lvl,
                )
            )
    else:  # competences
        if not data.competences:
            raise AppError(
                "assessment_competence_required",
                status.HTTP_400_BAD_REQUEST,
            )
        assessment.specialization_id = None
        assessment.grade_id = None
        for item in data.competences:
            db.add(
                AssessmentCompetence(
                    assessment_id=assessment.id,
                    competence_id=item.competence_id,
                    skill_level_id=item.skill_level_id,
                )
            )


async def set_assessment_criteria(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment_id: uuid.UUID,
    data,
) -> dict:
    a = await db.get(
        Assessment, assessment_id, options=[selectinload(Assessment.status)]
    )
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)
    await _assert_criteria_editable(db, a)

    passing_score = await _resolve_passing_score(db, tenant_id, data)
    await _apply_criteria_to_assessment(db, tenant_id, a, data, passing_score)
    await db.commit()
    return await get_assessment_detail(db, tenant_id, assessment_id)


async def set_group_criteria(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    data,
) -> dict:
    g = await db.get(AssessmentGroup, group_id)
    if not g or g.tenant_id != tenant_id:
        raise AppError("assessment_group_not_found", status.HTTP_404_NOT_FOUND)

    # Pre-validate target_position once for the whole group
    if data.criteria_type == "target_position":
        if data.specialization_id is None:
            raise AppError(
                "assessment_specialization_id_required",
                status.HTTP_400_BAD_REQUEST,
            )
        await _validate_specialization_has_competences(
            db, tenant_id, data.specialization_id, data.grade_id
        )

    passing_score = await _resolve_passing_score(db, tenant_id, data)

    g.criteria_type = data.criteria_type
    g.specialization_id = (
        data.specialization_id if data.criteria_type == "target_position" else None
    )
    g.grade_id = data.grade_id if data.criteria_type == "target_position" else None
    g.passing_score = passing_score

    result = await db.execute(
        select(Assessment)
        .options(selectinload(Assessment.status))
        .where(Assessment.group_id == group_id)
    )
    for a in result.scalars().all():
        if a.status and a.status.code in TERMINAL_STATUSES:
            continue
        await _apply_criteria_to_assessment(db, tenant_id, a, data, passing_score)

    await db.commit()
    return await get_assessment_group(db, tenant_id, group_id)


# --- Criteria reference data ---


async def list_criteria_specializations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    include_id: uuid.UUID | None = None,
) -> list[dict]:
    """All active specializations available to this tenant.

    Earlier we filtered down to specializations that already had a grade
    with linked competences, but that left the picker empty whenever a
    fresh tenant had not yet wired up the grade system — the UI showed
    the placeholder with no items to choose from. The picker is now the
    raw active dictionary; any unusable choice is caught downstream when
    the grade dropdown returns no rows.

    HRP-292: ``include_id`` keeps an assessment's already-saved
    specialization in the list even after it was deactivated — the user
    must not lose the stored selection, but no other inactive item leaks.
    """
    from app.modules.dictionary.models import DictionaryItem
    from app.modules.dictionary.service import effective_is_active_expr

    active_or_included: ColumnElement[bool] = effective_is_active_expr(tenant_id).is_(
        True
    )
    if include_id is not None:
        active_or_included = active_or_included | (DictionaryItem.id == include_id)

    items_q = (
        select(DictionaryItem)
        .where(
            DictionaryItem.type == "specialization",
            active_or_included,
            # Origin (tenant_id IS NULL) items are visible to every tenant;
            # custom items are scoped to the requesting tenant.
            (DictionaryItem.tenant_id == tenant_id)
            | (DictionaryItem.tenant_id.is_(None)),
        )
        .order_by(DictionaryItem.sort_index, DictionaryItem.title)
    )
    items = (await db.execute(items_q)).scalars().all()
    return [{"id": d.id, "title": d.title, "i18n_key": d.i18n_key} for d in items]


async def list_criteria_grades(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    specialization_id: uuid.UUID,
    *,
    include_id: uuid.UUID | None = None,
) -> list[dict]:
    """Grades of given specialization that have at least one competence link.

    HRP-292: grades deactivated on the Dictionaries → Grades level
    (tenant-effective, HRP-285/337) are dropped; ``include_id`` keeps the
    assessment's already-saved grade visible so the stored selection
    survives deactivation.
    """
    from app.modules.dictionary.models import DictionaryItem
    from app.modules.dictionary.service import effective_is_active_expr
    from app.modules.grade_system.models import (
        GradeCompetenceLink,
        GradeSpecialization,
    )

    sub = (
        select(GradeSpecialization.grade_id)
        .join(
            GradeCompetenceLink,
            GradeCompetenceLink.grade_specialization_id == GradeSpecialization.id,
        )
        .where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == specialization_id,
        )
        .distinct()
    )
    active_or_included: ColumnElement[bool] = effective_is_active_expr(tenant_id).is_(
        True
    )
    if include_id is not None:
        active_or_included = active_or_included | (DictionaryItem.id == include_id)
    items_q = (
        select(DictionaryItem)
        .where(DictionaryItem.id.in_(sub), active_or_included)
        .order_by(DictionaryItem.sort_index, DictionaryItem.title)
    )
    items = (await db.execute(items_q)).scalars().all()
    return [{"id": d.id, "title": d.title, "i18n_key": d.i18n_key} for d in items]


# --- Answers ---


async def record_answer(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    current_user_id: uuid.UUID,
    assessment_id: uuid.UUID,
    data,
) -> dict:
    a = await db.get(Assessment, assessment_id)
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)
    await _assert_not_terminal(db, a)
    # HRP-185: lock the questionnaire while a reviewer is calibrating
    # Totals so the baseline doesn't shift underneath them.
    # HRP-329: the lock is permanent once a calibration was saved —
    # letting surveys resume would shift the baseline under saved results.
    await _assert_not_calibration_locked(db, a)

    # Ownership: a participant can only submit answers for their own row
    participant = await db.get(AssessmentParticipant, data.participant_id)
    if (
        not participant
        or participant.assessment_id != assessment_id
        or participant.user_id != current_user_id
    ):
        raise AppError(
            "assessment_answer_own_participant_only",
            status.HTTP_403_FORBIDDEN,
        )

    # Indicator must belong to one of the competences attached to the assessment
    from app.modules.competence.models import Indicator

    indicator = await db.get(Indicator, data.indicator_id)
    if not indicator:
        raise AppError("indicator_not_found", status.HTTP_404_NOT_FOUND)
    assessment_competences = await db.execute(
        select(AssessmentCompetence.competence_id).where(
            AssessmentCompetence.assessment_id == assessment_id
        )
    )
    competence_ids = {c for (c,) in assessment_competences.all()}
    if indicator.competence_id not in competence_ids:
        raise AppError(
            "assessment_indicator_not_in_competences",
            status.HTTP_400_BAD_REQUEST,
        )

    # HRP-146: assessment now opens in a Sheet with auto-save, so the
    # same indicator can be re-submitted by a participant tweaking their
    # answer. Upsert on (assessment, participant, indicator) keeps one
    # row per question — without this every keystroke / radio change
    # would clone an answer, double-count the rater and stall the
    # ``_maybe_mark_participant_completed`` distinct-count check.
    existing_q = await db.execute(
        select(AssessmentAnswer).where(
            AssessmentAnswer.assessment_id == assessment_id,
            AssessmentAnswer.participant_id == data.participant_id,
            AssessmentAnswer.indicator_id == data.indicator_id,
        )
    )
    answer = existing_q.scalar_one_or_none()
    if answer is None:
        answer = AssessmentAnswer(
            assessment_id=assessment_id,
            participant_id=data.participant_id,
            indicator_id=data.indicator_id,
            answer_option_id=data.answer_option_id,
            score=data.score,
            comment=data.comment,
        )
        db.add(answer)
    else:
        answer.answer_option_id = data.answer_option_id
        answer.score = data.score
        answer.comment = data.comment
    await db.flush()

    # First answer on a "sent" assessment kicks it to "in_progress".
    if a.status is None:
        await db.refresh(a, ["status"])
    if a.status.code == "sent":
        in_progress = await _get_status_by_code(db, "in_progress")
        a.status_id = in_progress.id
        a.status = in_progress
        if not a.started_at:
            a.started_at = datetime.now(timezone.utc)

    # Mark participant complete once they have answered every indicator
    # tied to the assessment.
    completed = await _maybe_mark_participant_completed(
        db, assessment_id, data.participant_id
    )
    if completed:
        # HRP-322: the completed survey is the billable unit (per-answer
        # autosave is free — this endpoint fires on every option change).
        # Resolve the cost once and pin it for precheck and consume, the
        # same price-pinning `_wrap_with_billing` does. Billing sits last,
        # right before the commit, so the tenant_credits row lock is not
        # held across the on_review recompute; a 402 rolls back this
        # answer and the flip, so the survey can be retried after top-up.
        cost = await billing_hooks.resolve_cost(
            db, tenant_id, "assessment.submit_answers"
        )
        await billing_hooks.precheck_action(
            db, tenant_id, "assessment.submit_answers", amount_override=cost
        )
        await billing_hooks.consume_action(
            db,
            tenant_id,
            current_user_id,
            "assessment.submit_answers",
            amount_override=cost,
        )

    await db.commit()
    await db.refresh(answer)
    return {
        "id": answer.id,
        "indicator_id": answer.indicator_id,
        "score": answer.score,
    }


async def get_participant_answers(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    current_user_id: uuid.UUID,
    assessment_id: uuid.UUID,
) -> dict:
    """HRP-146: return the caller's draft answers so the survey Sheet can
    rehydrate when reopened. The caller must be a participant of the
    assessment; non-participants get an empty payload (we leak nothing
    about other respondents' answers and don't 403 the page either)."""
    a = await db.get(Assessment, assessment_id)
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)

    participant_q = await db.execute(
        select(AssessmentParticipant).where(
            AssessmentParticipant.assessment_id == assessment_id,
            AssessmentParticipant.user_id == current_user_id,
        )
    )
    participant = participant_q.scalar_one_or_none()
    if participant is None:
        return {"participant_id": None, "answers": []}

    answers_q = await db.execute(
        select(AssessmentAnswer).where(
            AssessmentAnswer.assessment_id == assessment_id,
            AssessmentAnswer.participant_id == participant.id,
        )
    )
    return {
        "participant_id": participant.id,
        "answers": [
            {
                "indicator_id": ans.indicator_id,
                "answer_option_id": ans.answer_option_id,
                "score": ans.score,
                "comment": ans.comment,
            }
            for ans in answers_q.scalars().all()
        ],
    }


async def _maybe_mark_participant_completed(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    participant_id: uuid.UUID,
) -> bool:
    """Flip participant.is_completed when they have an answer for every
    indicator that belongs to a competence attached to the assessment.
    Returns True only for the transaction that performed the flip.

    Once every participant in the assessment is completed, the
    assessment itself auto-transitions to ``on_review`` (preliminary
    results are computed so reviewers can calibrate before ``done``).

    HRP-322: the completion flip is the billable unit — ``record_answer``
    bills ``assessment.submit_answers`` once when this returns True (the
    per-answer autosave itself is free). The helper stays billing-free so
    future callers don't silently inherit a charge; whoever flips must
    decide billing explicitly. The flip re-reads the participant row FOR
    UPDATE with ``populate_existing`` (the session already holds a stale
    copy from ``record_answer``): without the lock two concurrent
    autosaves of the final answer both observe ``is_completed=False``,
    both report the flip and the caller double-bills.

    HRP-75: the expected indicator set must mirror the questionnaire view
    the participant actually sees (HRP-43 cascade) — when an
    ``AssessmentCompetence`` row carries a ``skill_level_id``, only
    indicators with ``skill_level.sort_index <= target.sort_index`` are
    shown, so older logic that counted *all* indicators left
    ``is_completed`` stuck at False whenever any competence had higher-
    level indicators the user never saw.
    """
    from app.modules.competence.models import Indicator, SkillLevel

    # Cheap gate first: already-completed participants keep editing their
    # answers (allowed until the assessment turns terminal) — skip the two
    # aggregate counts below on every such autosave. Lock-free read; the
    # authoritative check happens under FOR UPDATE before the flip.
    participant = await db.get(AssessmentParticipant, participant_id)
    if not participant or participant.is_completed:
        return False

    target_level = aliased(SkillLevel, name="target_level")
    ind_level = aliased(SkillLevel, name="ind_level")
    expected_q = (
        select(func.count(func.distinct(Indicator.id)))
        .select_from(AssessmentCompetence)
        .join(
            Indicator,
            Indicator.competence_id == AssessmentCompetence.competence_id,
        )
        .outerjoin(target_level, target_level.id == AssessmentCompetence.skill_level_id)
        .outerjoin(ind_level, ind_level.id == Indicator.skill_level_id)
        .where(
            AssessmentCompetence.assessment_id == assessment_id,
            Indicator.is_active.is_(True),
            or_(
                # No skill_level filter on the AssessmentCompetence row →
                # questionnaire shows every active indicator of the
                # competence (legacy contract preserved).
                AssessmentCompetence.skill_level_id.is_(None),
                # Cascade: keep only indicators at or below the target
                # level. Indicators with no skill_level cannot be ranked,
                # so they're excluded when a filter is in effect — the
                # questionnaire wouldn't surface them either.
                and_(
                    AssessmentCompetence.skill_level_id.is_not(None),
                    ind_level.id.is_not(None),
                    ind_level.sort_index <= target_level.sort_index,
                ),
            ),
        )
    )
    expected = (await db.execute(expected_q)).scalar() or 0
    if expected == 0:
        return False

    answered_q = select(func.count(func.distinct(AssessmentAnswer.indicator_id))).where(
        AssessmentAnswer.assessment_id == assessment_id,
        AssessmentAnswer.participant_id == participant_id,
    )
    answered = (await db.execute(answered_q)).scalar() or 0
    if answered < expected:
        return False

    # Serialize the flip (see docstring): re-read under FOR UPDATE and
    # refresh the possibly-stale identity-map copy, so a concurrent
    # transaction that already flipped is observed here.
    participant = await db.get(
        AssessmentParticipant,
        participant_id,
        with_for_update=True,
        populate_existing=True,
    )
    if not participant or participant.is_completed:
        return False
    participant.is_completed = True
    await db.flush()

    await _maybe_auto_move_to_on_review(db, assessment_id)
    return True


async def _maybe_auto_move_to_on_review(
    db: AsyncSession, assessment_id: uuid.UUID
) -> None:
    """Flip an in-progress assessment into ``on_review`` when every
    participant has finished. Triggers preliminary result computation
    so reviewers can calibrate before approving.

    HRP-145: if the assessment is already in ``on_review`` (e.g. a
    reviewer flipped it manually with one respondent done and the rest
    finished afterward) recompute preliminary results so the freshly
    submitted survey feeds Avg Score. Calibration overrides survive —
    the HRP-126 guard inside ``_recompute_assessment_results`` keeps
    ``percent``/``level_id`` tied to ``calibrated_score`` when present.
    """
    assessment = await db.get(
        Assessment, assessment_id, options=[selectinload(Assessment.status)]
    )
    if assessment is None or assessment.status is None:
        return

    if assessment.status.code == "on_review":
        await _recompute_assessment_results(db, assessment)
        # HRP-170: refresh the cached chart when extra answers come in
        # after the manual on_review move so the percentages track the
        # latest data.
        from app.modules.assessment.recommendation import compute_grade_recommendation

        await compute_grade_recommendation(db, assessment.tenant_id, assessment)
        return

    if assessment.status.code != "in_progress":
        return

    remaining_q = (
        select(func.count())
        .select_from(AssessmentParticipant)
        .where(
            AssessmentParticipant.assessment_id == assessment_id,
            AssessmentParticipant.is_completed.is_(False),
        )
    )
    remaining = (await db.execute(remaining_q)).scalar() or 0
    if remaining > 0:
        return

    on_review = await _get_status_by_code(db, "on_review")
    assessment.status_id = on_review.id
    assessment.status = on_review
    await _recompute_assessment_results(db, assessment)
    # HRP-170: surface the chart as soon as the assessment auto-flips
    # into On Review (matches manual change_status path).
    from app.modules.assessment.recommendation import compute_grade_recommendation

    await compute_grade_recommendation(db, assessment.tenant_id, assessment)


# --- Results ---


async def get_results(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment_id: uuid.UUID,
    *,
    visible_employee_ids: set[uuid.UUID] | None = None,
    participant_user_id: uuid.UUID | None = None,
    restrict_to_active: bool = False,
    hide_results_for_employee: bool = False,
) -> list[dict]:
    """HRP-112: same scope/Draft fence as `get_assessment_detail` so a
    restricted caller can't curl `GET /assessments/{id}/results` to read
    calibrated scores for assessments they don't otherwise see.

    A 404 (not 403) keeps existence of out-of-scope assessments private —
    mirrors the HRP-40 detail endpoint.
    """
    a = await db.get(
        Assessment,
        assessment_id,
        options=[
            selectinload(Assessment.status),
            selectinload(Assessment.participants),
        ],
    )
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)

    if visible_employee_ids is not None:
        is_assessee_visible = a.employee_id in visible_employee_ids
        is_participant = participant_user_id is not None and any(
            p.user_id == participant_user_id for p in a.participants
        )
        if not is_assessee_visible and not is_participant:
            raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)

    if restrict_to_active and a.status is not None and a.status.code == "draft":
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)

    # HRP-243: Employee-only callers don't see results unless they are the
    # assessee and the assessment is closed (Done). Mirrors the gate in
    # ``get_assessment_detail`` so a direct GET /results can't reveal what
    # the detail endpoint already hides.
    if hide_results_for_employee and participant_user_id is not None:
        is_self_participant = any(
            p.role == "self" and p.user_id == participant_user_id
            for p in a.participants
        )
        status_code = a.status.code if a.status is not None else None
        if not is_self_participant or status_code != "done":
            return []

    result = await db.execute(
        select(AssessmentResult).where(AssessmentResult.assessment_id == assessment_id)
    )
    rows = list(result.scalars().all())
    level_ids = {r.level_id for r in rows if r.level_id is not None}
    levels_by_id: dict[uuid.UUID, AnswerScaleLevel] = {}
    if level_ids:
        levels_q = await db.execute(
            select(AnswerScaleLevel).where(AnswerScaleLevel.id.in_(level_ids))
        )
        levels_by_id = {lv.id: lv for lv in levels_q.scalars().all()}
    return [
        {
            "id": r.id,
            "competence_id": r.competence_id,
            "avg_score": r.avg_score,
            "calibrated_score": r.calibrated_score,
            "percent": r.percent,
            "level": (
                {
                    "id": levels_by_id[r.level_id].id,
                    "percent_from": levels_by_id[r.level_id].percent_from,
                    "percent_to": levels_by_id[r.level_id].percent_to,
                    "system_code": levels_by_id[r.level_id].system_code,
                    "system_title": levels_by_id[r.level_id].system_title,
                    "description": levels_by_id[r.level_id].description,
                    "sort_index": levels_by_id[r.level_id].sort_index,
                }
                if r.level_id and r.level_id in levels_by_id
                else None
            ),
        }
        for r in rows
    ]


async def calibrate(
    db: AsyncSession, tenant_id: uuid.UUID, assessment_id: uuid.UUID, items: list
) -> list[dict]:
    a = await db.get(Assessment, assessment_id)
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)
    await _assert_not_terminal(db, a)

    # HRP-126: derive percent (and matching level) from calibrated_score so
    # the Results table refreshes consistently with the manual override.
    # calibrated_score is on the same raw-weight scale as answer options, so
    # percent = score / max_option_weight * 100, clamped to [0, 100].
    max_weight: float = 0.0
    levels: list = []
    if a.scale_id is not None:
        scale = await _load_scale_full(db, a.scale_id)
        if scale is not None:
            scale_weights = [
                o.weight
                for o in scale.options
                if not o.is_neutral and o.weight is not None
            ]
            if scale_weights:
                max_weight = float(max(scale_weights))
            levels = sorted(
                scale.levels,
                key=lambda lv: (lv.sort_index, lv.percent_from),
            )

    def _percent_for(score: float | None) -> int | None:
        if score is None or max_weight <= 0:
            return None
        ratio = float(score) / max_weight
        return max(0, min(100, round(ratio * 100)))

    def _level_for(percent: int | None) -> uuid.UUID | None:
        if percent is None:
            return None
        for lv in levels:
            if lv.percent_from <= percent <= lv.percent_to:
                return lv.id
        return None

    results = []
    for item in items:
        # Upsert result
        result = await db.execute(
            select(AssessmentResult).where(
                AssessmentResult.assessment_id == assessment_id,
                AssessmentResult.competence_id == item.competence_id,
            )
        )
        r = result.scalar_one_or_none()
        new_percent = _percent_for(item.calibrated_score)
        new_level_id = _level_for(new_percent)
        if r:
            r.calibrated_score = item.calibrated_score
            r.percent = new_percent
            r.level_id = new_level_id
        else:
            r = AssessmentResult(
                assessment_id=assessment_id,
                competence_id=item.competence_id,
                avg_score=0,
                calibrated_score=item.calibrated_score,
                percent=new_percent,
                level_id=new_level_id,
            )
            db.add(r)
        results.append(r)

    await db.commit()

    levels_by_id = {lv.id: lv for lv in levels}
    return [
        {
            "id": r.id,
            "competence_id": r.competence_id,
            "avg_score": r.avg_score,
            "calibrated_score": r.calibrated_score,
            "percent": r.percent,
            "level": (
                {
                    "id": levels_by_id[r.level_id].id,
                    "percent_from": levels_by_id[r.level_id].percent_from,
                    "percent_to": levels_by_id[r.level_id].percent_to,
                    "system_code": levels_by_id[r.level_id].system_code,
                    "system_title": levels_by_id[r.level_id].system_title,
                    "description": levels_by_id[r.level_id].description,
                    "sort_index": levels_by_id[r.level_id].sort_index,
                }
                if r.level_id and r.level_id in levels_by_id
                else None
            ),
        }
        for r in results
    ]


# --- Calibration (HRP-185: per-indicator Total override) -------------------


_CALIBRATION_ALLOWED_STATUSES = ("on_review", "done")


async def _has_calibrated_totals(db: AsyncSession, assessment_id: uuid.UUID) -> bool:
    return bool(
        await db.scalar(
            select(func.count(AssessmentCalibratedTotal.id)).where(
                AssessmentCalibratedTotal.assessment_id == assessment_id
            )
        )
    )


async def _assert_not_calibration_locked(db: AsyncSession, a: Assessment) -> None:
    """HRP-185: no submissions while a reviewer edits Totals.
    HRP-329: nor after a calibration was saved — the calibrated results
    are final and a late survey would shift the baseline under them."""
    if a.calibration_in_progress:
        raise AppError(
            "assessment_calibration_in_progress",
            status.HTTP_409_CONFLICT,
        )
    if await _has_calibrated_totals(db, a.id):
        raise AppError(
            "assessment_calibrated_questionnaire_closed",
            status.HTTP_409_CONFLICT,
        )


async def _assert_calibration_eligible(
    db: AsyncSession, assessment: Assessment
) -> None:
    if assessment.status is None:
        await db.refresh(assessment, ["status"])
    if (
        assessment.status is None
        or assessment.status.code not in _CALIBRATION_ALLOWED_STATUSES
    ):
        raise AppError(
            "assessment_calibration_not_eligible",
            status.HTTP_400_BAD_REQUEST,
        )


async def start_calibration(
    db: AsyncSession, tenant_id: uuid.UUID, assessment_id: uuid.UUID
) -> dict:
    """Flip ``calibration_in_progress`` to True so participant
    submissions get blocked while the reviewer edits Totals."""
    a = await db.get(
        Assessment,
        assessment_id,
        options=[selectinload(Assessment.status)],
    )
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)
    await _assert_calibration_eligible(db, a)
    a.calibration_in_progress = True
    await db.commit()
    return await get_assessment_detail(db, tenant_id, assessment_id)


async def save_calibration(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment_id: uuid.UUID,
    totals: list,
) -> dict:
    """Upsert the per-indicator Total overrides, drop the in-progress
    flag and re-run the result recompute so percent/level reflect the
    calibrated values.

    ``totals`` items must expose ``indicator_id`` and ``answer_option_id``.
    """
    a = await db.get(
        Assessment,
        assessment_id,
        options=[selectinload(Assessment.status)],
    )
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)
    await _assert_calibration_eligible(db, a)

    seen_indicator_ids: set[uuid.UUID] = set()
    existing_q = await db.execute(
        select(AssessmentCalibratedTotal).where(
            AssessmentCalibratedTotal.assessment_id == assessment_id
        )
    )
    existing_by_indicator = {
        row.indicator_id: row for row in existing_q.scalars().all()
    }

    for item in totals:
        ind_id = uuid.UUID(str(item.indicator_id))
        opt_id = uuid.UUID(str(item.answer_option_id))
        seen_indicator_ids.add(ind_id)
        row = existing_by_indicator.get(ind_id)
        if row is None:
            db.add(
                AssessmentCalibratedTotal(
                    assessment_id=assessment_id,
                    indicator_id=ind_id,
                    answer_option_id=opt_id,
                )
            )
        else:
            row.answer_option_id = opt_id

    # Indicators with calibrated rows that the new payload didn't mention
    # are left as-is — Save should be additive, the spec only describes
    # Cancel as the wipe path.

    a.calibration_in_progress = False
    await db.flush()
    await _recompute_assessment_results(db, a)
    await db.commit()
    return await get_assessment_detail(db, tenant_id, assessment_id)


async def cancel_calibration(
    db: AsyncSession, tenant_id: uuid.UUID, assessment_id: uuid.UUID
) -> dict:
    """Discard every calibrated Total, drop the in-progress flag and
    recompute so percent/level land back on the raw survey averages."""
    a = await db.get(
        Assessment,
        assessment_id,
        options=[selectinload(Assessment.status)],
    )
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)
    await _assert_calibration_eligible(db, a)

    await db.execute(
        delete(AssessmentCalibratedTotal).where(
            AssessmentCalibratedTotal.assessment_id == assessment_id
        )
    )
    a.calibration_in_progress = False
    await db.flush()
    await _recompute_assessment_results(db, a)
    await db.commit()
    return await get_assessment_detail(db, tenant_id, assessment_id)


async def _calibrated_totals_map(
    db: AsyncSession, assessment_id: uuid.UUID
) -> dict[uuid.UUID, uuid.UUID]:
    rows = await db.execute(
        select(AssessmentCalibratedTotal).where(
            AssessmentCalibratedTotal.assessment_id == assessment_id
        )
    )
    return {r.indicator_id: r.answer_option_id for r in rows.scalars().all()}


# --- Detailed Results (HRP-154) ---

# Statuses where the Results block (and therefore Detailed results) is
# visible. ``cancelled`` is gated separately in ``get_detailed_results``
# because it only qualifies when the assessment was cancelled out of
# ``on_review`` — pre-review cancellations have no aggregated results.
_DETAILED_RESULTS_STATUSES = ("on_review", "done", "cancelled")


def _nearest_option(
    avg_weight: float, options: list[AnswerOption]
) -> AnswerOption | None:
    """Pick the answer option whose weight is closest to ``avg_weight``.

    Used for the per-question / per-role display values where the
    backend returns an averaged weight but the UI still wants both a
    label and an id from the scale (the id pre-populates the calibration
    Select with the computed Total, HRP-185 REDO).
    """
    rated = [
        (o, o.weight) for o in options if not o.is_neutral and o.weight is not None
    ]
    if not rated:
        return None
    return min(rated, key=lambda pair: abs(float(pair[1]) - avg_weight))[0]


def _detailed_indicator_row(
    ind: Any,
    role_buckets: dict[str, list[AssessmentAnswer]],
    *,
    scale_options: list[AnswerOption],
    options_by_id: dict[uuid.UUID, AnswerOption],
    max_weight: float,
    calibrated_by_indicator: dict[uuid.UUID, uuid.UUID],
    participant_external_name: dict[uuid.UUID, str | None],
    participant_user_id: dict[uuid.UUID, uuid.UUID | None],
    user_names: dict[uuid.UUID, str],
) -> dict:
    """Build one indicator's Detailed-results row from its per-role answers.

    Pure helper factored out of ``get_detailed_results``' inner loop: per-role
    average weight + comments, spec-ordered role list, the auto-computed Total,
    and the HRP-185 calibrated-Total override.
    """
    roles_out: list[dict] = []
    comments_out: list[dict] = []
    role_avg_weights_for_overall: list[float] = []

    for role, role_answers in role_buckets.items():
        real_weights: list[float] = []
        has_neutral = False
        for ans in role_answers:
            opt = (
                options_by_id.get(ans.answer_option_id)
                if ans.answer_option_id is not None
                else None
            )
            if opt is not None:
                if opt.is_neutral or opt.weight is None:
                    has_neutral = True
                else:
                    real_weights.append(float(opt.weight))
            elif ans.score is not None:
                real_weights.append(float(ans.score))
            if ans.comment:
                author_name = participant_external_name.get(ans.participant_id)
                if author_name is None:
                    uid = participant_user_id.get(ans.participant_id)
                    author_name = user_names.get(uid) if uid else None
                comments_out.append(
                    {
                        "role": role,
                        "user_name": author_name,
                        "created_at": ans.created_at,
                        "text": ans.comment,
                    }
                )

        if real_weights:
            avg_w = sum(real_weights) / len(real_weights)
            nearest = _nearest_option(avg_w, scale_options)
            roles_out.append(
                {
                    "role": role,
                    "answer_title": nearest.title if nearest is not None else None,
                    "answer_code": nearest.code if nearest is not None else None,
                    "answer_weight": avg_w,
                    "is_neutral": False,
                    "answers_count": len(role_answers),
                }
            )
            role_avg_weights_for_overall.append(avg_w)
        elif has_neutral:
            # All responses for this role on this indicator
            # were "Don't know" — surface the neutral marker.
            neutral_opt = next(
                (o for o in scale_options if o.is_neutral),
                None,
            )
            roles_out.append(
                {
                    "role": role,
                    "answer_title": (
                        neutral_opt.title if neutral_opt is not None else "Don't know"
                    ),
                    "answer_code": (
                        neutral_opt.code if neutral_opt is not None else None
                    ),
                    "answer_weight": None,
                    "is_neutral": True,
                    "answers_count": len(role_answers),
                }
            )
        # else: no responses from this role for this indicator,
        # so we drop it (per spec: roles without participants
        # or surveys aren't shown).

    # Sort roles deterministically by spec order, falling back
    # to alphabetical for anything custom.
    role_order = {
        "self": 0,
        "manager": 1,
        "peer": 2,
        "subordinate": 3,
    }
    roles_out.sort(key=lambda r: (role_order.get(r["role"], 99), r["role"]))

    overall_avg: float | None = None
    overall_percent: int | None = None
    overall_title: str | None = None
    overall_code: str | None = None
    # HRP-185 REDO: expose the option id of the auto-computed
    # Total so the calibration Select can pre-populate with
    # the same answer the badge shows (instead of a "Total"
    # placeholder that hides what's already there).
    overall_answer_option_id: uuid.UUID | None = None
    if role_avg_weights_for_overall:
        overall_avg = sum(role_avg_weights_for_overall) / len(
            role_avg_weights_for_overall
        )
        overall_opt = _nearest_option(overall_avg, scale_options)
        if overall_opt is not None:
            overall_title = overall_opt.title
            overall_code = overall_opt.code
            overall_answer_option_id = overall_opt.id
        if max_weight > 0:
            overall_percent = max(0, min(100, round(overall_avg / max_weight * 100)))

    # HRP-185: if a reviewer pinned this indicator's Total,
    # the calibrated option replaces the computed Total so
    # the Detailed results row matches what the recompute
    # used. The per-role values are left untouched — they
    # still show what each role originally answered.
    calibrated_opt_id = calibrated_by_indicator.get(ind.id)
    is_calibrated = calibrated_opt_id is not None
    if calibrated_opt_id is not None:
        opt = options_by_id.get(calibrated_opt_id)
        if opt is not None:
            overall_title = opt.title
            overall_code = opt.code
            overall_answer_option_id = opt.id
            if opt.weight is not None:
                overall_avg = float(opt.weight)
                if max_weight > 0:
                    overall_percent = max(
                        0,
                        min(
                            100,
                            round(float(opt.weight) / max_weight * 100),
                        ),
                    )

    # Sort comments newest first.
    comments_out.sort(key=lambda c: c["created_at"], reverse=True)

    return {
        "indicator_id": ind.id,
        "indicator_title": ind.title,
        "roles": roles_out,
        "comments": comments_out,
        "overall_avg_weight": overall_avg,
        "overall_percent": overall_percent,
        "overall_answer_title": overall_title,
        "overall_answer_code": overall_code,
        "overall_answer_option_id": overall_answer_option_id,
        "all_dont_know": (
            not is_calibrated
            and not role_avg_weights_for_overall
            and bool(role_buckets)
        ),
        "is_calibrated": is_calibrated,
        "calibrated_answer_option_id": calibrated_opt_id,
    }


def _detailed_skill_level_percents(
    sl_indicators: list,
    *,
    completed_roles: set[str],
    answers_by_indicator_role: dict[uuid.UUID, dict[str, list[AssessmentAnswer]]],
    options_by_id: dict[uuid.UUID, AnswerOption],
    calibrated_by_indicator: dict[uuid.UUID, uuid.UUID],
    max_weight: float,
) -> list[float]:
    """Per-role (and synthetic calibrated-role) percents for one skill level.

    Mirrors ``_recompute_assessment_results`` within a single level (weighted
    indicator avg per role). HRP-185 REDO #3: a calibrated indicator's per-role
    answers are skipped and the override weight contributes once as a synthetic
    "calibrated" role, matching ``_compute_breakdown_for_assessment``.
    """
    role_level_percents: list[float] = []
    if max_weight <= 0:
        return role_level_percents

    # Real roles consume only the indicators whose Totals are
    # NOT calibrated; calibrated indicators are handled
    # separately below so they don't dilute the average.
    for role in completed_roles:
        weighted_sum = 0.0
        weight_sum = 0.0
        for ind in sl_indicators:
            if ind.id in calibrated_by_indicator:
                continue
            role_answers = answers_by_indicator_role.get(ind.id, {}).get(role, [])
            real_weights = []
            for ans in role_answers:
                if ans.answer_option_id is not None:
                    opt = options_by_id.get(ans.answer_option_id)
                    if opt is None or opt.is_neutral or opt.weight is None:
                        continue
                    real_weights.append(float(opt.weight))
                elif ans.score is not None:
                    real_weights.append(float(ans.score))
            if not real_weights:
                continue
            ind_avg = sum(real_weights) / len(real_weights)
            weight = float(ind.weight) if ind.weight else 1.0
            weighted_sum += ind_avg * weight
            weight_sum += weight
        if weight_sum == 0:
            continue
        role_level_percents.append(weighted_sum / weight_sum / max_weight * 100.0)

    # Synthetic "calibrated" role contributes the weighted
    # average of the override weights for the calibrated
    # indicators that sit on this skill level.
    calibrated_weighted_sum = 0.0
    calibrated_weight_sum = 0.0
    for ind in sl_indicators:
        calibrated_opt_id = calibrated_by_indicator.get(ind.id)
        if calibrated_opt_id is None:
            continue
        opt = options_by_id.get(calibrated_opt_id)
        if opt is None or opt.weight is None:
            continue
        weight = float(ind.weight) if ind.weight else 1.0
        calibrated_weighted_sum += float(opt.weight) * weight
        calibrated_weight_sum += weight
    if calibrated_weight_sum > 0:
        role_level_percents.append(
            calibrated_weighted_sum / calibrated_weight_sum / max_weight * 100.0
        )

    return role_level_percents


async def get_detailed_results(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment_id: uuid.UUID,
    *,
    visible_employee_ids: set[uuid.UUID] | None = None,
) -> dict:
    """HRP-154: per-competence breakdown for the Results page.

    Visibility mirrors the Results block — only assessments past the
    on_review checkpoint expose data. Cancelled assessments are only
    surfaced when they were cancelled *after* preliminary results were
    produced (``AssessmentResult`` rows present).

    Returns an empty competence list when the assessment exists but
    there's nothing to show yet (so the frontend can render an empty
    block instead of a 404).
    """
    from app.modules.competence.models import Competence, Indicator, SkillLevel
    from app.modules.dictionary.models import DictionaryItem

    a = await db.get(
        Assessment, assessment_id, options=[selectinload(Assessment.status)]
    )
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)

    if visible_employee_ids is not None and a.employee_id not in visible_employee_ids:
        # Manager-scoped users can't peek at other divisions even if they
        # know the assessment id — match the HRP-112 fence on
        # ``get_results``.
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)

    if a.status is None or a.status.code not in _DETAILED_RESULTS_STATUSES:
        return {"assessment_id": assessment_id, "competences": []}

    # Load participants fresh — relying on a relationship loader after the
    # caller flipped is_completed in the same session leaves us with the
    # stale value from the identity map.
    participants_q = await db.execute(
        select(AssessmentParticipant).where(
            AssessmentParticipant.assessment_id == assessment_id
        )
    )
    participants = list(participants_q.scalars().all())

    # Gather competences with type label.
    comps_q = await db.execute(
        select(AssessmentCompetence).where(
            AssessmentCompetence.assessment_id == assessment_id
        )
    )
    assessment_competences = list(comps_q.scalars().all())
    if not assessment_competences:
        return {"assessment_id": assessment_id, "competences": []}

    competence_ids = [ac.competence_id for ac in assessment_competences]
    competence_rows = (
        (await db.execute(select(Competence).where(Competence.id.in_(competence_ids))))
        .scalars()
        .all()
    )
    competence_by_id = {c.id: c for c in competence_rows}

    type_ids = {c.competence_type_id for c in competence_rows if c.competence_type_id}
    type_items: dict[uuid.UUID, DictionaryItem] = {}
    if type_ids:
        type_rows = (
            (
                await db.execute(
                    select(DictionaryItem).where(DictionaryItem.id.in_(type_ids))
                )
            )
            .scalars()
            .all()
        )
        type_items = {row.id: row for row in type_rows}

    # Scale (snapshot) for option titles and max weight.
    scale = await _load_scale_full(db, a.scale_id) if a.scale_id is not None else None
    if scale is None:
        # No scale → no quantitative breakdown possible. Surface what we
        # have (titles + roles) with everything else null so the UI can
        # still display the structure.
        options_by_id = {}
        scale_options: list[AnswerOption] = []
        max_weight = 0.0
        scale_levels: list[AnswerScaleLevel] = []
    else:
        scale_options = list(scale.options)
        options_by_id = {o.id: o for o in scale_options}
        weights_in_scale = [
            o.weight for o in scale_options if not o.is_neutral and o.weight is not None
        ]
        max_weight = float(max(weights_in_scale)) if weights_in_scale else 0.0
        scale_levels = sorted(
            scale.levels, key=lambda lv: (lv.sort_index, lv.percent_from)
        )

    # Participants → role mapping; also count how many completed per role
    # so we can drop roles that had no completed surveys.
    participant_role: dict[uuid.UUID, str] = {p.id: p.role for p in participants}
    completed_roles = {p.role for p in participants if p.is_completed}

    # Indicators for the assessed competences, with their skill levels.
    indicators_q = await db.execute(
        select(Indicator).where(Indicator.competence_id.in_(competence_ids))
    )
    indicators = list(indicators_q.scalars().all())
    indicators_by_competence: dict[uuid.UUID, list[Indicator]] = {}
    for ind in indicators:
        indicators_by_competence.setdefault(ind.competence_id, []).append(ind)

    skill_level_ids = {ind.skill_level_id for ind in indicators if ind.skill_level_id}
    for ac in assessment_competences:
        if ac.skill_level_id:
            skill_level_ids.add(ac.skill_level_id)
    skill_levels_by_id: dict[uuid.UUID, SkillLevel] = {}
    if skill_level_ids:
        sl_rows = (
            (
                await db.execute(
                    select(SkillLevel).where(SkillLevel.id.in_(skill_level_ids))
                )
            )
            .scalars()
            .all()
        )
        skill_levels_by_id = {sl.id: sl for sl in sl_rows}

    # HRP-185: calibrated Totals override the per-indicator Total field
    # so Detailed results matches what the recompute used. Loaded once
    # here so we don't issue per-indicator queries inside the loop.
    calibrated_by_indicator = await _calibrated_totals_map(db, assessment_id)

    # Answers + the participant/user metadata we need for comments.
    answers_q = await db.execute(
        select(AssessmentAnswer).where(AssessmentAnswer.assessment_id == assessment_id)
    )
    answers = list(answers_q.scalars().all())

    # Cache user display names for comment authors.
    from app.modules.auth.models import User as AuthUser

    participant_user_id: dict[uuid.UUID, uuid.UUID | None] = {
        p.id: p.user_id for p in participants
    }
    participant_external_name: dict[uuid.UUID, str | None] = {}
    external_ids = [
        p.external_reviewer_id for p in participants if p.external_reviewer_id
    ]
    if external_ids:
        ext_rows = (
            (
                await db.execute(
                    select(ExternalReviewer).where(
                        ExternalReviewer.id.in_(external_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        ext_by_id = {row.id: row for row in ext_rows}
        for p in participants:
            if p.external_reviewer_id and p.external_reviewer_id in ext_by_id:
                participant_external_name[p.id] = ext_by_id[p.external_reviewer_id].name

    user_ids = {uid for uid in participant_user_id.values() if uid is not None}
    user_names: dict[uuid.UUID, str] = {}
    if user_ids:
        user_rows = (
            (await db.execute(select(AuthUser).where(AuthUser.id.in_(user_ids))))
            .scalars()
            .all()
        )
        for u in user_rows:
            user_names[u.id] = _user_full_name(u) or u.email

    # Existing aggregated results (calibrated overrides percent/level).
    results_q = await db.execute(
        select(AssessmentResult).where(AssessmentResult.assessment_id == assessment_id)
    )
    result_by_competence = {r.competence_id: r for r in results_q.scalars().all()}

    # Pre-bucket answers per indicator → role → list of answer rows.
    answers_by_indicator_role: dict[uuid.UUID, dict[str, list[AssessmentAnswer]]] = {}
    for ans in answers:
        role = participant_role.get(ans.participant_id)
        if role is None:
            continue
        answers_by_indicator_role.setdefault(ans.indicator_id, {}).setdefault(
            role, []
        ).append(ans)

    competences_out: list[dict] = []

    for ac in assessment_competences:
        comp = competence_by_id.get(ac.competence_id)
        if comp is None:
            continue

        comp_indicators = sorted(
            indicators_by_competence.get(ac.competence_id, []),
            key=lambda i: (
                (
                    skill_levels_by_id[i.skill_level_id].sort_index
                    if i.skill_level_id and i.skill_level_id in skill_levels_by_id
                    else 0
                ),
                i.sort_index,
            ),
        )

        # Required level: explicit AssessmentCompetence.skill_level_id or
        # the highest skill level present in the competence's indicators
        # (Specialization-All grades case — HRP-154 spec).
        required_sl_id: uuid.UUID | None = ac.skill_level_id
        if required_sl_id is None and comp_indicators:
            sl_candidates = [
                skill_levels_by_id[i.skill_level_id]
                for i in comp_indicators
                if i.skill_level_id and i.skill_level_id in skill_levels_by_id
            ]
            if sl_candidates:
                required_sl_id = max(sl_candidates, key=lambda sl: sl.sort_index).id
        required_sl = (
            skill_levels_by_id[required_sl_id]
            if required_sl_id and required_sl_id in skill_levels_by_id
            else None
        )
        required_sl_title = required_sl.title if required_sl else None

        # HRP-184: Detailed results must show only the indicators the
        # questionnaire actually surfaced — drop anything at a skill level
        # above the required level so the layout matches Question preview
        # and Take this assessment. The cascade rule is the same one the
        # questionnaire walks (``_maybe_mark_participant_completed``).
        target_sort_idx: int | None = (
            skill_levels_by_id[required_sl_id].sort_index
            if required_sl_id and required_sl_id in skill_levels_by_id
            else None
        )
        if target_sort_idx is not None:
            comp_indicators = [
                i
                for i in comp_indicators
                if i.skill_level_id is not None
                and i.skill_level_id in skill_levels_by_id
                and skill_levels_by_id[i.skill_level_id].sort_index <= target_sort_idx
            ]

        # Group indicators by skill level for the per-level breakdown.
        indicators_by_level: dict[uuid.UUID | None, list[Indicator]] = {}
        for ind in comp_indicators:
            indicators_by_level.setdefault(ind.skill_level_id, []).append(ind)

        # Sort skill levels by sort_index; unknown level (None) goes last.
        ordered_level_keys = sorted(
            indicators_by_level.keys(),
            key=lambda sl_id: (
                1 if sl_id is None else 0,
                (
                    skill_levels_by_id[sl_id].sort_index
                    if sl_id and sl_id in skill_levels_by_id
                    else 0
                ),
            ),
        )

        skill_levels_out: list[dict] = []
        for sl_id in ordered_level_keys:
            sl_indicators = indicators_by_level[sl_id]
            sl_obj = skill_levels_by_id.get(sl_id) if sl_id else None

            # Per-question breakdown + per-role aggregation.
            questions_out: list[dict] = []

            for ind in sl_indicators:
                role_buckets = answers_by_indicator_role.get(ind.id, {})
                questions_out.append(
                    _detailed_indicator_row(
                        ind,
                        role_buckets,
                        scale_options=scale_options,
                        options_by_id=options_by_id,
                        max_weight=max_weight,
                        calibrated_by_indicator=calibrated_by_indicator,
                        participant_external_name=participant_external_name,
                        participant_user_id=participant_user_id,
                        user_names=user_names,
                    )
                )

            # Per-skill-level percent: mirror _recompute_assessment_results
            # within a single level (weighted indicator avg per role), with
            # the HRP-185 calibrated-role handling. See helper docstring.
            role_level_percents = _detailed_skill_level_percents(
                sl_indicators,
                completed_roles=completed_roles,
                answers_by_indicator_role=answers_by_indicator_role,
                options_by_id=options_by_id,
                calibrated_by_indicator=calibrated_by_indicator,
                max_weight=max_weight,
            )

            if role_level_percents:
                percent_for_skill_level = max(
                    0,
                    min(
                        100,
                        round(sum(role_level_percents) / len(role_level_percents)),
                    ),
                )
                all_dont_know_level = False
            else:
                percent_for_skill_level = None
                all_dont_know_level = True

            skill_levels_out.append(
                {
                    "skill_level_id": sl_id,
                    "skill_level_title": sl_obj.title if sl_obj else None,
                    "skill_level_i18n_key": sl_obj.i18n_key if sl_obj else None,
                    "sort_index": sl_obj.sort_index if sl_obj else 0,
                    "percent_for_skill_level": percent_for_skill_level,
                    "all_dont_know": all_dont_know_level,
                    "questions": questions_out,
                }
            )

        # Competence-level summary: pull from the existing AssessmentResult
        # so calibrated overrides win for percent/level.
        agg = result_by_competence.get(ac.competence_id)
        agg_percent = agg.percent if agg else None
        agg_level_id = agg.level_id if agg else None
        agg_level_title = None
        agg_level_code = None
        if agg_level_id is not None:
            for lv in scale_levels:
                if lv.id == agg_level_id:
                    # Origin levels carry system_code with a NULL
                    # system_title — without the code the seeded scale's
                    # level is unlabelable (HRP-479).
                    agg_level_title = lv.system_title
                    agg_level_code = lv.system_code
                    break

        all_dont_know_comp = (
            all(sl["all_dont_know"] for sl in skill_levels_out)
            if skill_levels_out
            else True
        )

        competences_out.append(
            {
                "competence_id": comp.id,
                "competence_title": comp.title,
                "competence_type_id": comp.competence_type_id,
                "competence_type_title": (
                    type_items[comp.competence_type_id].title
                    if comp.competence_type_id in type_items
                    else None
                ),
                "competence_type_i18n_key": (
                    type_items[comp.competence_type_id].i18n_key
                    if comp.competence_type_id in type_items
                    else None
                ),
                "required_skill_level_id": required_sl_id,
                "required_skill_level_title": required_sl_title,
                "required_skill_level_i18n_key": (
                    required_sl.i18n_key if required_sl else None
                ),
                "percent": agg_percent if not all_dont_know_comp else None,
                "level_id": agg_level_id if not all_dont_know_comp else None,
                "level_title": agg_level_title if not all_dont_know_comp else None,
                "level_code": agg_level_code if not all_dont_know_comp else None,
                "all_dont_know": all_dont_know_comp,
                "skill_levels": skill_levels_out,
            }
        )

    return {"assessment_id": assessment_id, "competences": competences_out}


# --- Answer Scales ---


async def set_assessment_scale(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment_id: uuid.UUID,
    scale_id: uuid.UUID | None,
) -> dict:
    from sqlalchemy import or_

    a = await db.get(
        Assessment, assessment_id, options=[selectinload(Assessment.status)]
    )
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)
    await _assert_not_terminal(db, a)

    if scale_id is not None:
        scale_row = await db.execute(
            select(AnswerScale).where(
                AnswerScale.id == scale_id,
                or_(
                    AnswerScale.tenant_id == tenant_id,
                    AnswerScale.tenant_id.is_(None),
                ),
                AnswerScale.deleted_at.is_(None),
                AnswerScale.is_snapshot.is_(False),
            )
        )
        if scale_row.scalar_one_or_none() is None:
            raise AppError("answer_scale_not_found", status.HTTP_404_NOT_FOUND)

    a.scale_id = scale_id
    await db.commit()
    return await get_assessment_detail(db, tenant_id, assessment_id)


async def set_group_scale(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    scale_id: uuid.UUID | None,
) -> dict:
    from sqlalchemy import or_

    g = await db.get(AssessmentGroup, group_id)
    if not g or g.tenant_id != tenant_id:
        raise AppError("assessment_group_not_found", status.HTTP_404_NOT_FOUND)

    if scale_id is not None:
        scale_row = await db.execute(
            select(AnswerScale).where(
                AnswerScale.id == scale_id,
                or_(
                    AnswerScale.tenant_id == tenant_id,
                    AnswerScale.tenant_id.is_(None),
                ),
                AnswerScale.deleted_at.is_(None),
                AnswerScale.is_snapshot.is_(False),
            )
        )
        if scale_row.scalar_one_or_none() is None:
            raise AppError("answer_scale_not_found", status.HTTP_404_NOT_FOUND)

    # Scale is locked once any child has left draft — that's when the scale gets
    # snapshotted, so changing the group value would orphan snapshots.
    children = await db.execute(
        select(Assessment)
        .options(selectinload(Assessment.status))
        .where(Assessment.group_id == group_id)
    )
    assessments = children.scalars().all()
    if any(a.status and a.status.code != "draft" for a in assessments):
        raise AppError(
            "assessment_group_scale_locked",
            status.HTTP_400_BAD_REQUEST,
        )

    g.scale_id = scale_id
    for a in assessments:
        a.scale_id = scale_id
    await db.commit()
    return await get_assessment_group(db, tenant_id, group_id)


async def _recompute_assessment_results(
    db: AsyncSession, assessment: Assessment
) -> None:
    """Compute avg_score / percent / level_id per competence.

    Algorithm (HRP-62 spec): aggregate by participant role, then by skill
    level inside each role with indicator weights, then average across
    roles. Neutral options ("Don't know") and absent answers are dropped.
    Roles with no usable answers are excluded from the role average; if a
    competence ends up with no answers at all, ``avg_score`` is 0 and
    ``percent`` is left null.
    """
    from app.modules.competence.models import Indicator

    competences_q = await db.execute(
        select(AssessmentCompetence).where(
            AssessmentCompetence.assessment_id == assessment.id
        )
    )
    competences = list(competences_q.scalars().all())
    if not competences:
        return

    scale = (
        await _load_scale_full(db, assessment.scale_id)
        if assessment.scale_id is not None
        else None
    )
    options_by_id: dict[uuid.UUID, AnswerOption] = (
        {o.id: o for o in scale.options} if scale else {}
    )
    weights_in_scale = (
        [o.weight for o in scale.options if not o.is_neutral and o.weight is not None]
        if scale
        else []
    )
    max_weight = max(weights_in_scale) if weights_in_scale else 0

    participants_q = await db.execute(
        select(AssessmentParticipant).where(
            AssessmentParticipant.assessment_id == assessment.id
        )
    )
    role_by_participant: dict[uuid.UUID, str] = {
        p.id: p.role for p in participants_q.scalars().all()
    }

    answers_q = await db.execute(
        select(AssessmentAnswer).where(AssessmentAnswer.assessment_id == assessment.id)
    )
    answers = list(answers_q.scalars().all())

    # HRP-185: when a reviewer has pinned a per-indicator Total, the
    # recompute treats that calibrated answer as the authoritative value
    # for every role — real answers for the calibrated indicators are
    # ignored, and a synthetic "calibrated" role contributes the override.
    cal_q = await db.execute(
        select(AssessmentCalibratedTotal).where(
            AssessmentCalibratedTotal.assessment_id == assessment.id
        )
    )
    calibrated_by_indicator: dict[uuid.UUID, uuid.UUID] = {
        t.indicator_id: t.answer_option_id for t in cal_q.scalars().all()
    }

    answered_indicator_ids = {a.indicator_id for a in answers}
    competence_ids = {ac.competence_id for ac in competences}
    indicators_by_id: dict[uuid.UUID, Indicator] = {}
    if competence_ids:
        ind_q = await db.execute(
            select(Indicator).where(Indicator.competence_id.in_(competence_ids))
        )
        for ind in ind_q.scalars().all():
            indicators_by_id[ind.id] = ind
    # Pull in any indicator referenced by an answer that isn't on the
    # current competence list (defensive — shouldn't happen, but better
    # than dropping the answer silently).
    missing = (answered_indicator_ids | set(calibrated_by_indicator)) - set(
        indicators_by_id
    )
    if missing:
        extra_q = await db.execute(select(Indicator).where(Indicator.id.in_(missing)))
        for ind in extra_q.scalars().all():
            indicators_by_id[ind.id] = ind

    # raw[competence][role][skill_level][indicator] = list of scores
    raw: dict[uuid.UUID, dict[str, dict[uuid.UUID, dict[uuid.UUID, list[float]]]]] = {}
    if max_weight > 0:
        for ans in answers:
            answer_ind = indicators_by_id.get(ans.indicator_id)
            if answer_ind is None:
                continue
            # HRP-185: skip real answers for indicators with a calibrated
            # Total — the synthetic injection below carries that data.
            if ans.indicator_id in calibrated_by_indicator:
                continue
            role = role_by_participant.get(ans.participant_id)
            if role is None:
                continue
            score: float | None = None
            if ans.answer_option_id is not None:
                opt = options_by_id.get(ans.answer_option_id)
                if opt is None or opt.is_neutral or opt.weight is None:
                    continue
                score = float(opt.weight)
            elif ans.score is not None:
                score = float(ans.score)
            if score is None:
                continue
            (
                raw.setdefault(answer_ind.competence_id, {})
                .setdefault(role, {})
                .setdefault(answer_ind.skill_level_id, {})
                .setdefault(answer_ind.id, [])
                .append(score)
            )
        for ind_id, option_id in calibrated_by_indicator.items():
            calib_ind = indicators_by_id.get(ind_id)
            if calib_ind is None or calib_ind.skill_level_id is None:
                continue
            opt = options_by_id.get(option_id)
            if opt is None or opt.weight is None:
                continue
            (
                raw.setdefault(calib_ind.competence_id, {})
                .setdefault("calibrated", {})
                .setdefault(calib_ind.skill_level_id, {})
                .setdefault(calib_ind.id, [])
                .append(float(opt.weight))
            )

    existing_q = await db.execute(
        select(AssessmentResult).where(AssessmentResult.assessment_id == assessment.id)
    )
    existing_by_comp = {r.competence_id: r for r in existing_q.scalars().all()}

    levels = sorted(
        scale.levels if scale else [],
        key=lambda lv: (lv.sort_index, lv.percent_from),
    )

    for ac in competences:
        role_data = raw.get(ac.competence_id, {})
        # Step 1+2: per role, average weighted level percent across the
        # competence's skill levels that produced at least one answer.
        role_percents: list[float] = []
        for _role, levels_data in role_data.items():
            level_percents: list[float] = []
            for _level_id, indicator_scores in levels_data.items():
                weighted_sum = 0.0
                weight_sum = 0.0
                for indicator_id, scores in indicator_scores.items():
                    if not scores:
                        continue
                    indicator_avg = sum(scores) / len(scores)
                    raw_weight = indicators_by_id[indicator_id].weight
                    # Indicator weight defaults to 0 in the schema; treat
                    # that as "unweighted" (1) so we don't wipe out the
                    # whole role when no weights are configured.
                    weight = float(raw_weight) if raw_weight else 1.0
                    weighted_sum += indicator_avg * weight
                    weight_sum += weight
                if weight_sum == 0:
                    continue
                level_avg = weighted_sum / weight_sum
                level_percents.append(level_avg / max_weight * 100.0)
            if level_percents:
                role_percents.append(sum(level_percents) / len(level_percents))

        if role_percents:
            final_percent = sum(role_percents) / len(role_percents)
            avg = round(final_percent / 100.0, 4)
            percent: int | None = round(final_percent)
        else:
            avg = 0.0
            percent = None

        level_id: uuid.UUID | None = None
        if percent is not None and levels:
            for lv in levels:
                if lv.percent_from <= percent <= lv.percent_to:
                    level_id = lv.id
                    break

        existing = existing_by_comp.get(ac.competence_id)
        # HRP-126: when calibration override is present on an existing result,
        # keep percent/level aligned with the calibrated score so transitions
        # (on_review → done) don't silently revert the reviewer's decision.
        if (
            existing is not None
            and existing.calibrated_score is not None
            and max_weight > 0
        ):
            calibrated_ratio = float(existing.calibrated_score) / max_weight
            percent = max(0, min(100, round(calibrated_ratio * 100)))
            level_id = None
            for lv in levels:
                if lv.percent_from <= percent <= lv.percent_to:
                    level_id = lv.id
                    break

        if existing is None:
            db.add(
                AssessmentResult(
                    assessment_id=assessment.id,
                    competence_id=ac.competence_id,
                    avg_score=avg,
                    percent=percent,
                    level_id=level_id,
                )
            )
        else:
            existing.avg_score = avg
            existing.percent = percent
            existing.level_id = level_id


# --- Mass Assessment (Groups) ---


async def create_mass_assessment(
    db: AsyncSession, tenant_id: uuid.UUID, initiator_id: uuid.UUID, data
) -> dict:
    from app.modules.employee.models import Employee

    atype = await _get_type_by_code(db, data.type_code)
    draft = await _get_status_by_code(db, "draft")

    # Deduplicate and validate employees
    unique_ids = list(dict.fromkeys(data.employee_ids))
    if not unique_ids:
        raise AppError("assessment_no_employees_provided", status.HTTP_400_BAD_REQUEST)

    result = await db.execute(
        select(Employee).where(
            Employee.id.in_(unique_ids), Employee.tenant_id == tenant_id
        )
    )
    found = {e.id for e in result.scalars().all()}
    missing = set(unique_ids) - found
    if missing:
        raise AppError(
            "assessment_employees_not_found",
            status.HTTP_400_BAD_REQUEST,
            employee_ids=[str(m) for m in missing],
        )

    # HRP-37: enforce the per-employee active-assessment cap on Mass
    # Assessment too. Count active rows per assessee and split the input
    # into (eligible / capped) so we can do a partial creation.
    active_by_employee_q = (
        select(Assessment.employee_id, func.count(Assessment.id))
        .join(AssessmentStatus, AssessmentStatus.id == Assessment.status_id)
        .where(
            Assessment.tenant_id == tenant_id,
            Assessment.employee_id.in_(unique_ids),
            AssessmentStatus.code.notin_(TERMINAL_STATUSES),
        )
        .group_by(Assessment.employee_id)
    )
    rows = (await db.execute(active_by_employee_q)).all()
    active_count_by_emp: dict[uuid.UUID, int] = {row[0]: row[1] for row in rows}
    eligible_ids = [
        emp_id
        for emp_id in unique_ids
        if active_count_by_emp.get(emp_id, 0) < MAX_ACTIVE_ASSESSMENTS_PER_EMPLOYEE
    ]
    skipped_count = len(unique_ids) - len(eligible_ids)
    if not eligible_ids:
        raise AppError(
            "assessment_mass_all_employees_capped",
            status.HTTP_409_CONFLICT,
            limit=MAX_ACTIVE_ASSESSMENTS_PER_EMPLOYEE,
        )

    # Create group (still created even on partial — the assessment group
    # is the audit-trail container for the whole batch).
    group = AssessmentGroup(
        tenant_id=tenant_id,
        title=data.title,
        initiator_id=initiator_id,
        specialization_id=data.specialization_id,
        grade_id=data.grade_id,
        scale_id=data.scale_id,
    )
    db.add(group)
    await db.flush()

    # Create individual assessments only for employees with free slots.
    for emp_id in eligible_ids:
        a = Assessment(
            tenant_id=tenant_id,
            title=data.title,
            employee_id=emp_id,
            type_id=atype.id,
            status_id=draft.id,
            specialization_id=data.specialization_id,
            grade_id=data.grade_id,
            scale_id=data.scale_id,
            initiator_id=initiator_id,
            approver_id=data.approver_id,
            ended_at=data.ended_at,
            group_id=group.id,
        )
        db.add(a)
        await db.flush()
        await _auto_assign_self(db, a.id, emp_id)
        if atype.code in ("180", "360"):
            await _auto_assign_manager(db, tenant_id, a.id, emp_id)

    await db.commit()

    result_dict = await get_assessment_group(db, tenant_id, group.id)
    # Surface partial-creation stats so the frontend can render a
    # `Created M of N assessments` snackbar (vs the all-or-nothing
    # success snackbar). Field is optional in the response schema.
    result_dict["created_count"] = len(eligible_ids)
    result_dict["requested_count"] = len(unique_ids)
    result_dict["skipped_capped_count"] = skipped_count
    return result_dict


async def list_assessments_grouped(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    visible_employee_ids: set[uuid.UUID] | None = None,
    participant_user_id: uuid.UUID | None = None,
    restrict_to_active: bool = False,
    search: str | None = None,
    type_codes: list[str] | None = None,
    status_codes: list[str] | None = None,
) -> tuple[list[dict], int]:
    from collections import defaultdict

    # HRP-113: was a per-function `_apply_scope` closure; same predicate as
    # `list_assessments` so it now lives in `apply_assessment_scope`.
    def _apply_scope(query):
        return apply_assessment_scope(
            query,
            visible_employee_ids=visible_employee_ids,
            participant_user_id=participant_user_id,
            restrict_to_active=restrict_to_active,
        )

    is_scoped = visible_employee_ids is not None or restrict_to_active

    # Phase 1: fetch all groups for tenant
    group_result = await db.execute(
        select(AssessmentGroup).where(AssessmentGroup.tenant_id == tenant_id)
    )
    groups = group_result.scalars().all()
    group_ids = [g.id for g in groups]

    # Fetch ALL grouped assessments in a single query (avoids N+1)
    by_group: dict[uuid.UUID, list[Assessment]] = defaultdict(list)
    if group_ids:
        grouped_query = (
            select(Assessment)
            .options(
                selectinload(Assessment.status),
                selectinload(Assessment.assessment_type),
            )
            .where(Assessment.group_id.in_(group_ids))
        )
        grouped_query = _apply_scope(grouped_query)
        grouped_result = await db.execute(grouped_query)
        for a in grouped_result.scalars().all():
            assert a.group_id is not None  # filtered by group_id.in_()
            by_group[a.group_id].append(a)

    # HRP-166: assign a status bucket per item so the merged list sorts
    # active → done → cancelled regardless of whether the row is a group
    # or a single assessment. For groups the bucket comes from the
    # children — active if any child is non-terminal; otherwise done if
    # any child is done (mixed terminal groups land under done), else
    # cancelled. The bucket date matches what the UI surfaces per row:
    # ``created_at`` for active rows, the freshest ``finished_at`` for
    # terminal rows.
    def _group_bucket_and_date(
        children: list[Assessment], group_created_at: datetime
    ) -> tuple[int, datetime]:
        codes = [a.status.code if a.status else "unknown" for a in children]
        any_active = any(c not in TERMINAL_STATUSES for c in codes)
        if any_active or not codes:
            return 0, group_created_at
        if "done" in codes:
            done_dates = [
                a.finished_at
                for a in children
                if a.status and a.status.code == "done" and a.finished_at
            ]
            return 1, max(done_dates) if done_dates else group_created_at
        cancel_dates = [
            a.finished_at
            for a in children
            if a.status and a.status.code == "cancelled" and a.finished_at
        ]
        return 2, max(cancel_dates) if cancel_dates else group_created_at

    group_items = []
    for g in groups:
        children = by_group.get(g.id, [])
        # Hide a group entirely from a scope-restricted caller when none of
        # its assessments survive the filter — otherwise we'd render an empty
        # group card for a regular employee.
        if is_scoped and not children:
            continue
        status_summary: dict[str, int] = {}
        type_code = None
        type_title = None
        for a in children:
            code = a.status.code if a.status else "unknown"
            status_summary[code] = status_summary.get(code, 0) + 1
            if not type_code and a.assessment_type:
                type_code = a.assessment_type.code
                type_title = a.assessment_type.title

        bucket, bucket_date = _group_bucket_and_date(children, g.created_at)
        group_items.append(
            {
                "kind": "group",
                "group": {
                    "id": g.id,
                    "title": g.title,
                    "initiator_id": g.initiator_id,
                    "assessment_count": len(children),
                    "status_summary": status_summary,
                    "type_code": type_code,
                    "type_title": type_title,
                    "created_at": g.created_at,
                },
                "assessment": None,
                "_bucket": bucket,
                "_bucket_date": bucket_date,
            }
        )

    # Phase 2: standalone assessments (no group)
    standalone_query = (
        select(Assessment)
        .options(
            selectinload(Assessment.assessment_type),
            selectinload(Assessment.status),
            selectinload(Assessment.employee),
        )
        .where(Assessment.tenant_id == tenant_id, Assessment.group_id.is_(None))
    )
    standalone_query = _apply_scope(standalone_query)
    standalone_result = await db.execute(standalone_query)
    standalone = standalone_result.scalars().all()

    def _single_bucket_and_date(a: Assessment) -> tuple[int, datetime]:
        code = a.status.code if a.status else "unknown"
        if code == "done":
            return 1, a.finished_at or a.created_at
        if code == "cancelled":
            return 2, a.finished_at or a.created_at
        return 0, a.created_at

    single_items = []
    for a in standalone:
        bucket, bucket_date = _single_bucket_and_date(a)
        single_items.append(
            {
                "kind": "single",
                "assessment": _assessment_to_read(a),
                "group": None,
                "_bucket": bucket,
                "_bucket_date": bucket_date,
            }
        )

    # HRP-193: server-side filtering so the X-Y of N counter and the
    # paginator reflect the filtered slice (the old UI filtered the
    # current page client-side, so a Cancelled-status filter only ever
    # surfaced the cancelled rows that happened to live on the page the
    # user was looking at). The frontend now forwards `search`,
    # `type_codes`, `status_codes` and resets to page 1 on any change.
    search_q = (search or "").strip().lower()
    type_filter = set(type_codes or [])
    status_filter = set(status_codes or [])

    def _matches(item: dict) -> bool:
        if item["kind"] == "single":
            a = item["assessment"]
            if search_q:
                hay = (a.get("title") or "").lower()
                emp = (a.get("employee_name") or "").lower()
                if search_q not in hay and search_q not in emp:
                    return False
            if type_filter and a.get("type_code") not in type_filter:
                return False
            return not (status_filter and a.get("status_code") not in status_filter)
        g = item["group"]
        if search_q and search_q not in (g.get("title") or "").lower():
            return False
        if type_filter and g.get("type_code") not in type_filter:
            return False
        if status_filter:
            summary: dict[str, int] = g.get("status_summary") or {}
            if not any(summary.get(s, 0) > 0 for s in status_filter):
                return False
        return True

    # Merge and sort: bucket asc, then date desc inside each bucket.
    all_items = group_items + single_items
    if search_q or type_filter or status_filter:
        all_items = [item for item in all_items if _matches(item)]
    all_items.sort(key=lambda x: (x["_bucket"], -x["_bucket_date"].timestamp()))

    total = len(all_items)
    page = all_items[skip : skip + limit]

    return [
        {"kind": item["kind"], "assessment": item["assessment"], "group": item["group"]}
        for item in page
    ], total


async def get_assessment_group(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    visible_employee_ids: set[uuid.UUID] | None = None,
    participant_user_id: uuid.UUID | None = None,
    restrict_to_active: bool = False,
) -> dict:
    g = await db.get(AssessmentGroup, group_id)
    if not g or g.tenant_id != tenant_id:
        raise AppError("assessment_group_not_found", status.HTTP_404_NOT_FOUND)

    # HRP-40 follow-up: this endpoint is the lazy-load companion to
    # /assessments-grouped (frontend `assessments/page.tsx` fetches it when
    # a user expands a group card), so it must apply the same scope/Draft
    # filters — otherwise a regular employee can still inspect every child
    # of any group by id. HRP-113: now routed through the shared helper.
    children_query = (
        select(Assessment)
        .options(
            selectinload(Assessment.assessment_type),
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

    result = await db.execute(children_query)
    assessments = result.scalars().all()

    # A scope-restricted caller with no visible child shouldn't be able to
    # confirm the group exists via this endpoint either — mirror the
    # hide-empty-group rule from list_assessments_grouped.
    if (visible_employee_ids is not None or restrict_to_active) and not assessments:
        raise AppError("assessment_group_not_found", status.HTTP_404_NOT_FOUND)

    status_summary: dict[str, int] = {}
    type_code = None
    type_title = None
    for a in assessments:
        code = a.status.code if a.status else "unknown"
        status_summary[code] = status_summary.get(code, 0) + 1
        if not type_code and a.assessment_type:
            type_code = a.assessment_type.code
            type_title = a.assessment_type.title

    # Aggregate criteria competences from any non-terminal child as a representative set
    competences_data: list[dict] = []
    if assessments:
        first = assessments[0]
        comp_q = await db.execute(
            select(AssessmentCompetence).where(
                AssessmentCompetence.assessment_id == first.id
            )
        )
        competences_data = [
            {
                "competence_id": c.competence_id,
                "competence_title": c.competence.title if c.competence else "",
                "skill_level_id": c.skill_level_id,
                "skill_level_title": c.skill_level.title if c.skill_level else None,
                "skill_level_i18n_key": (
                    c.skill_level.i18n_key if c.skill_level else None
                ),
            }
            for c in comp_q.scalars().all()
        ]

    spec_title, grade_title, spec_key, grade_key = await _resolve_dict_titles(
        db, g.specialization_id, g.grade_id
    )
    scale_data = None
    if g.scale_id is not None:
        scale = await _load_scale_full(db, g.scale_id)
        scale_data = await _scale_detail_dict(db, scale) if scale else None
    return {
        "id": g.id,
        "title": g.title,
        "initiator_id": g.initiator_id,
        "assessment_count": len(assessments),
        "status_summary": status_summary,
        "type_code": type_code,
        "type_title": type_title,
        "created_at": g.created_at,
        "assessments": [_assessment_to_read(a) for a in assessments],
        "criteria_type": g.criteria_type,
        "specialization_id": g.specialization_id,
        "specialization_title": spec_title,
        "specialization_i18n_key": spec_key,
        "grade_id": g.grade_id,
        "grade_title": grade_title,
        "grade_i18n_key": grade_key,
        "passing_score": g.passing_score,
        "competences": competences_data,
        "scale_id": g.scale_id,
        "scale": scale_data,
    }


async def update_assessment_group(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    title: str,
) -> dict:
    """Rename a mass assessment and cascade the new title to every child.

    Children inherit the parent title in the UI (the per-child pencil is
    hidden when `group_id` is set), so renaming has to propagate or the
    children are stuck on a stale label.
    """
    g = await db.get(AssessmentGroup, group_id)
    if not g or g.tenant_id != tenant_id:
        raise AppError("assessment_group_not_found", status.HTTP_404_NOT_FOUND)

    new_title = title.strip()
    if not new_title:
        raise AppError("assessment_title_empty", status.HTTP_400_BAD_REQUEST)

    g.title = new_title
    children = await db.execute(
        select(Assessment).where(Assessment.group_id == group_id)
    )
    for child in children.scalars().all():
        child.title = new_title
    await db.commit()
    return await get_assessment_group(db, tenant_id, group_id)


async def bulk_change_status(
    db: AsyncSession, tenant_id: uuid.UUID, group_id: uuid.UUID, new_code: str
) -> dict:
    g = await db.get(AssessmentGroup, group_id)
    if not g or g.tenant_id != tenant_id:
        raise AppError("assessment_group_not_found", status.HTTP_404_NOT_FOUND)

    new_status = await _get_status_by_code(db, new_code)

    result = await db.execute(
        select(Assessment)
        .options(selectinload(Assessment.status))
        .where(Assessment.group_id == group_id)
    )
    assessments = result.scalars().all()

    changed = 0
    skipped = 0
    reasons = {
        "terminal": 0,
        "same_or_lower_status": 0,
        "already_cancelled": 0,
        "missing_criteria_or_scale": 0,
        "deadline_in_past": 0,
        "no_completed_participant": 0,
        "not_in_on_review": 0,
        "manual_in_progress_not_allowed": 0,
    }
    # HRP-84: collected lifecycle events to fan out after the commit.
    pending_notifications: list[tuple[Assessment, str]] = []
    for a in assessments:
        if new_code == "cancelled":
            # Terminal statuses are immutable in bulk-cancel too: "done"
            # children must stay done, "cancelled" children are no-ops.
            # Mass cancel only sweeps assessments that are still in flight.
            if a.status.code == "cancelled":
                skipped += 1
                reasons["already_cancelled"] += 1
                continue
            if a.status.code in TERMINAL_STATUSES:
                skipped += 1
                reasons["terminal"] += 1
                continue
        else:
            # Non-cancel transitions: terminal is locked, sequence must increment
            if a.status.code in TERMINAL_STATUSES:
                skipped += 1
                reasons["terminal"] += 1
                continue
            if new_status.sequence <= a.status.sequence:
                skipped += 1
                reasons["same_or_lower_status"] += 1
                continue
            # Mirror change_status guard: draft → sent needs criteria + scale.
            if (
                a.status.code == "draft"
                and new_code == "sent"
                and (not a.criteria_type or a.scale_id is None)
            ):
                skipped += 1
                reasons["missing_criteria_or_scale"] += 1
                continue
            # HRP-83: same guard as change_status for an expired deadline.
            if (
                a.status.code == "draft"
                and new_code == "sent"
                and _deadline_in_past(a.ended_at)
            ):
                skipped += 1
                reasons["deadline_in_past"] += 1
                continue
            # Manual on_review requires at least one completed participant.
            if new_code == "on_review":
                completed_q = await db.execute(
                    select(func.count())
                    .select_from(AssessmentParticipant)
                    .where(
                        AssessmentParticipant.assessment_id == a.id,
                        AssessmentParticipant.is_completed.is_(True),
                    )
                )
                if (completed_q.scalar() or 0) == 0:
                    skipped += 1
                    reasons["no_completed_participant"] += 1
                    continue
            # Done is reachable only from on_review (mirror change_status).
            if new_code == "done" and a.status.code != "on_review":
                skipped += 1
                reasons["not_in_on_review"] += 1
                continue
            # HRP-192: in_progress is auto-driven only — block bulk too.
            if new_code == "in_progress":
                skipped += 1
                reasons["manual_in_progress_not_allowed"] += 1
                continue
        prev_code = a.status.code
        a.status_id = new_status.id
        a.status = new_status
        if new_code == "sent" and prev_code == "draft" and a.scale_id is not None:
            await snapshot_scale_for_assessment(db, a)
        if new_code == "in_progress" and not a.started_at:
            a.started_at = datetime.now(timezone.utc)
        elif new_code == "on_review":
            await _recompute_assessment_results(db, a)
            # HRP-170: mirror change_status — compute the recommendation
            # at the On Review checkpoint so the chart appears in bulk too.
            from app.modules.assessment.recommendation import (
                compute_grade_recommendation,
            )

            await compute_grade_recommendation(db, tenant_id, a)
        elif new_code == "done":
            a.finished_at = datetime.now(timezone.utc)
            await _recompute_assessment_results(db, a)
            from app.modules.assessment.recommendation import (
                compute_grade_recommendation,
            )

            await compute_grade_recommendation(db, tenant_id, a)
        elif new_code == "cancelled":
            if not a.finished_at:
                # HRP-161: mirror change_status — pin ``finished_at`` on the
                # cancellation transition so the UI can show the closing date.
                a.finished_at = datetime.now(timezone.utc)
            if prev_code == "on_review":
                # HRP-170: refresh the chart cache for an on_review→cancel
                # transition (mirror change_status).
                from app.modules.assessment.recommendation import (
                    compute_grade_recommendation,
                )

                await compute_grade_recommendation(db, tenant_id, a)
        changed += 1
        # HRP-84: queue a lifecycle email per advanced child; dispatch
        # happens after the commit so a delivery failure can't roll back
        # the bulk transition.
        notify_event: str | None = None
        if new_code == "sent" and prev_code == "draft":
            notify_event = "evaluate"
        elif new_code == "done":
            notify_event = "completed"
        elif new_code == "cancelled" and prev_code in (
            "sent",
            "in_progress",
            "on_review",
        ):
            notify_event = "cancelled"
        if notify_event is not None:
            pending_notifications.append((a, notify_event))

    await db.commit()

    for a, event in pending_notifications:
        await _dispatch_lifecycle_emails(db, a, event)

    return {
        "changed": changed,
        "skipped": skipped,
        "total": len(assessments),
        "skipped_reasons": reasons,
    }


# --- CPA ---


def _cpa_to_read(c: CPA) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "author_id": c.author_id,
        "status": c.status,
        "scale_id": c.scale_id,
        "tenant_id": c.tenant_id,
        "started_at": c.started_at,
        "ended_at": c.ended_at,
        "finished_at": c.finished_at,
        "created_at": c.created_at,
    }


async def create_cpa(
    db: AsyncSession, tenant_id: uuid.UUID, author_id: uuid.UUID, data
) -> dict:
    atype = await _get_type_by_code(db, data.type_code)
    cpa = CPA(
        tenant_id=tenant_id,
        title=data.title,
        author_id=author_id,
        type_id=atype.id,
        scale_id=data.scale_id,
        ended_at=data.ended_at,
    )
    db.add(cpa)
    await db.commit()
    await db.refresh(cpa)
    return _cpa_to_read(cpa)


async def list_cpas(db: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    result = await db.execute(
        select(CPA).where(CPA.tenant_id == tenant_id).order_by(CPA.created_at.desc())
    )
    return [_cpa_to_read(c) for c in result.scalars().all()]


async def get_cpa_detail(
    db: AsyncSession, tenant_id: uuid.UUID, cpa_id: uuid.UUID
) -> dict:
    result = await db.execute(
        select(CPA)
        .options(
            selectinload(CPA.criteria),
            selectinload(CPA.participants),
            selectinload(CPA.assessments),
        )
        .where(CPA.id == cpa_id, CPA.tenant_id == tenant_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise AppError("cpa_not_found", status.HTTP_404_NOT_FOUND)

    data = _cpa_to_read(c)
    data["criteria"] = [
        {
            "id": cr.id,
            "cpa_id": cr.cpa_id,
            "criteria_type": cr.criteria_type,
            "config": cr.config,
            "weight": cr.weight,
        }
        for cr in c.criteria
    ]
    # Resolve CPA participant names
    from app.modules.auth.models import User

    user_ids = [p.user_id for p in c.participants]
    users_result = (
        await db.execute(select(User).where(User.id.in_(user_ids)))
        if user_ids
        else None
    )
    users_map = {u.id: u for u in users_result.scalars().all()} if users_result else {}

    data["participants"] = [
        {
            "id": p.id,
            "cpa_id": p.cpa_id,
            "user_id": p.user_id,
            "user_name": _user_full_name(users_map.get(p.user_id)),
            "role": p.role,
        }
        for p in c.participants
    ]
    data["assessment_count"] = len(c.assessments)
    return data


async def add_cpa_criteria(
    db: AsyncSession, tenant_id: uuid.UUID, cpa_id: uuid.UUID, data
) -> dict:
    c = await db.get(CPA, cpa_id)
    if not c or c.tenant_id != tenant_id:
        raise AppError("cpa_not_found", status.HTTP_404_NOT_FOUND)

    cr = CPACriteria(
        cpa_id=cpa_id,
        criteria_type=data.criteria_type,
        config=data.config,
        weight=data.weight,
    )
    db.add(cr)
    await db.commit()
    await db.refresh(cr)
    return {
        "id": cr.id,
        "cpa_id": cr.cpa_id,
        "criteria_type": cr.criteria_type,
        "config": cr.config,
        "weight": cr.weight,
    }


async def add_cpa_participant(
    db: AsyncSession, tenant_id: uuid.UUID, cpa_id: uuid.UUID, data
) -> dict:
    c = await db.get(CPA, cpa_id)
    if not c or c.tenant_id != tenant_id:
        raise AppError("cpa_not_found", status.HTTP_404_NOT_FOUND)

    p = CPAParticipant(cpa_id=cpa_id, user_id=data.user_id, role=data.role)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return {"id": p.id, "cpa_id": p.cpa_id, "user_id": p.user_id, "role": p.role}


async def get_cpa_analytics(
    db: AsyncSession, tenant_id: uuid.UUID, cpa_id: uuid.UUID
) -> dict:
    c = await db.get(CPA, cpa_id)
    if not c or c.tenant_id != tenant_id:
        raise AppError("cpa_not_found", status.HTTP_404_NOT_FOUND)

    # Get all assessments for this CPA
    result = await db.execute(
        select(Assessment)
        .options(selectinload(Assessment.results), selectinload(Assessment.status))
        .where(Assessment.cpa_id == cpa_id)
    )
    assessments = result.scalars().all()

    total = len(assessments)
    completed = sum(
        1 for a in assessments if a.status is not None and a.status.code == "done"
    )

    # Resolve employee names for ranking
    from app.modules.employee.models import Employee

    emp_ids = list({a.employee_id for a in assessments})
    emp_map: dict[uuid.UUID, str | None] = {}
    if emp_ids:
        emp_result = await db.execute(select(Employee).where(Employee.id.in_(emp_ids)))
        for emp in emp_result.scalars().all():
            emp_map[emp.id] = _employee_name(emp)

    # Build ranking by average score
    ranking = []
    score_buckets: dict[str, int] = {}
    for a in assessments:
        if not a.results:
            continue
        scores: list[float] = [
            r.calibrated_score if r.calibrated_score is not None else r.avg_score
            for r in a.results
        ]
        if scores:
            avg = sum(scores) / len(scores)
            ranking.append(
                {
                    "employee_id": a.employee_id,
                    "employee_name": emp_map.get(a.employee_id),
                    "assessment_id": a.id,
                    "avg_score": round(avg, 2),
                    "rank": 0,
                }
            )
            bucket = str(int(avg))
            score_buckets[bucket] = score_buckets.get(bucket, 0) + 1

    # Sort and assign ranks
    ranking.sort(
        key=lambda x: float(x.get("avg_score", 0)),  # type: ignore[arg-type]
        reverse=True,
    )
    for i, item in enumerate(ranking):
        item["rank"] = i + 1

    return {
        "cpa_id": cpa_id,
        "total_assessments": total,
        "completed_assessments": completed,
        "ranking": ranking,
        "score_distribution": score_buckets,
    }


async def copy_cpa(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    author_id: uuid.UUID,
    source_cpa_id: uuid.UUID,
    new_title: str,
) -> dict:
    """Create a new CPA by copying template from an existing one."""
    result = await db.execute(
        select(CPA)
        .options(selectinload(CPA.criteria), selectinload(CPA.participants))
        .where(CPA.id == source_cpa_id, CPA.tenant_id == tenant_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise AppError("source_cpa_not_found", status.HTTP_404_NOT_FOUND)

    new_cpa = CPA(
        tenant_id=tenant_id,
        title=new_title,
        author_id=author_id,
        type_id=source.type_id,
        scale_id=source.scale_id,
    )
    db.add(new_cpa)
    await db.flush()

    # Copy criteria
    for cr in source.criteria:
        db.add(
            CPACriteria(
                cpa_id=new_cpa.id,
                criteria_type=cr.criteria_type,
                config=cr.config,
                weight=cr.weight,
            )
        )

    # Copy participant roles
    for p in source.participants:
        db.add(
            CPAParticipant(
                cpa_id=new_cpa.id,
                user_id=p.user_id,
                role=p.role,
            )
        )

    await db.commit()
    await db.refresh(new_cpa)
    return _cpa_to_read(new_cpa)


# ---------------------------------------------------------------------------
# GF4: External Reviewers
# ---------------------------------------------------------------------------

EXTERNAL_LINK_EXPIRE_DAYS = 30


def _external_reviewer_to_read(er: ExternalReviewer) -> dict:
    return {
        "id": er.id,
        "assessment_id": er.assessment_id,
        "token": er.token,
        "name": er.name,
        "email": er.email,
        "expires_at": er.expires_at,
        "completed_at": er.completed_at,
        "share_url": f"/review/{er.token}",
        "created_at": er.created_at,
    }


async def create_external_reviewer(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment_id: uuid.UUID,
    name: str | None,
    email: str | None,
    role: str = "external",
) -> dict:
    a = await db.get(Assessment, assessment_id)
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)

    token = secrets.token_urlsafe(32)
    er = ExternalReviewer(
        assessment_id=assessment_id,
        tenant_id=tenant_id,
        token=token,
        name=name,
        email=email,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=EXTERNAL_LINK_EXPIRE_DAYS),
    )
    db.add(er)
    await db.flush()

    # Create matching participant entry
    p = AssessmentParticipant(
        assessment_id=assessment_id,
        user_id=None,
        external_reviewer_id=er.id,
        role=role,
    )
    db.add(p)
    await db.commit()
    await db.refresh(er)

    # Send email notification if email provided
    if email:
        try:
            from app.core.email import enqueue_email
            from app.core.email_templates import render_external_review_email
            from app.core.i18n import format_date, resolve_locale
            from app.modules.company.models import Tenant

            # i18n F4: the invitee has no account yet, so the tenant
            # default is the whole chain for them.
            tenant = await db.get(Tenant, tenant_id)
            locale = resolve_locale(
                tenant_default=tenant.default_locale if tenant else None
            )
            deadline = format_date(er.expires_at, locale) if er.expires_at else None
            subj, body = render_external_review_email(
                token, a.title or "", deadline, locale=locale
            )
            enqueue_email(
                email,
                subj,
                body,
                tenant_id=str(tenant_id),
                template_code="assessment.external_review_invite",
            )
        except Exception:  # noqa: BLE001 - invite email is best-effort
            logger.warning(
                "External review invite email failed for assessment %s",
                assessment_id,
                exc_info=True,
            )

    return _external_reviewer_to_read(er)


async def list_external_reviewers(
    db: AsyncSession, tenant_id: uuid.UUID, assessment_id: uuid.UUID
) -> list[dict]:
    a = await db.get(Assessment, assessment_id)
    if not a or a.tenant_id != tenant_id:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)

    result = await db.execute(
        select(ExternalReviewer)
        .where(ExternalReviewer.assessment_id == assessment_id)
        .order_by(ExternalReviewer.created_at.desc())
    )
    return [_external_reviewer_to_read(er) for er in result.scalars().all()]


async def delete_external_reviewer(
    db: AsyncSession, tenant_id: uuid.UUID, reviewer_id: uuid.UUID
) -> dict:
    er = await db.get(ExternalReviewer, reviewer_id)
    if not er or er.tenant_id != tenant_id:
        raise AppError("external_reviewer_not_found", status.HTTP_404_NOT_FOUND)

    # Also remove participant
    result = await db.execute(
        select(AssessmentParticipant).where(
            AssessmentParticipant.external_reviewer_id == er.id
        )
    )
    participant = result.scalar_one_or_none()
    if participant:
        await db.delete(participant)

    data = _external_reviewer_to_read(er)
    await db.delete(er)
    await db.commit()
    return data


async def get_external_assessment(db: AsyncSession, token: str) -> dict:
    """Get assessment info for external reviewer (no auth required)."""
    result = await db.execute(
        select(ExternalReviewer).where(ExternalReviewer.token == token)
    )
    er = result.scalar_one_or_none()
    if not er:
        raise AppError("external_review_link_invalid", status.HTTP_404_NOT_FOUND)
    if er.expires_at < datetime.now(timezone.utc):
        raise AppError("external_review_link_expired", status.HTTP_400_BAD_REQUEST)
    if er.completed_at:
        raise AppError("external_review_already_completed", status.HTTP_400_BAD_REQUEST)

    a = await db.execute(
        select(Assessment)
        .options(
            selectinload(Assessment.assessment_type),
            selectinload(Assessment.competences),
        )
        .where(Assessment.id == er.assessment_id)
    )
    assessment = a.scalar_one()

    # Get competences with indicators
    from app.modules.competence.models import Competence, Indicator

    competences_data = []
    for ac in assessment.competences:
        comp = await db.get(Competence, ac.competence_id)
        if not comp:
            continue
        indicators_result = await db.execute(
            select(Indicator).where(
                Indicator.competence_id == comp.id,
                Indicator.is_active == True,  # noqa: E712
            )
        )
        indicators = [
            {"id": ind.id, "title": ind.title, "weight": ind.weight}
            for ind in indicators_result.scalars().all()
        ]
        competences_data.append(
            {
                "id": comp.id,
                "title": comp.title,
                "indicators": indicators,
            }
        )

    # Get scale if set
    scale_data = None
    if assessment.scale_id:
        scale = await db.execute(
            select(AnswerScale)
            .options(selectinload(AnswerScale.options))
            .where(AnswerScale.id == assessment.scale_id)
        )
        s = scale.scalar_one_or_none()
        if s:
            scale_data = {
                "id": s.id,
                "title": s.title,
                "description": s.description,
                "i18n_key": s.i18n_key,
                "tenant_id": s.tenant_id,
                "is_default": s.is_default,
                "options": [
                    {
                        "id": o.id,
                        "title": o.title,
                        "code": o.code,
                        "weight": o.weight,
                        "description": o.description,
                        "sort_index": o.sort_index,
                        "is_neutral": o.is_neutral,
                    }
                    for o in s.options
                ],
            }

    # Get employee name (anonymized: first name + last initial)
    employee_name = None
    if assessment.employee_id:
        from app.modules.employee.models import Employee

        emp = await db.get(Employee, assessment.employee_id)
        if emp and emp.user:
            employee_name = f"{emp.user.first_name} {emp.user.last_name[0]}."

    return {
        "assessment_id": assessment.id,
        "employee_name": employee_name,
        "type_title": assessment.assessment_type.title,
        # HRP-479: stable code so a future external-review UI can localize.
        "type_code": assessment.assessment_type.code,
        "competences": competences_data,
        "scale": scale_data,
    }


async def submit_external_answers(db: AsyncSession, token: str, answers: list) -> dict:
    """Submit answers from external reviewer (no auth required)."""
    result = await db.execute(
        select(ExternalReviewer).where(ExternalReviewer.token == token)
    )
    er = result.scalar_one_or_none()
    if not er:
        raise AppError("external_review_link_invalid", status.HTTP_404_NOT_FOUND)
    if er.expires_at < datetime.now(timezone.utc):
        raise AppError("external_review_link_expired", status.HTTP_400_BAD_REQUEST)
    if er.completed_at:
        raise AppError("external_review_already_completed", status.HTTP_400_BAD_REQUEST)

    # HRP-185 / HRP-329: refuse submission while the assessment is being
    # calibrated — or after a calibration was saved.
    a = await db.get(Assessment, er.assessment_id)
    if a is not None:
        await _assert_not_calibration_locked(db, a)

    # Find participant
    p_result = await db.execute(
        select(AssessmentParticipant).where(
            AssessmentParticipant.external_reviewer_id == er.id
        )
    )
    participant = p_result.scalar_one_or_none()
    if not participant:
        raise AppError(
            "assessment_participant_record_not_found", status.HTTP_400_BAD_REQUEST
        )

    # Record all answers
    for ans in answers:
        answer = AssessmentAnswer(
            assessment_id=er.assessment_id,
            participant_id=participant.id,
            indicator_id=ans.indicator_id,
            answer_option_id=ans.answer_option_id,
            score=ans.score,
            comment=ans.comment,
        )
        db.add(answer)

    # Mark as completed
    participant.is_completed = True
    er.completed_at = datetime.now(timezone.utc)
    await db.flush()

    # HRP-145: keep preliminary results in sync with the new survey.
    # When every participant has finished this flips in_progress →
    # on_review with a fresh recompute; when the assessment is already
    # in on_review (manual move with subset done), it just refreshes
    # Avg Score so the external reviewer's submission shows up.
    await _maybe_auto_move_to_on_review(db, er.assessment_id)
    await db.commit()

    return {"status": "completed", "answers_count": len(answers)}
