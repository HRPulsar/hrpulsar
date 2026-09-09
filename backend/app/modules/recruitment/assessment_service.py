"""Candidate assessments: question CRUD + PDF export, human assessment
scores with optimistic locking (HRP-266 versions/revert), assessment
invites (public token flow), canvas API and the compact assessment
matrix (HRP-265).

Split out of ``service.py`` (project-review #7); see ``service.py`` for
the delegating namespace.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from fastapi import Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.modules.auth.models import User
from app.modules.recruitment import audit_service
from app.modules.recruitment.common import (
    _get_candidate,
    _get_vacancy,
    _publish_event,
    candidate_display_name,
    normalize_competence_id,
)
from app.modules.recruitment.models import (
    AIAnalysisRun,
    AIAssessment,
    AssessmentInvite,
    Candidate,
    CandidateFile,
    CandidateQuestion,
    CandidateVacancy,
    HumanAssessment,
    Interview,
    RecruitmentAuditLog,
    Vacancy,
    VacancyProfile,
)
from app.modules.recruitment.schemas import (
    AssessmentScoreCreate,
    AssessmentScoreUpdate,
    InviteCreate,
    QuestionCreate,
    QuestionUpdate,
)
from app.modules.recruitment.score_normalization import compute_normalized_ai_score
from app.modules.storage.models import File

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Candidate Questions CRUD
# ---------------------------------------------------------------------------


def _question_to_read(q: CandidateQuestion) -> dict:
    return {
        "id": q.id,
        "candidate_id": q.candidate_id,
        "vacancy_id": q.vacancy_id,
        "competence_id": q.competence_id,
        "question_text": q.question_text,
        "good_answer": q.good_answer,
        "acceptable_answer": q.acceptable_answer,
        "poor_answer": q.poor_answer,
        "resume_fragment": q.resume_fragment,
        "purpose": q.purpose,
        "priority": q.priority,
        "is_manual": q.is_manual,
        "sort_order": q.sort_order,
        "created_at": q.created_at,
    }


async def export_questions_pdf(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    *,
    include_good: bool = True,
    include_acceptable: bool = True,
    include_poor: bool = True,
) -> bytes:
    """Render the candidate's question bank for a vacancy as PDF (FR-13/SCR-65)."""
    from app.modules.recruitment.pdf_export import export_questions_pdf as _render

    return await _render(
        db,
        tenant_id,
        candidate_id,
        vacancy_id,
        include_good=include_good,
        include_acceptable=include_acceptable,
        include_poor=include_poor,
    )


async def list_questions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    vacancy_id: uuid.UUID | None = None,
) -> list[dict]:
    """List questions for a candidate, optionally filtered by vacancy."""
    query = select(CandidateQuestion).where(
        CandidateQuestion.candidate_id == candidate_id,
        CandidateQuestion.tenant_id == tenant_id,
    )
    if vacancy_id:
        query = query.where(CandidateQuestion.vacancy_id == vacancy_id)

    result = await db.execute(query.order_by(CandidateQuestion.sort_order))
    return [_question_to_read(q) for q in result.scalars().all()]


