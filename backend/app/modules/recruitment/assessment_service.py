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

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
    AIAssessment,
    AssessmentInvite,
    Candidate,
    CandidateFile,
    CandidateQuestion,
    CandidateVacancy,
    HumanAssessment,
    Interview,
    RecruitmentAuditLog,
    VacancyProfile,
)
from app.modules.recruitment.schemas import (
    AssessmentScoreCreate,
    AssessmentScoreUpdate,
    InviteCreate,
    QuestionCreate,
    QuestionUpdate,
)
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")

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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
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
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Candidate-vacancy link not found"
        )

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
            raise HTTPException(
                status.HTTP_412_PRECONDITION_FAILED,
                f"Assessment was updated by another writer "
                f"(expected version {expected_version}, current {existing.version}).",
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
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            "Assessment was created by another writer "
            f"(no row existed when you read; expected version {expected_version}).",
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")

    expected_version = parse_assessment_if_match(if_match)
    if expected_version is not None and expected_version != ha.version:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            f"Assessment was updated by another writer "
            f"(expected version {expected_version}, current {ha.version}).",
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audit event not found")
    payload = audit_row.payload_diff or {}
    # Spec: revert only applies to Manager-side cells. Invite-only audit
    # rows (no evaluator_id) are surfaced for context but cannot be
    # restored — the invitee owns their submission. This guard runs
    # BEFORE the (cv, comp, evaluator) match so the user gets the right
    # message instead of a generic 404 hiding the real reason.
    if payload.get("evaluator_id") is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Invited-evaluator scores cannot be reverted",
        )
    if (
        payload.get("candidate_vacancy_id") != str(cv_id)
        or payload.get("competence_id") != str(competence_id)
        or payload.get("evaluator_id") != str(evaluator_id)
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Audit event does not match the requested cell",
        )

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
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            f"Assessment was updated by another writer since this "
            f"Versions snapshot (expected version {expected_version}, "
            f"current {existing.version}).",
        )

    if existing is None:
        if expected_version is not None:
            raise HTTPException(
                status.HTTP_412_PRECONDITION_FAILED,
                "Assessment was removed by another writer since this "
                "Versions snapshot.",
            )
        # Revert-to-nothing on a row that has since been cleared is a
        # no-op; revert-to-score creates a fresh entry attributed to the
        # initiator. Either way we get a clean audit trail of the action.
        if target_score is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Nothing to revert: the cell is already empty",
            )
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
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Candidate-vacancy link not found"
        )

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

        candidate_name = candidate_display_name(cv.candidate, fallback="(unnamed)")
        vacancy_title = cv.vacancy.title if cv.vacancy else None
        subject, html_body = render_recruitment_invite_email(
            token,
            candidate_name,
            vacancy_title,
            expires_in_days=data.expires_in_days,
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    if invite.expires_at < datetime.now(timezone.utc):
        invite.status = "expired"
        await db.commit()
        raise HTTPException(status.HTTP_410_GONE, "Invite expired")
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate-vacancy not found")

    candidate_name = candidate_display_name(cv.candidate, fallback="(unnamed)")

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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate-vacancy not found")
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
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "competence_id is required")

    if cv_id_raw and str(cv_id_raw) != str(invite.candidate_vacancy_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Token does not match candidate-vacancy"
        )

    try:
        competence_uuid = uuid.UUID(str(competence_id))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "competence_id must be a UUID")

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
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "competence_id is not part of the vacancy profile",
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