async def add_question(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    data: QuestionCreate,
) -> dict:
    """Add a manual question to candidate's question bank."""
    await _get_candidate(db, tenant_id, candidate_id)
    await _get_vacancy(db, tenant_id, vacancy_id)

    q = CandidateQuestion(
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        vacancy_id=vacancy_id,
        competence_id=data.competence_id,
        question_text=data.question_text,
        good_answer=data.good_answer,
        acceptable_answer=data.acceptable_answer,
        poor_answer=data.poor_answer,
        resume_fragment=data.resume_fragment,
        purpose=data.purpose,
        priority=data.priority,
        is_manual=True,
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return _question_to_read(q)


async def update_question(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    question_id: uuid.UUID,
    data: QuestionUpdate,
) -> dict:
    """Update a candidate question."""
    result = await db.execute(
        select(CandidateQuestion).where(
            CandidateQuestion.id == question_id,
            CandidateQuestion.tenant_id == tenant_id,
        )
    )
    q = result.scalar_one_or_none()
    if not q:
        raise AppError("question_not_found", status.HTTP_404_NOT_FOUND)

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(q, field, value)
    await db.commit()
    await db.refresh(q)
    return _question_to_read(q)


async def delete_question(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    question_id: uuid.UUID,
) -> None:
    """Delete a candidate question."""
    result = await db.execute(
        select(CandidateQuestion).where(
            CandidateQuestion.id == question_id,
            CandidateQuestion.tenant_id == tenant_id,
        )
    )
    q = result.scalar_one_or_none()
    if not q:
        raise AppError("question_not_found", status.HTTP_404_NOT_FOUND)
    await db.delete(q)
    await db.commit()


# ---------------------------------------------------------------------------
# Human Assessments (scores)
# ---------------------------------------------------------------------------


def assessment_etag(version: int) -> str:
    """Weak ETag for HumanAssessment rows (HRP-266 conflict resolution).

    The matching ``If-Match`` value lets concurrent writers race-detect
    via standard HTTP semantics: a stale token from a second editor lands
    a 412 instead of silently overwriting the first editor's score.
    """
    return f'W/"{version}"'


def parse_assessment_if_match(header: str | None) -> int | None:
    """Extract the integer version embedded in a W/"N" ETag.

    Returns ``None`` when the header is missing — the upstream
    ``record_human_assessment`` then treats the call as "I have no idea
    what's already there", which is appropriate for the initial insert.
    Returns ``None`` for malformed values too; the caller's matching
    logic then refuses to upsert without a fresh GET, surfacing the
    inconsistency rather than guessing.

    Strictly strips a single ``W/`` prefix (RFC 7232 §2.3 weak ETag) —
    a character-set ``lstrip`` would also accept malformed inputs like
    ``W5`` or ``///"5"``, which is exactly the kind of slop a future
    fuzzer would pick on.
    """
    if not header:
        return None
    cleaned = header.strip()
    cleaned = cleaned.removeprefix("W/")
    cleaned = cleaned.strip().strip('"')
    if not cleaned.isdigit():
        return None
    return int(cleaned)


def _assessment_payload_diff(
    *,
    cv_id: uuid.UUID,
    competence_id: uuid.UUID,
    evaluator_id: uuid.UUID | None,
    invite_id: uuid.UUID | None,
    old_score: float | None,
    new_score: float | None,
    old_comment: str | None,
    new_comment: str | None,
    new_version: int,
    operation: str,
    extra: dict | None = None,
) -> dict:
    """Build the audit-log payload that the Versions panel reads back.

    The Versions timeline groups by ``(cv_id, competence_id, evaluator_id
    || invite_id)`` and renders ``old_score → new_score``; ``operation``
    distinguishes ``upsert`` / ``update`` / ``revert`` so the UI can
    label the entry. ``extra`` is merged in so revert can stash a
    pointer back to the source event without bending the schema.
    """
    payload: dict = {
        "candidate_vacancy_id": str(cv_id),
        "competence_id": str(competence_id),
        "evaluator_id": str(evaluator_id) if evaluator_id else None,
        "invite_id": str(invite_id) if invite_id else None,
        "old_score": old_score,
        "new_score": new_score,
        "old_comment": old_comment,
        "new_comment": new_comment,
        "version": new_version,
        "operation": operation,
    }
    if extra:
        payload.update(extra)
    return payload


async def record_human_assessment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
    evaluator_id: uuid.UUID,
    data: AssessmentScoreCreate,
    *,
    if_match: str | None = None,
    initiator_id: uuid.UUID | None = None,
    request: Request | None = None,
) -> dict:
    """Record or update a human assessment score for a competency.

    Last-write-wins per evaluator per competency. If score already exists
    for this evaluator+competency, increment version. When ``if_match``
    is supplied the function refuses to overwrite a stale snapshot —
    callers caught a 412 must refresh and prompt the user.
    """
    # Verify cv belongs to tenant
    cv_result = await db.execute(
        select(CandidateVacancy).where(
            CandidateVacancy.id == cv_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
    )
    if not cv_result.scalar_one_or_none():
        raise AppError("candidate_vacancy_link_not_found", status.HTTP_404_NOT_FOUND)

    # SELECT FOR UPDATE serialises concurrent writers on the same
    # (cv, competence, evaluator) triple — without it two callers both
    # holding the same If-Match snapshot race past the version check.
    existing_result = await db.execute(
        select(HumanAssessment)
        .where(
            HumanAssessment.candidate_vacancy_id == cv_id,
            HumanAssessment.competence_id == data.competence_id,
            HumanAssessment.evaluator_id == evaluator_id,
            HumanAssessment.tenant_id == tenant_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    existing = existing_result.scalar_one_or_none()

    expected_version = parse_assessment_if_match(if_match)

    if existing:
        # ETag 412 — caller saw version N but DB advanced past it.
        if expected_version is not None and expected_version != existing.version:
            raise AppError(
                "assessment_stale_version",
                status.HTTP_412_PRECONDITION_FAILED,
                expected=expected_version,
                current=existing.version,
            )
        old_score = existing.score
        old_comment = existing.comment
        existing.score = data.score
        existing.comment = data.comment
        existing.version = existing.version + 1
        await db.commit()
        await db.refresh(existing)
        await audit_service.record_event(
            db,
            tenant_id=tenant_id,
            user_id=initiator_id or evaluator_id,
            action="assessment.update",
            entity_type="assessment",
            entity_id=existing.id,
            payload_diff=_assessment_payload_diff(
                cv_id=cv_id,
                competence_id=data.competence_id,
                evaluator_id=evaluator_id,
                invite_id=existing.invite_id,
                old_score=old_score,
                new_score=existing.score,
                old_comment=old_comment,
                new_comment=existing.comment,
                new_version=existing.version,
                operation="update",
            ),
            request=request,
        )
        return _assessment_to_read(existing)

    # First write — refuse a stale precondition (e.g. another writer
    # raced and inserted between the caller's GET and POST).
    if expected_version is not None:
        raise AppError(
            "assessment_created_by_another_writer",
            status.HTTP_412_PRECONDITION_FAILED,
            expected=expected_version,
        )

    ha = HumanAssessment(
        tenant_id=tenant_id,
        candidate_vacancy_id=cv_id,
        competence_id=data.competence_id,
        evaluator_id=evaluator_id,
        score=data.score,
        comment=data.comment,
        version=1,
    )
    db.add(ha)
    await db.commit()
    await db.refresh(ha)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=initiator_id or evaluator_id,
        action="assessment.create",
        entity_type="assessment",
        entity_id=ha.id,
        payload_diff=_assessment_payload_diff(
            cv_id=cv_id,
            competence_id=data.competence_id,
            evaluator_id=evaluator_id,
            invite_id=None,
            old_score=None,
            new_score=ha.score,
            old_comment=None,
            new_comment=ha.comment,
            new_version=ha.version,
            operation="upsert",
        ),
        request=request,
    )
    return _assessment_to_read(ha)


async def update_human_assessment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assessment_id: uuid.UUID,
    data: AssessmentScoreUpdate,
    *,
    if_match: str | None = None,
    initiator_id: uuid.UUID | None = None,
    request: Request | None = None,
) -> dict:
    """Update an existing human assessment score (PATCH per cell).

    ``initiator_id`` is the actor performing the edit (admin / recruiter
    overriding someone else's score); when missing the audit row falls
    back to the original evaluator so legacy callers still emit a sane
    user_id, but new callers SHOULD pass current_user.id explicitly so
    the Versions panel attributes the change to the real editor.

    The SELECT FOR UPDATE makes the version check atomic with the
    subsequent UPDATE — without it two writers holding the same expected
    version race past the precondition and both write version+1 (memory
    ``feedback_sqlalchemy_race_fix``).
    """
    result = await db.execute(
        select(HumanAssessment)
        .where(
            HumanAssessment.id == assessment_id,
            HumanAssessment.tenant_id == tenant_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    ha = result.scalar_one_or_none()
    if not ha:
        raise AppError("assessment_not_found", status.HTTP_404_NOT_FOUND)

    expected_version = parse_assessment_if_match(if_match)
    if expected_version is not None and expected_version != ha.version:
        raise AppError(
            "assessment_stale_version",
            status.HTTP_412_PRECONDITION_FAILED,
            expected=expected_version,
            current=ha.version,
        )

    old_score = ha.score
    old_comment = ha.comment
    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(ha, field, value)
    ha.version = ha.version + 1
    await db.commit()
    await db.refresh(ha)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=initiator_id or ha.evaluator_id,
        action="assessment.update",
        entity_type="assessment",
        entity_id=ha.id,
        payload_diff=_assessment_payload_diff(
            cv_id=ha.candidate_vacancy_id,
            competence_id=ha.competence_id,
            evaluator_id=ha.evaluator_id,
            invite_id=ha.invite_id,
            old_score=old_score,
            new_score=ha.score,
            old_comment=old_comment,
            new_comment=ha.comment,
            new_version=ha.version,
            operation="update",
        ),
        request=request,
    )
    return _assessment_to_read(ha)


async def revert_human_assessment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
    competence_id: uuid.UUID,
    evaluator_id: uuid.UUID,
    audit_event_id: uuid.UUID,
    *,
    initiator_id: uuid.UUID,
    if_match: str | None = None,
    request: Request | None = None,
) -> dict:
    """Restore an evaluator's cell to the ``old_score`` recorded by an
    earlier audit event (HRP-266 Versions panel Revert button).

    Only Manager-side cells are revertible: AI scores are recomputed by
    the analysis pipeline, never edited manually. The audit event must
    belong to the same tenant and reference the same (cv, competence,
    evaluator) triple — otherwise we 404 to avoid revealing other
    tenants' history shapes. Pass ``if_match`` to refuse the revert when
    the cell advanced between the Versions panel render and the click.
    """
    audit_row = (
        await db.execute(
            select(RecruitmentAuditLog).where(
                RecruitmentAuditLog.id == audit_event_id,
                RecruitmentAuditLog.tenant_id == tenant_id,
                # Defence in depth: a sibling recruitment module that
                # happens to emit candidate_vacancy_id / competence_id
                # in its payload could otherwise be nominated as a
                # revert source, breaking timeline coherence even when
                # the eventual mutation succeeds.
                RecruitmentAuditLog.entity_type == "assessment",
                RecruitmentAuditLog.action.in_(
                    [
                        "assessment.create",
                        "assessment.update",
                        "assessment.revert",
                    ]
                ),
            )
        )
    ).scalar_one_or_none()
    if audit_row is None:
        raise AppError("audit_event_not_found", status.HTTP_404_NOT_FOUND)
    payload = audit_row.payload_diff or {}
    # Spec: revert only applies to Manager-side cells. Invite-only audit
    # rows (no evaluator_id) are surfaced for context but cannot be
    # restored — the invitee owns their submission. This guard runs
    # BEFORE the (cv, comp, evaluator) match so the user gets the right
    # message instead of a generic 404 hiding the real reason.
    if payload.get("evaluator_id") is None:
        raise AppError(
            "assessment_invited_scores_not_revertible",
            status.HTTP_409_CONFLICT,
        )
    if (
        payload.get("candidate_vacancy_id") != str(cv_id)
        or payload.get("competence_id") != str(competence_id)
        or payload.get("evaluator_id") != str(evaluator_id)
    ):
        raise AppError("audit_event_cell_mismatch", status.HTTP_404_NOT_FOUND)

    target_score = payload.get("old_score")
    target_comment = payload.get("old_comment")

    # FOR UPDATE serialises the read-modify-write so two concurrent
    # reverts (or a revert racing a regular update) cannot both pass the
    # ETag check and silently clobber each other.
    existing = (
        await db.execute(
            select(HumanAssessment)
            .where(
                HumanAssessment.candidate_vacancy_id == cv_id,
                HumanAssessment.competence_id == competence_id,
                HumanAssessment.evaluator_id == evaluator_id,
                HumanAssessment.tenant_id == tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()

    expected_version = parse_assessment_if_match(if_match)
    if (
        existing is not None
        and expected_version is not None
        and expected_version != existing.version
    ):
        raise AppError(
            "assessment_stale_version_snapshot",
            status.HTTP_412_PRECONDITION_FAILED,
            expected=expected_version,
            current=existing.version,
        )

    if existing is None:
        if expected_version is not None:
            raise AppError(
                "assessment_removed_since_snapshot",
                status.HTTP_412_PRECONDITION_FAILED,
            )
        # Revert-to-nothing on a row that has since been cleared is a
        # no-op; revert-to-score creates a fresh entry attributed to the
        # initiator. Either way we get a clean audit trail of the action.
        if target_score is None:
            raise AppError("assessment_nothing_to_revert", status.HTTP_409_CONFLICT)
        existing = HumanAssessment(
            tenant_id=tenant_id,
            candidate_vacancy_id=cv_id,
            competence_id=competence_id,
            evaluator_id=evaluator_id,
            score=target_score,
            comment=target_comment,
            version=1,
        )
        db.add(existing)
        pre_revert_score = None
        pre_revert_comment = None
    else:
        # Capture the *actual* current score so the audit row reflects
        # what changed on this DB ("5 → 2"), not what the source event
        # said ("3 → 2"). Without this the Versions timeline is
        # internally inconsistent whenever an intermediate edit landed
        # between the source event and the revert.
        pre_revert_score = existing.score
        pre_revert_comment = existing.comment
        existing.score = target_score
        existing.comment = target_comment
        existing.version = existing.version + 1

    await db.commit()
    await db.refresh(existing)
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=initiator_id,
        action="assessment.revert",
        entity_type="assessment",
        entity_id=existing.id,
        payload_diff=_assessment_payload_diff(
            cv_id=cv_id,
            competence_id=competence_id,
            evaluator_id=evaluator_id,
            invite_id=existing.invite_id,
            old_score=pre_revert_score,
            new_score=target_score,
            old_comment=pre_revert_comment,
            new_comment=target_comment,
            new_version=existing.version,
            operation="revert",
            extra={"reverted_from_event_id": str(audit_event_id)},
        ),
        request=request,
    )
    return _assessment_to_read(existing)


async def list_assessment_history(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    *,
    evaluator_id: uuid.UUID | None = None,
    candidate_vacancy_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    only_divergence: bool = False,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[dict], int]:
    """Audit timeline of assessment writes scoped to one vacancy.

    Source-of-truth is ``recruitment_audit_log``; rows are emitted by
    record/update/revert_human_assessment with structured payload_diff
    so the Versions panel can render ``old_score → new_score`` and
    offer Revert without joining HumanAssessment row-by-row.

    Filters mirror the spec: per-evaluator, per-candidate (via
    candidate_vacancy_id), date range, and "only divergence-triggering"
    edits where the absolute gap from the previous score crosses the
    tenant's divergence threshold.
    """
    await _get_vacancy(db, tenant_id, vacancy_id)

    cv_ids_subquery = (
        (
            await db.execute(
                select(CandidateVacancy.id).where(
                    CandidateVacancy.vacancy_id == vacancy_id,
                    CandidateVacancy.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    cv_ids_str = {str(cv_id) for cv_id in cv_ids_subquery}
    if not cv_ids_str:
        return [], 0

    filters = [
        RecruitmentAuditLog.tenant_id == tenant_id,
        RecruitmentAuditLog.entity_type == "assessment",
        RecruitmentAuditLog.action.in_(
            ["assessment.create", "assessment.update", "assessment.revert"]
        ),
    ]
    if since is not None:
        filters.append(RecruitmentAuditLog.created_at >= since)
    if until is not None:
        filters.append(RecruitmentAuditLog.created_at <= until)

    query = (
        select(RecruitmentAuditLog).where(*filters)
        # ``id`` tiebreaker keeps two events written in the same
        # transaction in a stable order across reloads — without it the
        # Versions panel reorders rows depending on the SQL execution
        # plan, which makes screenshots / tests flaky.
        .order_by(
            RecruitmentAuditLog.created_at.desc(),
            RecruitmentAuditLog.id.desc(),
        )
    )

    rows = (await db.execute(query)).scalars().all()

    # Apply vacancy / evaluator / candidate filters in Python — payload_diff
    # is a JSONB blob and indexing JSONB extractors per filter is more
    # operational complexity than this view warrants today.
    threshold = None
    if only_divergence:
        from app.modules.recruitment import settings_service as _settings

        threshold = await _settings.get_divergence_threshold(db, tenant_id)

    filtered: list[RecruitmentAuditLog] = []
    for row in rows:
        payload = row.payload_diff or {}
        cv_str = payload.get("candidate_vacancy_id")
        if cv_str not in cv_ids_str:
            continue
        if candidate_vacancy_id is not None and cv_str != str(candidate_vacancy_id):
            continue
        ev_str = payload.get("evaluator_id")
        if evaluator_id is not None and ev_str != str(evaluator_id):
            continue
        if only_divergence and threshold is not None:
            old = payload.get("old_score")
            new = payload.get("new_score")
            if old is None or new is None:
                continue
            if abs(float(new) - float(old)) < threshold:
                continue
        filtered.append(row)

    total = len(filtered)
    page = filtered[skip : skip + limit]

    user_ids = {row.user_id for row in page if row.user_id is not None}
    users: dict[uuid.UUID, User] = {}
    if user_ids:
        u_result = await db.execute(
            select(User).where(User.id.in_(user_ids), User.tenant_id == tenant_id)
        )
        users = {u.id: u for u in u_result.scalars().all()}

    items: list[dict] = []
    for row in page:
        user = users.get(row.user_id) if row.user_id else None
        payload = row.payload_diff or {}
        items.append(
            {
                "id": row.id,
                "action": row.action,
                "operation": payload.get("operation"),
                "candidate_vacancy_id": payload.get("candidate_vacancy_id"),
                "competence_id": payload.get("competence_id"),
                "evaluator_id": payload.get("evaluator_id"),
                "invite_id": payload.get("invite_id"),
                "user_id": row.user_id,
                "user_name": (
                    (
                        f"{user.first_name or ''} {user.last_name or ''}".strip()
                        or (user.email if user else None)
                    )
                    if user
                    else None
                ),
                "old_score": payload.get("old_score"),
                "new_score": payload.get("new_score"),
                "old_comment": payload.get("old_comment"),
                "new_comment": payload.get("new_comment"),
                "version": payload.get("version"),
                "reverted_from_event_id": payload.get("reverted_from_event_id"),
                "created_at": row.created_at,
            }
        )
    return items, total


async def list_assessments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
) -> list[dict]:
    """List all human assessment scores for a candidate-vacancy link."""
    result = await db.execute(
        select(HumanAssessment).where(
            HumanAssessment.candidate_vacancy_id == cv_id,
            HumanAssessment.tenant_id == tenant_id,
        )
    )
    return [_assessment_to_read(ha) for ha in result.scalars().all()]


def _assessment_to_read(ha: HumanAssessment) -> dict:
    return {
        "id": ha.id,
        "candidate_vacancy_id": ha.candidate_vacancy_id,
        "competence_id": ha.competence_id,
        "evaluator_id": ha.evaluator_id,
        "evaluator_name": ha.evaluator_name,
        "invite_id": ha.invite_id,
        "score": ha.score,
        "comment": ha.comment,
        "version": ha.version,
        "created_at": ha.created_at,
        "updated_at": ha.updated_at,
    }


# ---------------------------------------------------------------------------
# Assessment Invites
# ---------------------------------------------------------------------------


async def create_assessment_invite(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
    data: InviteCreate,
) -> dict:
    """Create invite link for an external evaluator and email it (FR-20)."""
    import logging
    import secrets

    logger = logging.getLogger(__name__)

    result = await db.execute(
        select(CandidateVacancy)
        .options(
            selectinload(CandidateVacancy.candidate).selectinload(Candidate.person),
            selectinload(CandidateVacancy.vacancy),
        )
        .where(
            CandidateVacancy.id == cv_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
    )
    cv = result.scalar_one_or_none()
    if not cv:
        raise AppError("candidate_vacancy_link_not_found", status.HTTP_404_NOT_FOUND)

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_in_days)

    invite = AssessmentInvite(
        tenant_id=tenant_id,
        candidate_vacancy_id=cv_id,
        token=token,
        email=data.email,
        evaluator_name=data.evaluator_name,
        status="pending",
        expires_at=expires_at,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    try:
        from app.core.email import enqueue_email
        from app.core.email_templates import render_recruitment_invite_email
        from app.core.i18n import resolve_locale, translate
        from app.modules.company.models import Tenant

        vacancy_title = cv.vacancy.title if cv.vacancy else None
        # i18n F4: the external evaluator has no account, so the tenant
        # default is the only locale signal for this recipient.
        tenant = await db.get(Tenant, tenant_id)
        locale = resolve_locale(
            tenant_default=tenant.default_locale if tenant else None
        )
        candidate_name = candidate_display_name(
            cv.candidate, fallback=translate("email.fallback.unnamed", locale)
        )
        subject, html_body = render_recruitment_invite_email(
            token,
            candidate_name,
            vacancy_title,
            expires_in_days=data.expires_in_days,
            locale=locale,
        )
        enqueue_email(
            data.email,
            subject,
            html_body,
            tenant_id=str(tenant_id),
            template_code="recruitment.assessment_invite",
        )
    except Exception:
        logger.exception("Failed to enqueue recruitment invite email for cv=%s", cv_id)

    return _invite_to_read(invite)


async def list_invites(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
) -> list[dict]:
    """List all invite links for a candidate-vacancy."""
    result = await db.execute(
        select(AssessmentInvite).where(
            AssessmentInvite.candidate_vacancy_id == cv_id,
            AssessmentInvite.tenant_id == tenant_id,
        )
    )
    return [_invite_to_read(inv) for inv in result.scalars().all()]


async def _resolve_invite(db: AsyncSession, token: str) -> AssessmentInvite:
    """Fetch a non-expired invite by token. Raise 401/410 otherwise."""
    result = await db.execute(
        select(AssessmentInvite).where(AssessmentInvite.token == token)
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise AppError("invite_not_found", status.HTTP_404_NOT_FOUND)
    if invite.expires_at < datetime.now(timezone.utc):
        invite.status = "expired"
        await db.commit()
        raise AppError("invite_expired", status.HTTP_410_GONE)
    return invite


async def get_invite_context(db: AsyncSession, token: str) -> dict:
    """Bundle invite + vacancy + candidate + latest resume + questions for the public page."""
    from app.core.s3 import get_presigned_url

    invite = await _resolve_invite(db, token)

    cv_result = await db.execute(
        select(CandidateVacancy)
        .options(
            selectinload(CandidateVacancy.candidate).selectinload(Candidate.person),
            selectinload(CandidateVacancy.vacancy),
        )
        .where(CandidateVacancy.id == invite.candidate_vacancy_id)
    )
    cv = cv_result.scalar_one_or_none()
    if not cv:
        raise AppError("candidate_vacancy_not_found", status.HTTP_404_NOT_FOUND)

    # i18n F7: no English "(unnamed)" on the wire — the public invite page
    # localizes the empty-name fallback itself.
    candidate_name = candidate_display_name(cv.candidate, fallback="")

    resume_result = await db.execute(
        select(CandidateFile)
        .where(CandidateFile.candidate_id == cv.candidate_id)
        .order_by(CandidateFile.created_at.desc())
        .limit(1)
    )
    resume = resume_result.scalar_one_or_none()

    resume_url = None
    if resume and resume.file_id:
        file_record = await db.get(File, resume.file_id)
        if file_record:
            resume_url = get_presigned_url(file_record.path)

    q_result = await db.execute(
        select(CandidateQuestion)
        .where(
            CandidateQuestion.candidate_id == cv.candidate_id,
            CandidateQuestion.vacancy_id == cv.vacancy_id,
            CandidateQuestion.tenant_id == invite.tenant_id,
        )
        .order_by(CandidateQuestion.sort_order)
    )
    questions = [_question_to_read(q) for q in q_result.scalars().all()]

    return {
        "invite": _invite_to_read(invite),
        "vacancy_id": cv.vacancy_id,
        "vacancy_title": cv.vacancy.title if cv.vacancy else None,
        "candidate_id": cv.candidate_id,
        "candidate_name": candidate_name,
        "resume_url": resume_url,
        "resume_filename": resume.original_filename if resume else None,
        "resume_mime_type": resume.mime_type if resume else None,
        "questions": questions,
    }


async def get_invite_canvas(db: AsyncSession, token: str) -> dict:
    """Public canvas, scoped to the invited evaluator's candidate-vacancy."""
    invite = await _resolve_invite(db, token)
    result = await db.execute(
        select(CandidateVacancy).where(
            CandidateVacancy.id == invite.candidate_vacancy_id
        )
    )
    cv = result.scalar_one_or_none()
    if not cv:
        raise AppError("candidate_vacancy_not_found", status.HTTP_404_NOT_FOUND)
    canvas = await get_canvas(db, cv.tenant_id, cv.vacancy_id)
    canvas["candidates"] = [
        c
        for c in canvas["candidates"]
        if c.get("candidate_vacancy_id") == invite.candidate_vacancy_id
    ]
    canvas["evaluator_id"] = f"invite:{token}"
    canvas["evaluator_name"] = invite.evaluator_name or invite.email
    canvas["evaluators"] = [
        {
            "id": canvas["evaluator_id"],
            "name": canvas["evaluator_name"],
        }
    ]
    return canvas


async def record_invite_assessment(db: AsyncSession, token: str, payload: dict) -> dict:
    """Public mutation: record an evaluator's score via invite token.

    Tenant pays for the assessment (their hire pipeline benefits) — we explicitly
    call the billing hooks here because the wrapper-based path can't see
    `tenant_id` through a public token signature.
    """
    from app.core import billing_hooks

    invite = await _resolve_invite(db, token)

    cv_id_raw = payload.get("candidate_vacancy_id")
    competence_id = payload.get("competence_id")
    score = payload.get("score")
    comment = payload.get("comment")

    if not competence_id:
        raise AppError("competence_id_required", status.HTTP_400_BAD_REQUEST)

    if cv_id_raw and str(cv_id_raw) != str(invite.candidate_vacancy_id):
        raise AppError(
            "invite_token_candidate_vacancy_mismatch", status.HTTP_403_FORBIDDEN
        )

    try:
        competence_uuid = uuid.UUID(str(competence_id))
    except (ValueError, TypeError):
        raise AppError("competence_id_must_be_uuid", status.HTTP_400_BAD_REQUEST)

    # Validate that competence belongs to the vacancy's profile so anonymous
    # evaluators can't pollute human_assessments with arbitrary UUIDs.
    cv_lookup = await db.execute(
        select(CandidateVacancy).where(
            CandidateVacancy.id == invite.candidate_vacancy_id
        )
    )
    cv_obj = cv_lookup.scalar_one_or_none()
    if cv_obj:
        profile_lookup = await db.execute(
            select(VacancyProfile).where(
                VacancyProfile.vacancy_id == cv_obj.vacancy_id,
                VacancyProfile.tenant_id == invite.tenant_id,
            )
        )
        profile = profile_lookup.scalar_one_or_none()
        allowed_ids: set[str] = set()
        if profile and profile.profile_data:
            for item in profile.profile_data.get("competences", []) or []:
                if isinstance(item, dict):
                    raw = item.get("id") or item.get("name")
                    norm = normalize_competence_id(raw) if raw else None
                    if norm is not None:
                        allowed_ids.add(str(norm))
        if allowed_ids and str(competence_uuid) not in allowed_ids:
            raise AppError(
                "competence_id_not_in_vacancy_profile",
                status.HTTP_400_BAD_REQUEST,
            )

    score_value = float(score) if score is not None else None

    # Bill the inviting tenant before mutating; precheck raises 402 on shortfall.
    await billing_hooks.precheck_action(
        db, invite.tenant_id, "recruitment.record_assessment"
    )

    result = await db.execute(
        select(HumanAssessment).where(
            HumanAssessment.candidate_vacancy_id == invite.candidate_vacancy_id,
            HumanAssessment.competence_id == competence_uuid,
            HumanAssessment.tenant_id == invite.tenant_id,
            HumanAssessment.invite_id == invite.id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.score = score_value
        existing.comment = comment
        existing.version = existing.version + 1
        await db.commit()
        await db.refresh(existing)
        flipped_completed = False
        if invite.status == "opened":
            invite.status = "completed"
            await db.commit()
            flipped_completed = True
        await billing_hooks.consume_action(
            db, invite.tenant_id, None, "recruitment.update_assessment"
        )
        if flipped_completed:
            await _publish_event(
                "recruitment.invite.completed",
                {
                    "tenant_id": str(invite.tenant_id),
                    "invite_id": str(invite.id),
                    "cv_id": str(invite.candidate_vacancy_id),
                    "evaluator_name": invite.evaluator_name or invite.email,
                    "candidate_name": None,
                },
            )
        # FR-28: token flow — audit recorded in-body because the wrapper
        # can't see the inviting tenant through a token signature.
        await audit_service.record_event(
            db,
            tenant_id=invite.tenant_id,
            user_id=None,
            action="assessment.invite_submit",
            entity_type="assessment",
            entity_id=existing.id,
            payload_diff={"invite_id": str(invite.id), "version": existing.version},
        )
        return _assessment_to_read(existing)

    ha = HumanAssessment(
        tenant_id=invite.tenant_id,
        candidate_vacancy_id=invite.candidate_vacancy_id,
        competence_id=competence_uuid,
        evaluator_id=None,
        evaluator_name=invite.evaluator_name or invite.email,
        invite_id=invite.id,
        score=score_value,
        comment=comment,
        version=1,
    )
    db.add(ha)
    flipped_completed = False
    if invite.status == "opened":
        invite.status = "completed"
        flipped_completed = True
    await db.commit()
    await db.refresh(ha)
    await billing_hooks.consume_action(
        db, invite.tenant_id, None, "recruitment.record_assessment"
    )
    if flipped_completed:
        await _publish_event(
            "recruitment.invite.completed",
            {
                "tenant_id": str(invite.tenant_id),
                "invite_id": str(invite.id),
                "cv_id": str(invite.candidate_vacancy_id),
                "evaluator_name": invite.evaluator_name or invite.email,
                "candidate_name": None,
            },
        )
    # FR-28: token flow — see comment on the existing-row branch above.
    await audit_service.record_event(
        db,
        tenant_id=invite.tenant_id,
        user_id=None,
        action="assessment.invite_submit",
        entity_type="assessment",
        entity_id=ha.id,
        payload_diff={"invite_id": str(invite.id), "version": 1},
    )
    return _assessment_to_read(ha)


async def get_invite_by_token(db: AsyncSession, token: str) -> dict | None:
    """Get invite by token (public, no auth needed)."""
    result = await db.execute(
        select(AssessmentInvite).where(AssessmentInvite.token == token)
    )
    invite = result.scalar_one_or_none()
    if not invite:
        return None

    # Check expiry
    if invite.expires_at < datetime.now(timezone.utc):
        invite.status = "expired"
        await db.commit()

    # Update status to opened if pending
    if invite.status == "pending":
        invite.status = "opened"
        await db.commit()

    return _invite_to_read(invite)


def _invite_to_read(invite: AssessmentInvite) -> dict:
    return {
        "id": invite.id,
        "candidate_vacancy_id": invite.candidate_vacancy_id,
        "token": invite.token,
        "email": invite.email,
        "evaluator_name": invite.evaluator_name,
        "status": invite.status,
        "expires_at": invite.expires_at,
        "created_at": invite.created_at,
    }


# ---------------------------------------------------------------------------
# Canvas API
# ---------------------------------------------------------------------------


async def get_canvas(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
) -> dict:
    """Build canvas matrix: candidates x competencies x evaluators.

    Returns dict with:
    - competences: list of competences from vacancy profile
    - candidates: list of {candidate_id, name, human_scores, ai_scores}
    - evaluators: list of {id, name}
    """

    await _get_vacancy(db, tenant_id, vacancy_id)

    # Get vacancy profile competences
    profile_result = await db.execute(
        select(VacancyProfile).where(
            VacancyProfile.vacancy_id == vacancy_id,
            VacancyProfile.tenant_id == tenant_id,
        )
    )
    profile = profile_result.scalar_one_or_none()
    if not profile or not profile.profile_data:
        return {"competences": [], "candidates": [], "evaluators": []}

    profile_competences = profile.profile_data.get("competences", [])

    # Get all candidate-vacancy links
    cvs_result = await db.execute(
        select(CandidateVacancy)
        .options(
            selectinload(CandidateVacancy.candidate).selectinload(Candidate.person)
        )
        .where(
            CandidateVacancy.vacancy_id == vacancy_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
    )
    cvs = cvs_result.scalars().unique().all()

    if not cvs:
        return {
            "competences": profile_competences,
            "candidates": [],
            "evaluators": [],
        }

    cv_ids = [cv.id for cv in cvs]

    # Get all human assessments for these CVs
    human_result = await db.execute(
        select(HumanAssessment).where(
            HumanAssessment.candidate_vacancy_id.in_(cv_ids),
            HumanAssessment.tenant_id == tenant_id,
        )
    )
    human_scores = human_result.scalars().all()

    # Get AI assessments via interviews
    interview_result = await db.execute(
        select(Interview).where(
            Interview.candidate_vacancy_id.in_(cv_ids),
            Interview.tenant_id == tenant_id,
        )
    )
    interviews = interview_result.scalars().all()
    interview_ids = [i.id for i in interviews]

    ai_scores_list: list = []
    if interview_ids:
        ai_result = await db.execute(
            select(AIAssessment).where(
                AIAssessment.interview_id.in_(interview_ids),
                AIAssessment.tenant_id == tenant_id,
            )
        )
        ai_scores_list = list(ai_result.scalars().all())

    # Map interview_id -> cv_id
    interview_cv_map = {i.id: i.candidate_vacancy_id for i in interviews}

    # Build evaluator set: registered users + invited evaluators (keyed by invite_id)
    evaluator_ids = {hs.evaluator_id for hs in human_scores if hs.evaluator_id}
    evaluators: list[dict] = []
    if evaluator_ids:
        users_result = await db.execute(select(User).where(User.id.in_(evaluator_ids)))
        users = users_result.scalars().all()
        evaluators = [
            {"id": str(u.id), "name": f"{u.first_name} {u.last_name}"} for u in users
        ]
    invite_ids = {hs.invite_id for hs in human_scores if hs.invite_id}
    if invite_ids:
        invites_result = await db.execute(
            select(AssessmentInvite).where(AssessmentInvite.id.in_(invite_ids))
        )
        for inv in invites_result.scalars().all():
            evaluators.append(
                {
                    "id": f"invite:{inv.id}",
                    "name": inv.evaluator_name or inv.email,
                }
            )

    # Build candidate data
    candidates_data = []
    for cv in cvs:
        # HRP-361: full_name-first fallback — resume-sourced candidates
        # have no Person row (person_id optional, HRP-181 REDO).
        name = candidate_display_name(cv.candidate)

        # Human scores keyed by competence_id -> evaluator_key -> score
        cv_human = [hs for hs in human_scores if hs.candidate_vacancy_id == cv.id]
        scores: dict[str, dict[str, float | None]] = {}
        for hs in cv_human:
            comp_id = str(hs.competence_id)
            if comp_id not in scores:
                scores[comp_id] = {}
            evaluator_key = (
                str(hs.evaluator_id) if hs.evaluator_id else f"invite:{hs.invite_id}"
            )
            scores[comp_id][evaluator_key] = hs.score

        # AI scores keyed by competence_id
        cv_ai = [
            ai
            for ai in ai_scores_list
            if interview_cv_map.get(ai.interview_id) == cv.id
        ]
        ai_map: dict[str, float | None] = {}
        for ai in cv_ai:
            ai_map[str(ai.competence_id)] = ai.score

        candidates_data.append(
            {
                "candidate_vacancy_id": cv.id,
                "candidate_id": cv.candidate_id,
                "name": name,
                "status": cv.status,
                "human_scores": scores,
                "ai_scores": ai_map,
            }
        )

    return {
        "competences": profile_competences,
        "candidates": candidates_data,
        "evaluators": evaluators,
    }


# ---------------------------------------------------------------------------
# Assessment matrix (HRP-265 — Compact matrix + per-candidate aggregates)
# ---------------------------------------------------------------------------


# Tz-aware sentinel used in tuple-comparison fallbacks so a row with a NULL
# ``created_at`` cannot crash sort/dedup with "can't compare offset-naive and
# offset-aware datetimes". Older Interview rows imported pre-migration may
# legitimately lack a timestamp.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _normalize_ai_status(raw_status: str | None) -> str:
    """Map AIAssessment.status onto matrix-friendly buckets.

    The production CompetenceAssessment Pydantic schema (see
    ``prompts_interview.py``) writes one of:

    * ``assessed`` — AI returned a numeric verdict
    * ``not_covered`` — competence never came up on the transcript
    * ``insufficient`` — transcript mentioned the competence but the model
      could not reach a verdict; treated the same as not_covered for
      denominator purposes because no numeric score will ever land

    The matrix also accepts a small set of legacy / convenience synonyms so
    tests and historical rows keep working. Anything else passes through
    unchanged so the UI can render unknown statuses explicitly.
    """
    if not raw_status:
        return "missing"
    lowered = raw_status.lower()
    # ``ready``/``ok``/``completed`` survive from the pre-Pydantic schema
    # and the demo killswitch; ``assessed`` is the canonical production
    # token. All four mean "AI produced a numeric verdict".
    if lowered in {"assessed", "ready", "ok", "completed", "complete"}:
        return "ready"
    # ``insufficient`` is grouped with ``not_covered`` so a transcript
    # that mentioned a competence but did not let the model finish the
    # call does not silently deflate the candidate's AI % match.
    if lowered in {"not_covered", "insufficient", "skipped", "no_data"}:
        return "not_covered"
    return lowered


def _percent(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 1)


def _evaluator_key(
    evaluator_id: uuid.UUID | None,
    invite_id: uuid.UUID | None,
    label: str,
) -> tuple[str, str]:
    """Identity of one human opinion on one cell.

    A manager can score the same competence both in the round sheet and
    in the Canvas inline editor. Those are the same person changing their
    mind, not two evaluators, so the two rows collapse onto one key and
    the newest wins — otherwise the mean would sit between the old and
    the corrected score.
    """
    if evaluator_id is not None:
        return ("user", str(evaluator_id))
    if invite_id is not None:
        return ("invite", str(invite_id))
    return ("name", label)


class _MatrixScale(NamedTuple):
    """Everything the matrix needs to speak one set of units."""

    name: str | None
    min_score: float
    max_score: float
    # Ratio to rebase a legacy ``HumanAssessment`` by: those Canvas /
    # invite cells are entered against the tenant ``ScaleConfig``, so on a
    # 1-5 tenant with a 1-4 vacancy a stored 5 would otherwise render
    # above the matrix maximum.
    legacy_ratio: float


def _ai_score_on_scale(
    raw_score: float | None, min_score: float, max_score: float
) -> float | None:
    """Rebase a canonical 0..1 AI score onto the vacancy scale's range.

    Review finding on HRP-510 REDO: ``raw × max`` puts the AI on 0..max
    while manager levels sit on min..max, so on "Standard 1-4" the AI's
    bottom mark printed 0.0 against the manager's 1 — a full threshold
    apart, i.e. two people agreeing that the candidate is at the bottom
    of the scale were reported as disagreeing. The scale's own floor is
    the AI's floor: ``min + raw × (max - min)``.
    """

    span = compute_normalized_ai_score(raw_score, max_score - min_score)
    if span is None:
        return None
    # A one-level scale has no span to spread over; every mark is that level.
    if max_score <= min_score:
        return round(min_score, 2)
    return round(min_score + span, 2)


async def _matrix_scale(
    db: AsyncSession, tenant_id: uuid.UUID, vacancy: Vacancy
) -> _MatrixScale:
    """The scale the matrix renders, and the units both halves speak.

    HRP-510 REDO — that scale is the **vacancy's** Assessment scale, the
    one the round sheets are filled against and the one the Scale
    selector names. It used to be the tenant ``ScaleConfig`` (max 5), so
    a vacancy on "Standard 1-4" showed a manager's top mark as 5 and
    offered "Points (max 5)" in a selector the recruiter reads as the
    vacancy's own scale.

    Frozen snapshot first (that is what already-entered scores were
    written against), then the bound scale, then the tenant default.

    ``min_score`` is the scale's lowest level, not zero: manager marks
    live on min..max, so the AI half has to be rebased onto the same
    range (``_ai_score_on_scale``) or the two bottom marks read as a
    disagreement.

    This returns **no** divergence threshold, deliberately — there are two
    of them and they answer different questions:

    * ``AssessmentScale.divergence_threshold`` (frozen into the snapshot)
      is the **evaluator vs evaluator** threshold: how far apart two
      humans scoring the same round may sit before the round sheet flags
      them (HRP-374 / HRP-742). Default 2 on "Standard 1-4".
    * ``recruitment_matrix_settings.divergence_threshold`` on the tenant
      is the **Manager vs AI** gap this matrix is about (HRP-265,
      default 1.0), read through
      ``settings_service.get_divergence_threshold``.

    Reading the first one here silently halved the matrix's sensitivity
    (2 instead of 1 on a default vacancy) and swallowed the demo story's
    one explainable Manager/AI disagreement.
    """

    from app.modules.recruitment import settings_service
    from app.modules.recruitment.manager_assessment_models import (
        AssessmentScale,
        AssessmentScaleLevel,
    )

    active_scale = await settings_service.get_active_scale(db, tenant_id)
    tenant_max = float(active_scale.max_value) if active_scale else 5.0

    name: str | None = None
    min_score: float | None = None
    max_score: float | None = None

    snapshot = vacancy.assessment_scale_snapshot
    if snapshot:
        values = [
            float(level["value"])
            for level in (snapshot.get("levels") or [])
            if isinstance(level, dict) and level.get("value") is not None
        ]
        if values:
            name, min_score, max_score = snapshot.get("name"), min(values), max(values)

    if max_score is None:
        scale: AssessmentScale | None = None
        if vacancy.assessment_scale_id is not None:
            scale = await db.get(AssessmentScale, vacancy.assessment_scale_id)
        if scale is None:
            # ``ensure_default_scale`` writes; a GET must not. Reading the
            # default directly leaves the freeze to the first score write.
            scale = (
                (
                    await db.execute(
                        select(AssessmentScale).where(
                            AssessmentScale.tenant_id == tenant_id,
                            AssessmentScale.is_default.is_(True),
                            AssessmentScale.archived_at.is_(None),
                        )
                    )
                )
                .scalars()
                .first()
            )
        if scale is not None:
            values = list(
                (
                    await db.execute(
                        select(AssessmentScaleLevel.value).where(
                            AssessmentScaleLevel.scale_id == scale.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            if values:
                name = scale.name
                min_score, max_score = float(min(values)), float(max(values))

    if min_score is None or max_score is None:
        # No Assessment scale anywhere — the tenant ScaleConfig is the
        # only statement of units left, and it starts at its own minimum.
        return _MatrixScale(
            name=(active_scale.name if active_scale else None),
            min_score=float(active_scale.min_value) if active_scale else 0.0,
            max_score=tenant_max,
            legacy_ratio=1.0,
        )
    return _MatrixScale(
        name=name,
        min_score=min_score,
        max_score=max_score,
        legacy_ratio=(max_score / tenant_max if tenant_max > 0 else 1.0),
    )


async def _load_manager_cell_scores(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_ids: list[uuid.UUID],
    *,
    competence_id: uuid.UUID | None = None,
    legacy_ratio: float = 1.0,
    slot_round_by_cv: dict[uuid.UUID, uuid.UUID] | None = None,
) -> dict[uuid.UUID, dict[str, list[dict]]]:
    """Per-competence manager scores, keyed ``cv_id -> comp_key -> entries``.

    ``slot_round_by_cv`` (HRP-510 REDO) pins each candidate to one round
    — the one occupying the selected Round slot. Legacy ``HumanAssessment``
    cells carry no round at all, so they drop out entirely under a slot:
    a cell is either "what this round said" or a dash, never a round score
    silently mixed with a round-less one.

    HRP-507: manager scores live in two tables. ``HumanAssessment`` is the
    legacy/Canvas surface (inline cell editing, the old invite flow), and
    it is the only one the matrix used to read — which is why DIVERGENCE
    was always empty: the product flow (Manager assessments on the
    candidate page, HRP-186) writes ``AssessmentCompetenceScore`` rows
    hanging off a round's evaluation sheets, and those were invisible here.

    Round scores are scoped exactly like ``candidate_vacancies.manager_score``
    (``manager_assessment_service.recompute_manager_score``): the newest
    completed round that has scores, else the newest round with any — so
    the cells and the Manager column in the same table can never disagree
    about which round they describe. Only "counted" sheets contribute
    (internal evaluators, plus submitted external ones).
    """

    # Local imports: manager_assessment_service imports back into this
    # module's neighbourhood, so keep the edge out of module import time.
    from app.modules.recruitment.manager_assessment_models import (
        AssessmentCompetenceScore,
        AssessmentRound,
        RecruitmentAssessment,
    )
    from app.modules.recruitment.manager_assessment_service import _COUNTABLE_SHEET

    if not cv_ids:
        return {}

    legacy_query = select(HumanAssessment).where(
        HumanAssessment.candidate_vacancy_id.in_(cv_ids),
        HumanAssessment.tenant_id == tenant_id,
    )
    if competence_id is not None:
        legacy_query = legacy_query.where(
            HumanAssessment.competence_id == competence_id
        )
    legacy_rows = (await db.execute(legacy_query)).scalars().all()

    rounds = (
        (
            await db.execute(
                select(AssessmentRound)
                .where(
                    AssessmentRound.candidate_vacancy_id.in_(cv_ids),
                    AssessmentRound.tenant_id == tenant_id,
                    AssessmentRound.archived_at.is_(None),
                )
                .order_by(AssessmentRound.created_at)
            )
        )
        .scalars()
        .all()
    )

    score_query = (
        select(AssessmentCompetenceScore, RecruitmentAssessment, AssessmentRound)
        .join(
            RecruitmentAssessment,
            RecruitmentAssessment.id == AssessmentCompetenceScore.assessment_id,
        )
        .join(AssessmentRound, AssessmentRound.id == RecruitmentAssessment.round_id)
        .where(
            AssessmentRound.candidate_vacancy_id.in_(cv_ids),
            AssessmentRound.tenant_id == tenant_id,
            AssessmentRound.archived_at.is_(None),
            AssessmentCompetenceScore.score_value.is_not(None),
            _COUNTABLE_SHEET,
        )
    )
    if competence_id is not None:
        score_query = score_query.where(
            AssessmentCompetenceScore.competence_id == competence_id
        )
    score_rows = (await db.execute(score_query)).all() if rounds else []

    # Which round each candidate's cells describe — the very same choice
    # ``recompute_manager_score`` makes, or the cells and the Manager
    # column beside them would describe different rounds. HRP-727 moved
    # the rule into one selector; do not re-derive it here.
    from app.modules.recruitment.manager_assessment_service import (
        select_manager_score_round,
    )

    scored_ids = {rnd.id for _score, _sheet, rnd in score_rows}
    rounds_by_cv: dict[uuid.UUID, list] = {}
    for rnd in rounds:
        rounds_by_cv.setdefault(rnd.candidate_vacancy_id, []).append(rnd)
    chosen_round: dict[uuid.UUID, uuid.UUID] = {}
    if slot_round_by_cv is not None:
        chosen_round = dict(slot_round_by_cv)
    else:
        for cv_id, cv_rounds in rounds_by_cv.items():
            picked = select_manager_score_round(cv_rounds, scored_ids)
            if picked is not None:
                chosen_round[cv_id] = picked.id

    user_ids = {hs.evaluator_id for hs in legacy_rows if hs.evaluator_id}
    user_ids |= {
        sheet.evaluator_user_id
        for _s, sheet, _r in score_rows
        if sheet.evaluator_user_id
    }
    evaluator_names: dict[uuid.UUID, str] = {}
    if user_ids:
        user_rows = (
            (await db.execute(select(User).where(User.id.in_(user_ids))))
            .scalars()
            .all()
        )
        for u in user_rows:
            full = f"{u.first_name or ''} {u.last_name or ''}".strip()
            evaluator_names[u.id] = full or u.email

    # cv -> comp_key -> evaluator identity -> entry (newest wins)
    staged: dict[uuid.UUID, dict[str, dict[tuple[str, str], dict]]] = {}

    def _stage(cv_id: uuid.UUID, comp_key: str, entry: dict) -> None:
        bucket = staged.setdefault(cv_id, {}).setdefault(comp_key, {})
        key = _evaluator_key(
            entry["evaluator_id"], entry["invite_id"], entry["evaluator_label"]
        )
        previous = bucket.get(key)
        if previous is None or (entry["updated_at"] or _EPOCH) >= (
            previous["updated_at"] or _EPOCH
        ):
            bucket[key] = entry

    # Round sheets first, Canvas cells second: on an exact timestamp tie the
    # Canvas edit wins, because that is the surface a recruiter opens to
    # correct a cell they are looking at.
    for score, sheet, rnd in score_rows:
        if chosen_round.get(rnd.candidate_vacancy_id) != rnd.id:
            continue
        if sheet.evaluator_user_id is not None:
            label = evaluator_names.get(sheet.evaluator_user_id) or "Evaluator"
        else:
            label = sheet.evaluator_display_name or "Invited evaluator"
        _stage(
            rnd.candidate_vacancy_id,
            str(score.competence_id),
            {
                # Already a level of the vacancy's AssessmentScale — the
                # very scale the matrix renders since HRP-510 REDO, so
                # nothing to rebase.
                "score": float(score.score_value),
                "evaluator_label": label,
                "evaluator_id": sheet.evaluator_user_id,
                "invite_id": sheet.evaluator_invite_id,
                "comment": score.comment,
                "updated_at": score.updated_at,
                "version": sheet.version,
            },
        )

    for hs in legacy_rows:
        if hs.score is None or slot_round_by_cv is not None:
            continue
        if hs.evaluator_id is not None:
            label = evaluator_names.get(hs.evaluator_id) or "Evaluator"
        else:
            label = hs.evaluator_name or "Invited evaluator"
        _stage(
            hs.candidate_vacancy_id,
            str(hs.competence_id),
            {
                # Entered against the tenant ScaleConfig; the matrix speaks
                # the vacancy scale.
                "score": round(float(hs.score) * legacy_ratio, 2),
                "evaluator_label": label,
                "evaluator_id": hs.evaluator_id,
                "invite_id": hs.invite_id,
                "comment": hs.comment,
                "updated_at": hs.updated_at,
                "version": hs.version,
            },
        )

    return {
        cv_id: {
            comp_key: sorted(
                by_evaluator.values(),
                key=lambda e: e["updated_at"] or _EPOCH,
                reverse=True,
            )
            for comp_key, by_evaluator in per_comp.items()
        }
        for cv_id, per_comp in staged.items()
    }


def competence_cells_from_run_data(analysis_data: dict | None) -> dict[str, dict]:
    """Competence verdicts carried by one ``AIAnalysisRun.analysis_data``.

    Keyed by the normalised competence id, so the result drops straight
    into the same ``comp_key -> entry`` indexes the matrix and the XLSX
    report already speak. Pure — no session, no scale — because the two
    callers run on opposite sides of the sync/async split (the matrix
    endpoint and the report Celery task, HRP-685) and only the parsing
    has to agree.
    """

    entries = (analysis_data or {}).get("competence_assessments") or []
    if not isinstance(entries, list):
        return {}
    cells: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # Unlike the interview path, the run payload keeps the raw
        # model-supplied competence id, so it has to be normalised here
        # to match the profile keys.
        comp_uuid = normalize_competence_id(entry.get("competence_id") or "")
        if comp_uuid is None:
            continue
        raw = entry.get("score")
        reasoning = entry.get("reasoning")
        cells[str(comp_uuid)] = {
            # bool is an int subclass — an LLM answering the schema
            # with true/false must not become a fabricated 1.0/0.0.
            "score": (
                float(raw)
                if isinstance(raw, (int, float)) and not isinstance(raw, bool)
                else None
            ),
            "status": _normalize_ai_status(entry.get("status")),
            "reasoning": reasoning if isinstance(reasoning, str) else None,
            "citations": entry.get("citations") or [],
        }
    return cells


async def _load_ai_run_cell_scores(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, dict]]:
    """Per-competence AI scores from the active analysis run.

    HRP-507: ``AIAssessment`` rows only exist for interview-backed
    analyses. A resume-only run (the pre-screening mode the ticket walks
    through) writes its competence verdicts into
    ``AIAnalysisRun.analysis_data["competence_assessments"]`` and nothing
    else, so without this fallback the AI half of every cell is empty and
    no divergence can ever be computed.
    """

    if not cv_ids:
        return {}

    runs = (
        (
            await db.execute(
                select(AIAnalysisRun).where(
                    AIAnalysisRun.candidate_vacancy_id.in_(cv_ids),
                    AIAnalysisRun.tenant_id == tenant_id,
                    AIAnalysisRun.status == "completed",
                    AIAnalysisRun.archived_at.is_(None),
                )
                # A partial unique index already allows only one active
                # completed run per candidate-vacancy, but ordering keeps
                # the read deterministic if that invariant ever slips.
                .order_by(AIAnalysisRun.created_at.desc(), AIAnalysisRun.id.desc())
            )
        )
        .scalars()
        .all()
    )

    index: dict[uuid.UUID, dict[str, dict]] = {}
    for run in runs:
        if run.candidate_vacancy_id in index:
            continue
        cells = competence_cells_from_run_data(run.analysis_data)
        if not cells:
            continue
        index[run.candidate_vacancy_id] = {
            comp_key: {
                **entry,
                "updated_at": run.updated_at,
                "interview_id": run.interview_id,
            }
            for comp_key, entry in cells.items()
        }
    return index


async def get_assessment_matrix(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    *,
    round_filter: str = "latest",
    only_cv_ids: list[uuid.UUID] | None = None,
) -> dict:
    """Compact-view aggregates: per-cell M vs AI + per-candidate %.

    ``only_cv_ids`` scopes the candidate axis to the given rows — every
    per-candidate load (interviews, AI assessments, manager cell scores)
    shrinks with it, so a caller that needs one row's aggregates (the
    candidate PATCH, HRP-662) stops paying for the whole vacancy grid.
    Cell/aggregate semantics are per-candidate and unaffected.

    Returns the shape consumed by the new Assessments tab and the future
    Sort by % match column. For every (candidate, competence) we surface:

    * ``manager_score`` — mean of all human evaluators' scores; ``None``
      when no manager has scored the cell yet.
    * ``ai_score`` — latest AI score; ``None`` for ``not_covered`` /
      missing analyses.
    * ``ai_status`` — ``ready`` / ``not_covered`` / ``missing`` so the UI
      can render the right empty state.
    * ``divergence`` — boolean; only ``True`` when both sides have a
      numeric score and ``abs(m - ai) >= tenant.divergence_threshold``.

    Per-candidate aggregates follow the spec formula: the denominator is
    ``max_score * (total_competences - not_covered_count)``; not-covered
    competences only drop out of the AI % side, never the manager %.

    ``round_filter`` (HRP-510 REDO) is either a round-agnostic view —
    ``latest`` (default, the newest interview per candidate) or ``all``
    (mean across every interview) — or one of the **slots** reported in
    ``round_slots``: ``pre_interview``, ``interview_1``..``interview_N``,
    ``final``. A slot is a position in the Manager-assessments strip, not
    a round id (rounds belong to a candidate-vacancy pair), and ``N`` is
    the highest interview round any candidate on the vacancy reached.

    Under a slot both halves of a cell are scoped to it: the manager side
    is that candidate's round in that slot, and the AI side is the last
    completed run that answers for it — ``resume_only`` for
    ``pre_interview``, and for the interview slots the ``full`` run whose
    transcript came from an interview linked to that round. A candidate
    who never had the round reads as dashes across the row.
    """

    # Local imports avoid a circular dependency with settings_service
    # (which itself reads no service.py symbols).
    from app.modules.recruitment import settings_service

    vacancy = await _get_vacancy(db, tenant_id, vacancy_id)

    profile_row = (
        await db.execute(
            select(VacancyProfile).where(
                VacancyProfile.vacancy_id == vacancy_id,
                VacancyProfile.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    profile_competences: list[dict] = (
        (profile_row.profile_data or {}).get("competences", []) if profile_row else []
    )

    cvs_query = (
        select(CandidateVacancy)
        .options(
            selectinload(CandidateVacancy.candidate).selectinload(Candidate.person)
        )
        .where(
            CandidateVacancy.vacancy_id == vacancy_id,
            CandidateVacancy.tenant_id == tenant_id,
        )
    )
    if only_cv_ids is not None:
        cvs_query = cvs_query.where(CandidateVacancy.id.in_(only_cv_ids))
    cvs = (await db.execute(cvs_query)).scalars().unique().all()

    matrix_scale = await _matrix_scale(db, tenant_id, vacancy)
    scale_name = matrix_scale.name
    min_score, max_score = matrix_scale.min_score, matrix_scale.max_score
    legacy_ratio = matrix_scale.legacy_ratio
    # Manager vs AI is the tenant matrix setting (HRP-265). The vacancy
    # scale's own ``divergence_threshold`` is a different question —
    # evaluator vs evaluator on a round sheet — and must not be read here.
    threshold = await settings_service.get_divergence_threshold(db, tenant_id)

    if not cvs or not profile_competences:
        return {
            "vacancy_id": vacancy_id,
            "divergence_threshold": threshold,
            "max_score": max_score,
            "scale_name": scale_name,
            "round_slots": [],
            "round": "latest",
            "competences": [
                {
                    "id": normalize_competence_id(
                        comp.get("id") or comp.get("name") or ""
                    ),
                    "name": comp.get("name") or comp.get("id") or "",
                    "group": comp.get("group"),
                    "criticality": comp.get("criticality"),
                }
                for comp in profile_competences
                if isinstance(comp, dict)
                and normalize_competence_id(comp.get("id") or comp.get("name") or "")
                is not None
            ],
            "candidates": [],
        }

    cv_ids = [cv.id for cv in cvs]

    # Archived interviews are out of scope everywhere else the matrix
    # reads them (``_latest_transcribed_interview``, ``_load_transcripts``,
    # ``apply_ai_analysis_state``). Without the same filter here the
    # HRP-510 Round selector counted and numbered archived rows, so
    # "Latest" could resolve to a recording the recruiter had already
    # thrown away while the rest of the payload described a live one.
    interview_rows = (
        (
            await db.execute(
                select(Interview).where(
                    Interview.candidate_vacancy_id.in_(cv_ids),
                    Interview.tenant_id == tenant_id,
                    Interview.archived_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    interview_cv_map: dict[uuid.UUID, uuid.UUID] = {
        iv.id: iv.candidate_vacancy_id for iv in interview_rows
    }
    interview_created: dict[uuid.UUID, datetime] = {
        iv.id: iv.created_at for iv in interview_rows if iv.created_at is not None
    }

    ai_rows: list[AIAssessment] = []
    if interview_rows:
        ai_rows = list(
            (
                await db.execute(
                    select(AIAssessment).where(
                        AIAssessment.interview_id.in_([iv.id for iv in interview_rows]),
                        AIAssessment.tenant_id == tenant_id,
                    )
                )
            )
            .scalars()
            .all()
        )

    # HRP-510 — interview rounds, ordered oldest-first per candidate. The
    # AI side is the only one with a round dimension (one analysis per
    # interview), so this ordering is what the Round selector scopes.
    interviews_by_cv: dict[uuid.UUID, list[uuid.UUID]] = {}
    for iv in sorted(
        interview_rows,
        key=lambda row: (row.created_at or _EPOCH, row.id),
    ):
        interviews_by_cv.setdefault(iv.candidate_vacancy_id, []).append(iv.id)
    # HRP-510 REDO — the Round selector lists **slots** of the Manager
    # assessments strip (Pre-interview / Interview 1..N / Final), not
    # interview recordings and not round ids: a round belongs to one
    # candidate-vacancy pair, so "Interview 2" has to resolve to a
    # different row for every candidate. ``N`` is the highest interview
    # round reached by any candidate on the vacancy — the tester's
    # "take it from the candidate with the most rounds".
    from app.modules.recruitment.manager_assessment_models import AssessmentRound

    round_rows = (
        (
            await db.execute(
                select(AssessmentRound).where(
                    AssessmentRound.candidate_vacancy_id.in_(cv_ids),
                    AssessmentRound.tenant_id == tenant_id,
                    AssessmentRound.archived_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    rounds_by_slot: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    max_interview_number = 0
    has_pre_interview = False
    has_final = False
    for rnd in round_rows:
        if rnd.type == "interview":
            if rnd.round_number is None:
                continue
            slot_key = f"interview_{rnd.round_number}"
            max_interview_number = max(max_interview_number, rnd.round_number)
        elif rnd.type in {"pre_interview", "final"}:
            slot_key = rnd.type
            has_pre_interview = has_pre_interview or rnd.type == "pre_interview"
            has_final = has_final or rnd.type == "final"
        else:
            continue
        rounds_by_slot.setdefault(rnd.candidate_vacancy_id, {})[slot_key] = rnd.id

    round_slots: list[dict] = []
    if has_pre_interview:
        round_slots.append(
            {"key": "pre_interview", "type": "pre_interview", "number": None}
        )
    round_slots.extend(
        {"key": f"interview_{number}", "type": "interview", "number": number}
        for number in range(1, max_interview_number + 1)
    )
    if has_final:
        round_slots.append({"key": "final", "type": "final", "number": None})

    normalized_round = str(round_filter or "latest").strip().lower()
    slot_keys = {slot["key"] for slot in round_slots}
    if normalized_round not in slot_keys and normalized_round != "all":
        normalized_round = "latest"
    selected_slot: str | None = (
        normalized_round if normalized_round in slot_keys else None
    )
    # Which round each candidate has in the selected slot. A candidate who
    # never had that round is simply absent — the row reads as dashes.
    slot_round_by_cv: dict[uuid.UUID, uuid.UUID] | None = None
    if selected_slot is not None:
        slot_round_by_cv = {
            cv_id: slots[selected_slot]
            for cv_id, slots in rounds_by_slot.items()
            if selected_slot in slots
        }

    # HRP-507: both manager surfaces (round sheets + legacy Canvas cells).
    human_index = await _load_manager_cell_scores(
        db,
        tenant_id,
        cv_ids,
        legacy_ratio=legacy_ratio,
        slot_round_by_cv=slot_round_by_cv,
    )

    def _interview_in_scope(cv_id: uuid.UUID, interview_id: uuid.UUID) -> bool:
        # Under a slot the AI half comes from the analysis run that
        # answers for that round, not from whichever interview is newest.
        if selected_slot is not None:
            return False
        ordered = interviews_by_cv.get(cv_id) or []
        if not ordered:
            return False
        if normalized_round == "all":
            return True
        return ordered[-1] == interview_id

    # Index AI: cv_id -> comp_id -> latest entry (by interview.created_at, then by
    # AIAssessment.updated_at). Older runs are kept only as ``ai_history`` so the
    # footer can show what was superseded.
    ai_index: dict[uuid.UUID, dict[str, dict]] = {}
    for ai in ai_rows:
        cv_id = interview_cv_map.get(ai.interview_id)
        if cv_id is None:
            continue
        if not _interview_in_scope(cv_id, ai.interview_id):
            continue
        comp_key = str(ai.competence_id)
        candidate_bucket = ai_index.setdefault(cv_id, {})
        existing = candidate_bucket.get(comp_key)
        if existing is not None:
            # Tz-aware EPOCH fallback — Interview / AIAssessment rows can
            # legitimately have NULL created_at / updated_at, and comparing
            # a None against a tz-aware datetime in a tuple raises TypeError.
            new_anchor = (
                interview_created.get(ai.interview_id) or _EPOCH,
                ai.updated_at or _EPOCH,
            )
            old_anchor = (
                interview_created.get(existing["interview_id"]) or _EPOCH,
                existing["updated_at"] or _EPOCH,
            )
            if new_anchor <= old_anchor:
                continue
        candidate_bucket[comp_key] = {
            "score": float(ai.score) if ai.score is not None else None,
            "status": _normalize_ai_status(ai.status),
            "updated_at": ai.updated_at,
            "interview_id": ai.interview_id,
        }

    if normalized_round == "all":
        # "All combined" means the mean across rounds, not the newest
        # round winning — otherwise the option would be identical to
        # "Latest". Only numeric ``ready`` scores contribute; a cell the
        # AI never covered in any round stays not-covered.
        combined: dict[uuid.UUID, dict[str, list[float]]] = {}
        for ai in ai_rows:
            cv_id = interview_cv_map.get(ai.interview_id)
            if cv_id is None or ai.score is None:
                continue
            if _normalize_ai_status(ai.status) != "ready":
                continue
            combined.setdefault(cv_id, {}).setdefault(str(ai.competence_id), []).append(
                float(ai.score)
            )
        for cv_id, per_comp in combined.items():
            for comp_key, values in per_comp.items():
                entry = ai_index.setdefault(cv_id, {}).get(comp_key)
                if entry is None:
                    continue
                entry["score"] = round(sum(values) / len(values), 2)
                entry["status"] = "ready"

    # HRP-507: candidates analysed without an interview (resume-only mode,
    # or a full run whose per-interview rows were pruned) have no
    # ``AIAssessment`` rows at all — their competence verdicts only live on
    # the analysis run. Fall back per candidate so those cells stop being
    # blank; a candidate with interview rows keeps the round-scoped data.
    #
    # The active run carries no round dimension, so it only answers the
    # round-agnostic views; a selected slot is served by the run that
    # belongs to that round, resolved just below.
    if selected_slot is None:
        run_index = await _load_ai_run_cell_scores(
            db, tenant_id, [cv.id for cv in cvs if not ai_index.get(cv.id)]
        )
        for run_cv_id, run_cells in run_index.items():
            ai_index.setdefault(run_cv_id, {}).update(run_cells)
    else:
        # HRP-510 REDO — the AI half of a slot:
        #   (a) Pre-interview  -> the last completed ``resume_only`` run;
        #   (b) Interview N / Final -> the last completed ``full`` run whose
        #       transcript came from an interview linked to that round.
        # No such run means no AI opinion for that round: a dash, never
        # the candidate's newest analysis borrowed from another round.
        # Archived runs stay in scope on purpose — a resume-only run is
        # archived the moment a full top-up supersedes it, and it is still
        # the only answer the Pre-interview slot has.
        round_of_interview: dict[uuid.UUID, uuid.UUID | None] = {
            iv.id: iv.round_id for iv in interview_rows
        }
        ai_by_interview: dict[uuid.UUID, dict[str, dict]] = {}
        for ai in ai_rows:
            ai_by_interview.setdefault(ai.interview_id, {})[str(ai.competence_id)] = {
                "score": float(ai.score) if ai.score is not None else None,
                "status": _normalize_ai_status(ai.status),
                "updated_at": ai.updated_at,
                "interview_id": ai.interview_id,
            }
        wanted_mode = "resume_only" if selected_slot == "pre_interview" else "full"
        slot_runs = (
            (
                await db.execute(
                    select(AIAnalysisRun)
                    .where(
                        AIAnalysisRun.candidate_vacancy_id.in_(cv_ids),
                        AIAnalysisRun.tenant_id == tenant_id,
                        AIAnalysisRun.status == "completed",
                        AIAnalysisRun.mode == wanted_mode,
                    )
                    .order_by(AIAnalysisRun.created_at.desc(), AIAnalysisRun.id.desc())
                )
            )
            .scalars()
            .all()
        )
        for run in slot_runs:
            run_cv_id = run.candidate_vacancy_id
            if run_cv_id in ai_index:
                continue
            slot_round = (slot_round_by_cv or {}).get(run_cv_id)
            # A candidate who never had this round reads as dashes across
            # the whole row — including the AI half. A resume-only run is
            # not "the Pre-interview verdict" for a candidate who has no
            # Pre-interview round.
            if slot_round is None:
                continue
            if wanted_mode == "full":
                if run.interview_id is None:
                    continue
                if round_of_interview.get(run.interview_id) != slot_round:
                    continue
            slot_cells = competence_cells_from_run_data(run.analysis_data)
            if not slot_cells and run.interview_id is not None:
                # Runs written before the payload carried competence
                # verdicts still have their per-interview rows.
                slot_cells = ai_by_interview.get(run.interview_id) or {}
            if slot_cells:
                ai_index[run_cv_id] = slot_cells

    competences_payload: list[dict] = []
    competence_keys: list[str] = []
    for comp in profile_competences:
        if not isinstance(comp, dict):
            continue
        comp_uuid = normalize_competence_id(comp.get("id") or comp.get("name") or "")
        if comp_uuid is None:
            continue
        comp_key = str(comp_uuid)
        competence_keys.append(comp_key)
        competences_payload.append(
            {
                "id": comp_uuid,
                "name": comp.get("name") or comp.get("id") or "",
                "group": comp.get("group"),
                "criticality": comp.get("criticality"),
            }
        )

    total_competences = len(competence_keys)
    candidates_payload: list[dict] = []
    for cv in cvs:
        # HRP-361: full_name-first fallback — resume-sourced candidates
        # have no Person row (person_id optional, HRP-181 REDO).
        name = candidate_display_name(cv.candidate, fallback="")

        cells: list[dict] = []
        manager_score_sum: float = 0.0
        manager_scored_count: int = 0
        ai_score_sum: float = 0.0
        ai_scored_count: int = 0
        ai_not_covered_count: int = 0
        divergence_count: int = 0

        for comp_key in competence_keys:
            human_entries = human_index.get(cv.id, {}).get(comp_key, [])
            manager_score: float | None = None
            if human_entries:
                manager_score = round(
                    sum(e["score"] for e in human_entries) / len(human_entries), 2
                )
                manager_score_sum += manager_score
                manager_scored_count += 1

            ai_entry = ai_index.get(cv.id, {}).get(comp_key)
            ai_score: float | None = None
            ai_status = "missing"
            if ai_entry is not None:
                ai_status = ai_entry["status"]
                # HRP-507: AI competence scores are stored on the canonical
                # 0..1 scale (HRP-274), manager scores on the tenant scale.
                # Comparing them raw made every populated cell look
                # divergent and deflated the AI % match, so rebase the AI
                # side the same way ``ai_score_normalized`` is rebased on
                # the candidate row.
                rebased = (
                    _ai_score_on_scale(ai_entry["score"], min_score, max_score)
                    if ai_status == "ready"
                    else None
                )
                if rebased is not None:
                    ai_score = round(rebased, 2)
                    ai_score_sum += ai_score
                    ai_scored_count += 1
                else:
                    # Anything that is not a numeric ``ready`` score must
                    # drop out of the AI denominator — otherwise a transient
                    # ``failed`` cell or a ``ready`` row with NULL score
                    # silently deflates the candidate's % match.
                    ai_not_covered_count += 1

            divergence = False
            if manager_score is not None and ai_score is not None:
                divergence = abs(manager_score - ai_score) >= threshold
                if divergence:
                    divergence_count += 1

            cells.append(
                {
                    "competence_id": uuid.UUID(comp_key),
                    "manager_score": manager_score,
                    "manager_evaluator_count": len(human_entries),
                    "ai_score": ai_score,
                    "ai_status": ai_status,
                    "divergence": divergence,
                }
            )

        # Manager denominator covers every competence in the profile (the
        # spec treats no-score-yet as 0 of max for ranking purposes). AI
        # denominator subtracts not_covered cells so a candidate skipped
        # by the AI on a couple of competences is not unfairly diluted.
        manager_denominator = max_score * total_competences
        ai_denominator = max_score * max(total_competences - ai_not_covered_count, 0)

        manager_percent = (
            _percent(manager_score_sum, manager_denominator)
            if manager_scored_count > 0
            else None
        )
        ai_percent = (
            _percent(ai_score_sum, ai_denominator) if ai_scored_count > 0 else None
        )

        candidates_payload.append(
            {
                "candidate_vacancy_id": cv.id,
                "candidate_id": cv.candidate_id,
                "name": name or "Unknown",
                "status": cv.status,
                "stage_id": cv.stage_id,
                # HRP-361: ``CandidateVacancy.stage`` is lazy="selectin",
                # already loaded with the CV rows above.
                "stage_name": cv.stage.name if cv.stage else None,
                "manager_percent": manager_percent,
                "ai_percent": ai_percent,
                "divergence_count": divergence_count,
                "manager_scored_competences": manager_scored_count,
                "ai_scored_competences": ai_scored_count,
                "ai_not_covered_competences": ai_not_covered_count,
                "cells": cells,
            }
        )

    return {
        "vacancy_id": vacancy_id,
        "divergence_threshold": threshold,
        "max_score": max_score,
        "scale_name": scale_name,
        "total_competences": total_competences,
        # HRP-510 REDO — the Round selector's options, and which one this
        # payload is scoped to.
        "round_slots": round_slots,
        "round": normalized_round,
        "competences": competences_payload,
        "candidates": candidates_payload,
    }


async def get_assessment_matrix_cell_detail(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    candidate_vacancy_id: uuid.UUID,
    competence_id: uuid.UUID,
) -> dict:
    """Drill-down used by the footer-info row in the Compact matrix.

    Lists every evaluator's score (with timestamp) plus the latest AI
    score on the cell. Older AI runs are exposed under ``ai_history`` so
    the recruiter can tell why a top-up shifted a verdict.
    """

    vacancy = await _get_vacancy(db, tenant_id, vacancy_id)

    cv = (
        await db.execute(
            select(CandidateVacancy)
            .options(
                selectinload(CandidateVacancy.candidate).selectinload(Candidate.person)
            )
            .where(
                CandidateVacancy.id == candidate_vacancy_id,
                CandidateVacancy.vacancy_id == vacancy_id,
                CandidateVacancy.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if cv is None:
        raise AppError("candidate_vacancy_link_not_found", status.HTTP_404_NOT_FOUND)

    # The popover must speak the units of the cell it was opened from —
    # both halves of it (review finding: the AI score arrived raw here
    # while the cell showed it rebased). HRP-510 REDO moved those units
    # onto the vacancy's Assessment scale, so this reads the same seam.
    matrix_scale = await _matrix_scale(db, tenant_id, vacancy)
    min_score, max_score = matrix_scale.min_score, matrix_scale.max_score
    legacy_ratio = matrix_scale.legacy_ratio

    # HRP-507: same two manager surfaces the matrix reads, so the
    # drill-down can never contradict the cell it was opened from.
    manager_index = await _load_manager_cell_scores(
        db,
        tenant_id,
        [cv.id],
        competence_id=competence_id,
        legacy_ratio=legacy_ratio,
    )
    manager_entries: list[dict] = [
        {
            "evaluator_label": entry["evaluator_label"],
            "evaluator_id": entry["evaluator_id"],
            "invite_id": entry["invite_id"],
            "score": entry["score"],
            "comment": entry["comment"],
            "updated_at": entry["updated_at"],
            "version": entry["version"],
        }
        for entry in manager_index.get(cv.id, {}).get(str(competence_id), [])
    ]

    interview_rows = (
        (
            await db.execute(
                select(Interview).where(
                    Interview.candidate_vacancy_id == cv.id,
                    Interview.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    interview_created = {
        iv.id: iv.created_at for iv in interview_rows if iv.created_at is not None
    }

    ai_rows: list[AIAssessment] = []
    if interview_rows:
        ai_rows = list(
            (
                await db.execute(
                    select(AIAssessment).where(
                        AIAssessment.interview_id.in_([iv.id for iv in interview_rows]),
                        AIAssessment.competence_id == competence_id,
                        AIAssessment.tenant_id == tenant_id,
                    )
                )
            )
            .scalars()
            .all()
        )

    ai_sorted = sorted(
        ai_rows,
        key=lambda r: (
            interview_created.get(r.interview_id) or _EPOCH,
            r.updated_at or _EPOCH,
        ),
        reverse=True,
    )
    latest_ai: dict | None = None
    ai_history: list[dict] = []
    for idx, ai in enumerate(ai_sorted):
        entry = {
            # Raw 0..1 on the row, tenant scale in the payload — exactly
            # what the matrix cell does with the same number.
            "score": _ai_score_on_scale(ai.score, min_score, max_score),
            "status": _normalize_ai_status(ai.status),
            "reasoning": ai.reasoning,
            "citations": ai.citations or [],
            "interview_id": ai.interview_id,
            "updated_at": ai.updated_at,
        }
        if idx == 0:
            latest_ai = entry
        else:
            ai_history.append(entry)

    if latest_ai is None:
        # Resume-only candidates have no AIAssessment rows at all; the
        # cell falls back to the active analysis run, so the popover must
        # too, or it claims "no AI opinion" next to a filled-in cell.
        run_cells = await _load_ai_run_cell_scores(db, tenant_id, [cv.id])
        run_entry = run_cells.get(cv.id, {}).get(str(competence_id))
        if run_entry is not None:
            latest_ai = {
                "score": _ai_score_on_scale(run_entry["score"], min_score, max_score),
                "status": run_entry["status"],
                "reasoning": run_entry.get("reasoning"),
                "citations": [],
                "interview_id": run_entry.get("interview_id"),
                "updated_at": run_entry.get("updated_at"),
            }

    return {
        "candidate_vacancy_id": cv.id,
        "candidate_name": candidate_display_name(cv.candidate),
        "competence_id": competence_id,
        "manager_entries": manager_entries,
        "ai_latest": latest_ai,
        "ai_history": ai_history,
    }