async def get_assessment_matrix(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vacancy_id: uuid.UUID,
) -> dict:
    """Compact-view aggregates: per-cell M vs AI + per-candidate %.

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
    """

    # Local imports avoid a circular dependency with settings_service
    # (which itself reads no service.py symbols).
    from app.modules.recruitment import settings_service

    await _get_vacancy(db, tenant_id, vacancy_id)

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

    cvs = (
        (
            await db.execute(
                select(CandidateVacancy)
                .options(
                    selectinload(CandidateVacancy.candidate).selectinload(
                        Candidate.person
                    )
                )
                .where(
                    CandidateVacancy.vacancy_id == vacancy_id,
                    CandidateVacancy.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .unique()
        .all()
    )

    threshold = await settings_service.get_divergence_threshold(db, tenant_id)
    active_scale = await settings_service.get_active_scale(db, tenant_id)
    max_score: float = float(active_scale.max_value) if active_scale else 5.0
    scale_name: str | None = active_scale.name if active_scale else None

    if not cvs or not profile_competences:
        return {
            "vacancy_id": vacancy_id,
            "divergence_threshold": threshold,
            "max_score": max_score,
            "scale_name": scale_name,
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

    human_rows = (
        (
            await db.execute(
                select(HumanAssessment).where(
                    HumanAssessment.candidate_vacancy_id.in_(cv_ids),
                    HumanAssessment.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )

    interview_rows = (
        (
            await db.execute(
                select(Interview).where(
                    Interview.candidate_vacancy_id.in_(cv_ids),
                    Interview.tenant_id == tenant_id,
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

    # Evaluator names — used by the footer-info popover when a recruiter
    # clicks an individual cell.
    user_ids = {hs.evaluator_id for hs in human_rows if hs.evaluator_id}
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

    # Index human assessments: cv_id -> comp_id (str) -> list of (score, evaluator_label, version, updated_at)
    human_index: dict[uuid.UUID, dict[str, list[dict]]] = {}
    for hs in human_rows:
        if hs.score is None:
            continue
        comp_key = str(hs.competence_id)
        bucket = human_index.setdefault(hs.candidate_vacancy_id, {}).setdefault(
            comp_key, []
        )
        if hs.evaluator_id is not None:
            label = evaluator_names.get(hs.evaluator_id) or "Evaluator"
        else:
            label = hs.evaluator_name or "Invited evaluator"
        bucket.append(
            {
                "score": float(hs.score),
                "evaluator_label": label,
                "evaluator_id": str(hs.evaluator_id) if hs.evaluator_id else None,
                "invite_id": str(hs.invite_id) if hs.invite_id else None,
                "updated_at": hs.updated_at,
                "version": hs.version,
            }
        )

    # Index AI: cv_id -> comp_id -> latest entry (by interview.created_at, then by
    # AIAssessment.updated_at). Older runs are kept only as ``ai_history`` so the
    # footer can show what was superseded.
    ai_index: dict[uuid.UUID, dict[str, dict]] = {}
    for ai in ai_rows:
        cv_id = interview_cv_map.get(ai.interview_id)
        if cv_id is None:
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
                if ai_entry["score"] is not None and ai_status == "ready":
                    ai_score = ai_entry["score"]
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

    await _get_vacancy(db, tenant_id, vacancy_id)

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
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Candidate-vacancy link not found"
        )

    human_rows = (
        (
            await db.execute(
                select(HumanAssessment).where(
                    HumanAssessment.candidate_vacancy_id == cv.id,
                    HumanAssessment.competence_id == competence_id,
                    HumanAssessment.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )

    user_ids = {hs.evaluator_id for hs in human_rows if hs.evaluator_id}
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

    manager_entries: list[dict] = []
    for hs in sorted(
        human_rows,
        key=lambda r: (r.updated_at or r.created_at or _EPOCH),
        reverse=True,
    ):
        if hs.evaluator_id is not None:
            label = evaluator_names.get(hs.evaluator_id) or "Evaluator"
        else:
            label = hs.evaluator_name or "Invited evaluator"
        manager_entries.append(
            {
                "evaluator_label": label,
                "evaluator_id": hs.evaluator_id,
                "invite_id": hs.invite_id,
                "score": float(hs.score) if hs.score is not None else None,
                "comment": hs.comment,
                "updated_at": hs.updated_at,
                "version": hs.version,
            }
        )

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
            "score": float(ai.score) if ai.score is not None else None,
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

    return {
        "candidate_vacancy_id": cv.id,
        "candidate_name": candidate_display_name(cv.candidate),
        "competence_id": competence_id,
        "manager_entries": manager_entries,
        "ai_latest": latest_ai,
        "ai_history": ai_history,
    }
