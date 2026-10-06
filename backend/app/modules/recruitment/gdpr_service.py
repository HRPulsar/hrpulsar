"""GDPR export & erasure (R4b, §9.2). 72h SLA target.

Export gathers everything we hold for a candidate (person, candidate,
resumes, candidate_vacancies, questions, assessments, interviews,
segments, consents, references to reports) into a single JSON document,
uploads it to S3 under ``gdpr_exports/{tenant_id}/{request_id}.json`` and
returns a presigned URL valid for 7 days. The file itself is deleted
once that link expires (HRP-978, ``apply_retention``).

Erasure is intentionally *soft*: PII fields are redacted in place and an
audit-trail row is added to ``gdpr_erasure_log`` so the company can prove
to regulators when the request was honoured. The per-type erasure
primitives below are shared with the retention sweep (HRP-983).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import status
from sqlalchemy import Text, cast, delete, null, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.errors import AppError
from app.core.s3 import delete_file as s3_delete_file
from app.core.s3 import get_presigned_url, upload_file
from app.models import Person
from app.modules.auth.models import User
from app.modules.notification.models import EmailLog, Notification
from app.modules.recruitment.analysis_cache_service import (
    compute_cache_key_for_interview,
)
from app.modules.recruitment.manager_assessment_models import (
    AssessmentCompetenceScore,
    AssessmentIndicatorScore,
    AssessmentRound,
    RecruitmentAssessment,
)
from app.modules.recruitment.models import (
    AIAnalysisRun,
    AIAssessment,
    AssessmentInvite,
    Candidate,
    CandidateFile,
    CandidateQuestion,
    CandidateVacancy,
    ConsentRequest,
    ConsolidatedReport,
    GDPRErasureLog,
    GDPRExportRequest,
    GDPRPendingBlobDelete,
    HumanAssessment,
    Interview,
    InterviewAnalysisCache,
    InterviewSegment,
    Question,
    QuestionSet,
    RecruitmentAuditLog,
    RecruitmentRetentionConfig,
    UploadSession,
)
from app.modules.recruitment.settings_schemas import GDPRExportRequestCreate
from app.modules.storage.models import File

logger = logging.getLogger(__name__)

EXPORT_PRESIGN_TTL_SECONDS = 7 * 24 * 3600  # 7 days


# ─── Helpers ────────────────────────────────────────────────────────


async def _resolve_candidate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    candidate_id: uuid.UUID | None,
    person_id: uuid.UUID | None,
    email: str | None,
) -> Candidate | None:
    if candidate_id:
        c = await db.get(Candidate, candidate_id)
        if c and c.tenant_id == tenant_id:
            return c
        return None
    if person_id:
        result = await db.execute(
            select(Candidate).where(
                Candidate.tenant_id == tenant_id,
                Candidate.person_id == person_id,
            )
        )
        return result.scalars().first()
    if email:
        result = await db.execute(
            select(Candidate)
            .join(Person, Person.id == Candidate.person_id)
            .where(Candidate.tenant_id == tenant_id, Person.email == email)
        )
        return result.scalars().first()
    return None


async def _gather_candidate_payload(
    db: AsyncSession, tenant_id: uuid.UUID, candidate: Candidate
) -> dict[str, Any]:
    person = await db.get(Person, candidate.person_id)

    res_q = await db.execute(
        select(CandidateFile).where(
            CandidateFile.tenant_id == tenant_id, CandidateFile.candidate_id == candidate.id
        )
    )
    resumes = list(res_q.scalars().all())

    cv_q = await db.execute(
        select(CandidateVacancy).where(
            CandidateVacancy.tenant_id == tenant_id,
            CandidateVacancy.candidate_id == candidate.id,
        )
    )
    candidate_vacancies = list(cv_q.scalars().all())

    cv_ids = [cv.id for cv in candidate_vacancies]

    questions = []
    if cv_ids:
        q_q = await db.execute(
            select(CandidateQuestion).where(
                CandidateQuestion.tenant_id == tenant_id,
                CandidateQuestion.candidate_id == candidate.id,
            )
        )
        questions = list(q_q.scalars().all())

    interviews: list[Interview] = []
    segments: list[InterviewSegment] = []
    human_assessments: list[HumanAssessment] = []
    ai_assessments: list[AIAssessment] = []
    if cv_ids:
        i_q = await db.execute(
            select(Interview)
            .options(selectinload(Interview.segments))
            .where(
                Interview.tenant_id == tenant_id,
                Interview.candidate_vacancy_id.in_(cv_ids),
            )
        )
        interviews = list(i_q.scalars().all())
        for iv in interviews:
            segments.extend(iv.segments)

        ha_q = await db.execute(
            select(HumanAssessment).where(
                HumanAssessment.tenant_id == tenant_id,
                HumanAssessment.candidate_vacancy_id.in_(cv_ids),
            )
        )
        human_assessments = list(ha_q.scalars().all())

        if interviews:
            ai_q = await db.execute(
                select(AIAssessment).where(
                    AIAssessment.tenant_id == tenant_id,
                    AIAssessment.interview_id.in_([i.id for i in interviews]),
                )
            )
            ai_assessments = list(ai_q.scalars().all())

    async def rows(model: Any, *where: Any) -> list[Any]:
        return list((await db.execute(select(model).where(*where))).scalars())

    runs = await rows(
        AIAnalysisRun,
        AIAnalysisRun.tenant_id == tenant_id,
        AIAnalysisRun.candidate_vacancy_id.in_(cv_ids),
    )
    rounds = await rows(
        AssessmentRound,
        AssessmentRound.tenant_id == tenant_id,
        AssessmentRound.candidate_vacancy_id.in_(cv_ids),
    )
    sheets = await rows(
        RecruitmentAssessment,
        RecruitmentAssessment.tenant_id == tenant_id,
        RecruitmentAssessment.round_id.in_([r.id for r in rounds]),
    )
    sheet_ids = [a.id for a in sheets]
    competence_scores = await rows(
        AssessmentCompetenceScore,
        AssessmentCompetenceScore.assessment_id.in_(sheet_ids),
    )
    indicator_scores = await rows(
        AssessmentIndicatorScore,
        AssessmentIndicatorScore.assessment_id.in_(sheet_ids),
    )
    question_sets = await rows(
        QuestionSet,
        QuestionSet.tenant_id == tenant_id,
        QuestionSet.candidate_vacancy_id.in_(cv_ids),
    )
    set_questions = await rows(
        Question,
        Question.tenant_id == tenant_id,
        Question.question_set_id.in_([qs.id for qs in question_sets]),
    )

    cons_q = await db.execute(
        select(ConsentRequest).where(
            ConsentRequest.tenant_id == tenant_id,
            ConsentRequest.candidate_id == candidate.id,
        )
    )
    consents = list(cons_q.scalars().all())

    return {
        "schema_version": "gdpr-export.v1",
        "tenant_id": str(tenant_id),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "person": _person_dict(person) if person else None,
        "candidate": _candidate_dict(candidate),
        "resumes": [_resume_dict(r) for r in resumes],
        "candidate_vacancies": [_cv_dict(cv) for cv in candidate_vacancies],
        "questions": [_question_dict(q) for q in questions],
        "interviews": [_interview_dict(iv) for iv in interviews],
        "interview_segments": [_segment_dict(s) for s in segments],
        "human_assessments": [_human_assessment_dict(a) for a in human_assessments],
        "ai_assessments": [_ai_assessment_dict(a) for a in ai_assessments],
        "consent_requests": [_consent_dict(c) for c in consents],
        "ai_analysis_runs": [_fields(r, *_RUN_FIELDS) for r in runs],
        "assessment_rounds": [_fields(r, *_ROUND_FIELDS) for r in rounds],
        "evaluator_sheets": [_fields(a, *_SHEET_FIELDS) for a in sheets],
        "evaluator_competence_scores": [
            _fields(sc, *_SCORE_FIELDS, "competence_id") for sc in competence_scores
        ],
        "evaluator_indicator_scores": [
            _fields(sc, *_SCORE_FIELDS, "indicator_id", "competence_id")
            for sc in indicator_scores
        ],
        "question_sets": [_fields(qs, *_QUESTION_SET_FIELDS) for qs in question_sets],
        "question_set_questions": [
            _fields(q, *_SET_QUESTION_FIELDS) for q in set_questions
        ],
    }


def _plain(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _fields(row: Any, *names: str) -> dict:
    return {name: _plain(getattr(row, name)) for name in ("id", *names)}


_RUN_FIELDS = (
    "candidate_vacancy_id",
    "interview_id",
    "mode",
    "status",
    "verdict",
    "verdict_summary",
    "key_strength",
    "key_risk",
    "risk_mitigation",
    "recommendation_for_next_step",
    "ai_score",
    "data_completeness",
    "analysis_data",
    "created_at",
)
_ROUND_FIELDS = ("candidate_vacancy_id", "type", "status", "archived_reason")
_SHEET_FIELDS = (
    "round_id",
    "evaluator_type",
    "evaluator_display_name",
    "status",
    "submitted_at",
    "final_notes",
)
_SCORE_FIELDS = ("assessment_id", "score_value", "comment")
_QUESTION_SET_FIELDS = ("candidate_vacancy_id", "name", "set_type", "coverage_note")
_SET_QUESTION_FIELDS = (
    "question_set_id",
    "text",
    "goal",
    "priority",
    "resume_anchor_jsonb",
    "expected_answer_indicators",
    "follow_ups",
    "rationale",
)


def _person_dict(p: Person) -> dict:
    return {
        "id": str(p.id),
        "first_name": p.first_name,
        "last_name": p.last_name,
        "middle_name": p.middle_name,
        "email": p.email,
        "phone": p.phone,
    }


def _candidate_dict(c: Candidate) -> dict:
    return {
        "id": str(c.id),
        "person_id": str(c.person_id) if c.person_id else None,
        "full_name": c.full_name,
        "email": c.email,
        "phone": c.phone,
        "linkedin_url": c.linkedin_url,
        "location": c.location,
        "current_position": c.current_position,
        "years_of_experience": c.years_of_experience,
        "parsed_resume": c.parsed_resume_jsonb,
        "source": c.source,
        "notes": c.notes,
        "created_at": c.created_at.isoformat(),
    }


def _resume_dict(r: CandidateFile) -> dict:
    return {
        "id": str(r.id),
        "original_filename": r.original_filename,
        "mime_type": r.mime_type,
        "file_size": r.file_size,
        "parsed_data": r.parsed_data,
        "raw_text": r.raw_text,
        "parse_status": r.parse_status,
        "created_at": r.created_at.isoformat(),
    }


def _cv_dict(cv: CandidateVacancy) -> dict:
    return {
        "id": str(cv.id),
        "vacancy_id": str(cv.vacancy_id),
        "stage_id": str(cv.stage_id) if cv.stage_id else None,
        "status": cv.status,
        "ranking_score": cv.ranking_score,
        # Stage changes with the recruiters' comments.
        "status_history": cv.status_history,
        "ai_verdict": cv.ai_verdict,
        "ai_verdict_summary": cv.ai_verdict_summary,
        "ai_key_strength": cv.ai_key_strength,
        "ai_key_risk": cv.ai_key_risk,
        "ai_risk_mitigation": cv.ai_risk_mitigation,
        "ai_score": cv.ai_score,
        "created_at": cv.created_at.isoformat(),
    }


def _question_dict(q: CandidateQuestion) -> dict:
    return {
        "id": str(q.id),
        "vacancy_id": str(q.vacancy_id),
        "competence_id": str(q.competence_id) if q.competence_id else None,
        "question_text": q.question_text,
        "good_answer": q.good_answer,
        "acceptable_answer": q.acceptable_answer,
        "poor_answer": q.poor_answer,
        "purpose": q.purpose,
        "priority": q.priority,
    }


def _interview_dict(iv: Interview) -> dict:
    return {
        "id": str(iv.id),
        "candidate_vacancy_id": str(iv.candidate_vacancy_id),
        "interviewer_id": str(iv.interviewer_id) if iv.interviewer_id else None,
        "interview_date": iv.interview_date.isoformat() if iv.interview_date else None,
        "duration_seconds": iv.duration_seconds,
        "status": iv.status,
        "transcript": iv.transcript,
        "transcription_status": iv.transcription_status,
        "analysis_status": iv.analysis_status,
        "analysis_data": iv.analysis_data,
        "consent_signed_at": (
            iv.consent_signed_at.isoformat() if iv.consent_signed_at else None
        ),
    }


def _segment_dict(s: InterviewSegment) -> dict:
    return {
        "id": str(s.id),
        "interview_id": str(s.interview_id),
        "speaker": s.speaker,
        "start_sec": s.start_sec,
        "end_sec": s.end_sec,
        "text": s.text,
        "confidence": s.confidence,
    }


def _human_assessment_dict(a: HumanAssessment) -> dict:
    return {
        "id": str(a.id),
        "candidate_vacancy_id": str(a.candidate_vacancy_id),
        "competence_id": str(a.competence_id),
        "evaluator_id": str(a.evaluator_id) if a.evaluator_id else None,
        "evaluator_name": a.evaluator_name,
        "score": a.score,
        "comment": a.comment,
        "version": a.version,
    }


def _ai_assessment_dict(a: AIAssessment) -> dict:
    return {
        "id": str(a.id),
        "interview_id": str(a.interview_id),
        "competence_id": str(a.competence_id),
        "score": a.score,
        "status": a.status,
        "citations": a.citations,
        "reasoning": a.reasoning,
    }


def _consent_dict(c: ConsentRequest) -> dict:
    return {
        "id": str(c.id),
        "candidate_id": str(c.candidate_id),
        "template_id": str(c.template_id),
        "email": c.email,
        "expires_at": c.expires_at.isoformat(),
        "signed_at": c.signed_at.isoformat() if c.signed_at else None,
        "signed_ip": c.signed_ip,
        "status": c.status,
    }


# ─── Public service surface ──────────────────────────────────────────


async def gdpr_export(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: GDPRExportRequestCreate,
) -> GDPRExportRequest:
    """Register an export request and hand the heavy work to Celery.

    The endpoint returns the ``processing`` manifest row immediately (202);
    the ``run_gdpr_export_task`` worker gathers the payload, serialises the
    multi-MB JSON and uploads to S3 off the request thread, flipping the row
    to ``completed``/``failed``. The GDPR page polls ``gdpr-requests`` for the
    download link. Erasure stays synchronous on purpose (see ``gdpr_erase``).
    """

    candidate = await _resolve_candidate(
        db,
        tenant_id,
        candidate_id=data.candidate_id,
        person_id=data.person_id,
        email=data.email,
    )
    if candidate is None:
        raise AppError("gdpr_subject_not_found", status.HTTP_404_NOT_FOUND)

    request_row = GDPRExportRequest(
        tenant_id=tenant_id,
        requested_by=user_id,
        subject_type="candidate",
        subject_id=candidate.id,
        status="processing",
    )
    db.add(request_row)
    await db.commit()
    await db.refresh(request_row)

    # Local import keeps the service ↔ tasks dependency one-directional at
    # import time (tasks imports the service, not vice versa).
    from app.modules.recruitment.tasks import run_gdpr_export_task

    run_gdpr_export_task.delay(str(request_row.id))
    return request_row


async def _perform_gdpr_export(
    db: AsyncSession, request_id: uuid.UUID
) -> dict[str, Any]:
    """Do the gather → serialise → upload work for one export request.

    Called by ``run_gdpr_export_task`` on a worker-owned session. Always
    resolves the row to a terminal status (``completed``/``failed``) and
    commits, so a crash never strands a request in ``processing``.
    """

    request_row = await db.get(GDPRExportRequest, request_id)
    if request_row is None:
        return {"status": "missing", "request_id": str(request_id)}

    tenant_id = request_row.tenant_id
    candidate = await db.get(Candidate, request_row.subject_id)
    if candidate is None or candidate.tenant_id != tenant_id:
        request_row.status = "failed"
        request_row.error = "Subject not found"
        await db.commit()
        return {"status": "failed", "request_id": str(request_id)}

    path = f"gdpr_exports/{tenant_id}/{request_row.id}.json"
    uploaded = False
    try:
        payload = await _gather_candidate_payload(db, tenant_id, candidate)
        # default=str so datetime / UUID values inside ``parsed_data`` JSON
        # blobs (which we accept as arbitrary dicts from third-party
        # resume parsers) don't break the dump on TypeError.
        body = json.dumps(
            payload, ensure_ascii=False, indent=2, default=str
        ).encode("utf-8")

        file_row: File | None = None
        if settings.s3_endpoint:
            upload_result = upload_file(body, path, "application/json")
            if upload_result is None:
                request_row.status = "failed"
                request_row.error = "S3 upload failed"
                await db.commit()
                return {"status": "failed", "request_id": str(request_id)}
            uploaded = True

            file_row = File(
                tenant_id=tenant_id,
                name=path,
                original_name=f"gdpr-export-{candidate.id}.json",
                path=path,
                size=len(body),
                mime_type="application/json",
                uploaded_by=request_row.requested_by,
                entity_type="gdpr_export",
                entity_id=request_row.id,
            )
            db.add(file_row)

        request_row.status = "completed"
        request_row.file_id = file_row.id if file_row is not None else None
        request_row.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=EXPORT_PRESIGN_TTL_SECONDS
        )
        await db.commit()
        return {"status": "completed", "request_id": str(request_id)}
    except Exception as exc:  # noqa: BLE001 — never strand a processing row
        await db.rollback()
        # The upload happened before the commit that failed: no row points
        # at the file any more, so nothing would ever expire it.
        if uploaded and not _delete_blob(path):
            db.add(GDPRPendingBlobDelete(tenant_id=tenant_id, path=path))
        request_row = await db.get(GDPRExportRequest, request_id)
        if request_row is not None:
            request_row.status = "failed"
            request_row.error = str(exc)[:500]
            await db.commit()
        return {"status": "failed", "request_id": str(request_id)}


# ─── Erasure primitives (GDPR erase + retention sweep) ───────────────

REDACTED_TEXT = "[redacted]"
# Stamped on every JSON payload an erasure blanks. The retention sweep
# reads it back to skip rows already emptied, so it must not change.
REDACTED_MARK: dict[str, bool] = {"redacted": True}
# Shorter strings would match unrelated log rows when scrubbing by text.
_MIN_NEEDLE_LEN = 4
# Names that stand for no one in particular; scrubbing them would hit
# every other candidate filed under the same placeholder.
_PLACEHOLDER_NAMES = frozenset({"redacted redacted", "unnamed candidate"})


def _redacted_email() -> str:
    return f"redacted-{uuid.uuid4().hex[:12]}@local"


def _not_redacted(column: Any) -> Any:
    """Rows whose JSON payload a previous erasure has not stamped yet."""
    return or_(column.is_(None), ~column.contains(REDACTED_MARK))


def _delete_blob(path: str) -> bool:
    try:
        return bool(s3_delete_file(path))
    except Exception:  # noqa: BLE001 — a failed delete is queued, not raised
        logger.exception("GDPR blob delete failed for %s", path)
        return False


async def _drop_storage(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    file_ids: set[uuid.UUID],
    keys: set[str] | None = None,
) -> dict[str, int]:
    """Delete object-storage blobs and their ``files`` rows.

    Only this tenant's rows go. A blob the storage refuses to delete must
    not block the erasure, yet must not be reported gone either: its key
    is queued in ``gdpr_pending_blob_deletes`` and the nightly retention
    sweep retries it. ``storage_files`` counts what is actually gone.
    """
    paths = set(keys or ())
    rows_deleted = 0
    if file_ids:
        # The nulled pointers land before the rows they pointed at go.
        await db.flush()
        rows = (
            (
                await db.execute(
                    select(File).where(
                        File.id.in_(file_ids), File.tenant_id == tenant_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            if row.path:
                paths.add(row.path)
            await db.delete(row)
            rows_deleted += 1
    if not settings.s3_endpoint:
        return {"storage_files": rows_deleted}
    pending = 0
    for path in sorted(paths):
        if not _delete_blob(path):
            db.add(GDPRPendingBlobDelete(tenant_id=tenant_id, path=path))
            pending += 1
    done = {"storage_files": len(paths) - pending}
    if pending:
        done["storage_pending"] = pending
    return done


async def _retry_pending_blob_deletes(db: AsyncSession) -> int:
    """Nightly: delete the blobs earlier erasures could not; count the done."""
    if not settings.s3_endpoint:
        return 0
    done = 0
    for row in (await db.execute(select(GDPRPendingBlobDelete))).scalars().all():
        if _delete_blob(row.path):
            await db.delete(row)
            done += 1
        else:
            row.attempts += 1
    await db.commit()
    return done


async def _redact_runs(db: AsyncSession, tenant_id: uuid.UUID, condition: Any) -> int:
    """Blank the AI texts of matching analysis runs and of the card mirror."""
    runs = (
        (
            await db.execute(
                select(AIAnalysisRun).where(
                    AIAnalysisRun.tenant_id == tenant_id, condition
                )
            )
        )
        .scalars()
        .all()
    )
    active_cv_ids: set[uuid.UUID] = set()
    for run in runs:
        run.verdict_summary = None
        run.key_strength = None
        run.key_risk = None
        run.risk_mitigation = None
        run.error_message = None
        run.analysis_data = dict(REDACTED_MARK)
        if run.archived_at is None:
            active_cv_ids.add(run.candidate_vacancy_id)
    if active_cv_ids:
        await db.execute(
            update(CandidateVacancy)
            .where(CandidateVacancy.id.in_(active_cv_ids))
            .values(
                ai_verdict_summary=None,
                ai_key_strength=None,
                ai_key_risk=None,
                ai_risk_mitigation=None,
            )
            .execution_options(synchronize_session=False)
        )
    return len(runs)


async def _erase_interviews(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interviews: list[Interview],
    file_ids: set[uuid.UUID],
    keys: set[str],
) -> dict[str, int]:
    """Media, transcript and AI analysis of each interview; the row stays."""
    if not interviews:
        return {}
    ids = [iv.id for iv in interviews]
    for iv in interviews:
        # The cache key hashes the transcript, so it goes first.
        cache_key = await compute_cache_key_for_interview(db, tenant_id, iv)
        if cache_key is not None:
            await db.execute(
                delete(InterviewAnalysisCache).where(
                    InterviewAnalysisCache.tenant_id == tenant_id,
                    InterviewAnalysisCache.cache_key == cache_key,
                )
            )
        iv.transcript = REDACTED_TEXT
        iv.analysis_data = dict(REDACTED_MARK)
        file_ids.update(
            fk
            for fk in (iv.audio_file_id, iv.video_file_id, iv.transcript_file_id)
            if fk is not None
        )
        if iv.file_s3_key:
            keys.add(iv.file_s3_key)
        iv.audio_file_id = None
        iv.video_file_id = None
        iv.transcript_file_id = None
        iv.file_s3_key = None
    segments = await db.execute(
        update(InterviewSegment)
        .where(
            InterviewSegment.tenant_id == tenant_id,
            InterviewSegment.interview_id.in_(ids),
        )
        .values(text=REDACTED_TEXT)
        .execution_options(synchronize_session=False)
    )
    ai = await db.execute(
        update(AIAssessment)
        .where(AIAssessment.tenant_id == tenant_id, AIAssessment.interview_id.in_(ids))
        .values(reasoning=REDACTED_TEXT, citations=[])
        .execution_options(synchronize_session=False)
    )
    # Upload sessions keep the original media filename.
    await db.execute(
        delete(UploadSession).where(
            UploadSession.tenant_id == tenant_id, UploadSession.interview_id.in_(ids)
        )
    )
    return {
        "interviews": len(interviews),
        "interview_segments": segments.rowcount,  # type: ignore[attr-defined]
        "ai_assessments": ai.rowcount,  # type: ignore[attr-defined]
        "ai_analysis_runs": await _redact_runs(
            db, tenant_id, AIAnalysisRun.interview_id.in_(ids)
        ),
    }


def _erase_files(files: list[CandidateFile], file_ids: set[uuid.UUID]) -> int:
    """Resume (and media) rows: text, parse and the stored blob."""
    for f in files:
        f.raw_text = None
        f.parsed_data = dict(REDACTED_MARK)
        f.original_filename = "redacted.pdf"
        if f.file_id:
            file_ids.add(f.file_id)
        f.file_id = None
    return len(files)


def _erase_consents(consents: list[ConsentRequest], *, revoke: bool = False) -> int:
    """Who signed and from where; status and dates stay as proof.

    An erasure (``revoke``) also withdraws the consent: nothing of the
    candidate may reach an AI provider afterwards.
    """
    for c in consents:
        if revoke and c.status == "signed":
            c.status = "revoked"
        c.email = _redacted_email()
        c.signed_ip = None
        c.signed_user_agent = None
    return len(consents)


async def _delete_reports(
    db: AsyncSession, reports: list[ConsolidatedReport], file_ids: set[uuid.UUID]
) -> int:
    """Reports are snapshots with names in them; they can be regenerated."""
    for r in reports:
        if r.file_id:
            file_ids.add(r.file_id)
        await db.delete(r)
    return len(reports)


def _drop_export_files(
    exports: list[GDPRExportRequest], file_ids: set[uuid.UUID]
) -> int:
    dropped = 0
    for e in exports:
        if e.file_id:
            file_ids.add(e.file_id)
            e.file_id = None
            dropped += 1
    return dropped


# ─── GDPR erase ──────────────────────────────────────────────────────


def _pii_needles(
    names: Iterable[str | None],
    emails: Iterable[str | None],
    phones: Iterable[str | None],
) -> list[str]:
    """Strings that point at the candidate in free text.

    A one-word name is no identifier — "Anna" would take every Joanna and
    every other Anna of the tenant with it — so names count only with two
    words or more. Emails and phone numbers always count; a phone also as
    bare digits, since logs keep whatever formatting the number came in.
    """
    found = set()
    for name in names:
        words = (name or "").lower().split()
        if len(words) >= 2 and " ".join(words) not in _PLACEHOLDER_NAMES:
            found.add(" ".join(words))
    for value in [*emails, *phones]:
        value = (value or "").strip().lower()
        if len(value) >= _MIN_NEEDLE_LEN:
            found.add(value)
    for phone in phones:
        digits = re.sub(r"\D", "", phone or "")
        if len(digits) >= _MIN_NEEDLE_LEN:
            found.add(digits)
    # Longest first, so a full number wins over a shorter variant of it.
    return sorted(found, key=lambda n: (-len(n), n))


def _needle_pattern(needles: list[str]) -> re.Pattern[str]:
    """Whole-word matches only: "anna lee" must not hit "Joanna Lee", and
    an address must not hit a longer one ("joe.anna@x.com", "anna@x.com.au").
    """
    parts = [
        rf"(?<![\w.%+-]){re.escape(n)}(?![\w.-]*\w)"
        if "@" in n
        else rf"(?<!\w){re.escape(n)}(?!\w)"
        for n in needles
    ]
    return re.compile("|".join(parts), re.IGNORECASE)


def _scrub(value: Any, pattern: re.Pattern[str]) -> Any:
    """Redact each mention of the candidate; the rest of the text stays."""
    if isinstance(value, str):
        return pattern.sub(REDACTED_TEXT, value)
    if isinstance(value, dict):
        return {k: _scrub(v, pattern) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, pattern) for v in value]
    return value


def _mentions(column: Any, needles: list[str]) -> Any:
    """Cheap SQL prefilter; ``_scrub`` decides on word boundaries.

    JSON text escapes quotes (``"Jack"`` reads ``\\"Jack\\"``), so each
    needle is looked up by its longest piece free of quotes and
    backslashes rather than as a whole.
    """

    def literal(needle: str) -> str:
        piece = max(re.split(r'[\s"\\]+', needle), key=len)
        return piece.replace("%", "\\%").replace("_", "\\_")

    return or_(
        *(cast(column, Text).ilike(f"%{literal(n)}%", escape="\\") for n in needles)
    )


async def _person_is_shared(
    db: AsyncSession, person_id: uuid.UUID, candidate_id: uuid.UUID
) -> bool:
    """Another tenant's candidate or a user account points at the person."""
    other_candidate = await db.scalar(
        select(Candidate.id)
        .where(Candidate.person_id == person_id, Candidate.id != candidate_id)
        .limit(1)
    )
    if other_candidate is not None:
        return True
    return (
        await db.scalar(select(User.id).where(User.person_id == person_id).limit(1))
    ) is not None


async def _scrub_logs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    needles: list[str],
    entity_ids: list[Any],
) -> dict[str, int]:
    """Audit trail, notifications and email log: the event stays, PII goes.

    Rows about the candidate's own entities lose their whole payload (it
    may quote comments or AI texts); any other row of the tenant that
    names the candidate has those strings replaced.
    """
    audit = await db.execute(
        update(RecruitmentAuditLog)
        .where(
            RecruitmentAuditLog.tenant_id == tenant_id,
            RecruitmentAuditLog.payload_diff.is_not(None),
            or_(*(RecruitmentAuditLog.entity_id.in_(ids) for ids in entity_ids)),
        )
        .values(payload_diff=dict(REDACTED_MARK))
        .execution_options(synchronize_session=False)
    )
    # Public-link events (consent signing) carry the candidate's own IP.
    await db.execute(
        update(RecruitmentAuditLog)
        .where(
            RecruitmentAuditLog.tenant_id == tenant_id,
            RecruitmentAuditLog.user_id.is_(None),
            or_(*(RecruitmentAuditLog.entity_id.in_(ids) for ids in entity_ids)),
        )
        .values(ip=None, user_agent=None)
        .execution_options(synchronize_session=False)
    )
    scrubbed = {
        "audit_events": audit.rowcount,  # type: ignore[attr-defined]
        "notifications": 0,
        "email_logs": 0,
    }
    if not needles:
        return scrubbed
    pattern = _needle_pattern(needles)

    for row in (
        await db.execute(
            select(RecruitmentAuditLog).where(
                RecruitmentAuditLog.tenant_id == tenant_id,
                _mentions(RecruitmentAuditLog.payload_diff, needles),
            )
        )
    ).scalars():
        payload = _scrub(row.payload_diff, pattern)
        if payload != row.payload_diff:
            row.payload_diff = payload
            scrubbed["audit_events"] += 1
    for note in (
        await db.execute(
            select(Notification).where(
                Notification.tenant_id == tenant_id,
                _mentions(Notification.context, needles),
            )
        )
    ).scalars():
        context = _scrub(note.context, pattern)
        if context != note.context:
            note.context = context
            scrubbed["notifications"] += 1
    for mail in (
        await db.execute(
            select(EmailLog).where(
                EmailLog.tenant_id == tenant_id,
                or_(
                    _mentions(EmailLog.recipient, needles),
                    _mentions(EmailLog.subject, needles),
                ),
            )
        )
    ).scalars():
        recipient_hit = pattern.search(mail.recipient) is not None
        subject = _scrub(mail.subject, pattern)
        if recipient_hit or subject != mail.subject:
            if recipient_hit:
                mail.recipient = _redacted_email()
            mail.subject = subject
            scrubbed["email_logs"] += 1
    return scrubbed


async def _refuse_while_processing(
    db: AsyncSession, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> None:
    """409 while a worker holds the candidate's data: it would write the
    transcript or the AI texts back after the erasure. Queued jobs are
    stopped by the withdrawn consent instead."""
    cv_ids = select(CandidateVacancy.id).where(
        CandidateVacancy.tenant_id == tenant_id,
        CandidateVacancy.candidate_id == candidate_id,
    )
    busy = await db.scalar(
        select(Interview.id)
        .where(
            Interview.tenant_id == tenant_id,
            Interview.candidate_vacancy_id.in_(cv_ids),
            or_(
                Interview.transcription_status == "processing",
                Interview.analysis_status == "processing",
            ),
        )
        .limit(1)
    )
    if busy is None:
        busy = await db.scalar(
            select(AIAnalysisRun.id)
            .where(
                AIAnalysisRun.tenant_id == tenant_id,
                AIAnalysisRun.candidate_vacancy_id.in_(cv_ids),
                AIAnalysisRun.status == "processing",
            )
            .limit(1)
        )
    if busy is not None:
        raise AppError("gdpr_erasure_in_progress", status.HTTP_409_CONFLICT)


async def gdpr_erase(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> GDPRErasureLog:
    """Soft-erase a candidate's PII synchronously.

    Unlike ``gdpr_export`` (offloaded to Celery), erasure runs inline on
    purpose: the "right to be forgotten" acknowledgement returned to the
    controller must not precede the actual redaction. Volumes are bounded
    (one candidate's rows + a handful of S3 blobs), so the request budget
    holds. Keeping it synchronous also removes any window where PII still
    exists after the API reported success.

    Only this tenant's data changes (HRP-977): the global ``persons`` row
    is wiped only when nothing else points at it; otherwise this tenant's
    candidate is unlinked from it. HRP-978: AI texts, evaluator notes,
    reports, export files and the candidate's copies in the audit trail,
    notifications and email log go too. Review 05.10: the candidate's
    consent is withdrawn, and the erasure is refused (409) while a
    transcription or AI analysis of the candidate is running.
    """

    candidate = await db.get(Candidate, candidate_id)
    if candidate is None or candidate.tenant_id != tenant_id:
        raise AppError("candidate_not_found", status.HTTP_404_NOT_FOUND)
    await _refuse_while_processing(db, tenant_id, candidate.id)

    person = await db.get(Person, candidate.person_id) if candidate.person_id else None
    affected: dict[str, int] = {}
    file_ids: set[uuid.UUID] = set()
    keys: set[str] = set()

    consents = list(
        (
            await db.execute(
                select(ConsentRequest).where(
                    ConsentRequest.tenant_id == tenant_id,
                    ConsentRequest.candidate_id == candidate.id,
                )
            )
        ).scalars()
    )
    names: list[str | None] = [candidate.full_name]
    emails: list[str | None] = [candidate.email, *(c.email for c in consents)]
    phones: list[str | None] = [candidate.phone]
    if person is not None:
        names.append(f"{person.first_name} {person.last_name}")
        emails.append(person.email)
        phones.append(person.phone)
    needles = _pii_needles(names, emails, phones)

    if person is not None:
        if await _person_is_shared(db, person.id, candidate.id):
            candidate.person = None
            candidate.person_id = None
            affected["person_unlinked"] = 1
        else:
            person.first_name = "redacted"
            person.last_name = "redacted"
            person.middle_name = None
            person.email = _redacted_email()
            person.phone = None
            affected["person"] = 1

    # HRP-181 REDO: redact the denormalised canonical Candidate PII
    # columns. Keep ``full_name`` non-empty (NOT NULL column) and use a
    # unique placeholder email so the partial unique index on
    # ``(tenant_id, lower(email))`` stays satisfiable across re-imports.
    candidate.full_name = "redacted"
    candidate.email = _redacted_email()
    candidate.phone = None
    candidate.linkedin_url = None
    candidate.location = None
    candidate.current_position = None
    candidate.years_of_experience = None
    candidate.parsed_resume_jsonb = dict(REDACTED_MARK)
    candidate.notes = None
    affected["candidate"] = 1

    cvs = list(
        (
            await db.execute(
                select(CandidateVacancy).where(
                    CandidateVacancy.tenant_id == tenant_id,
                    CandidateVacancy.candidate_id == candidate.id,
                )
            )
        ).scalars()
    )
    cv_ids = [cv.id for cv in cvs]
    for cv in cvs:
        cv.ai_verdict_summary = None
        cv.ai_key_strength = None
        cv.ai_key_risk = None
        cv.ai_risk_mitigation = None
        # Stage-change comments are free text about the candidate.
        cv.status_history = [
            {**entry, "comment": None}
            if isinstance(entry, dict) and entry.get("comment")
            else entry
            for entry in (cv.status_history or [])
        ]

    interviews = list(
        (
            await db.execute(
                select(Interview).where(
                    Interview.tenant_id == tenant_id,
                    Interview.candidate_vacancy_id.in_(cv_ids),
                )
            )
        ).scalars()
    )
    for iv in interviews:
        iv.title = None
        iv.notes = None
        # Closes the upload gate, as a withdrawal does.
        iv.consent_signed_at = None
        iv.consent_template_id = None
    affected.update(
        {"interviews": 0, "interview_segments": 0, "ai_assessments": 0}
        | await _erase_interviews(db, tenant_id, interviews, file_ids, keys)
    )
    affected["ai_analysis_runs"] = await _redact_runs(
        db, tenant_id, AIAnalysisRun.candidate_vacancy_id.in_(cv_ids)
    )
    # Cache rows of earlier transcripts or profile versions: their key no
    # longer matches anything ``_erase_interviews`` can recompute.
    await db.execute(
        delete(InterviewAnalysisCache).where(
            InterviewAnalysisCache.tenant_id == tenant_id,
            InterviewAnalysisCache.candidate_vacancy_id.in_(cv_ids),
        )
    )

    # HRP-181 REDO: delete the actual S3 blobs (resume PDFs, interview
    # media) — blanking raw_text without removing the object lets any
    # presigned URL still hand out the original file.
    files = list(
        (
            await db.execute(
                select(CandidateFile).where(
                    CandidateFile.tenant_id == tenant_id,
                    CandidateFile.candidate_id == candidate.id,
                )
            )
        ).scalars()
    )
    affected["resumes"] = _erase_files(files, file_ids)

    # Human assessments — comment is free text and may quote the candidate.
    ha = await db.execute(
        update(HumanAssessment)
        .where(
            HumanAssessment.tenant_id == tenant_id,
            HumanAssessment.candidate_vacancy_id.in_(cv_ids),
        )
        .values(comment=REDACTED_TEXT)
        .execution_options(synchronize_session=False)
    )
    affected["human_assessments"] = ha.rowcount  # type: ignore[attr-defined]

    # Evaluator notes on the manager-assessment sheets (HRP-978).
    round_ids = select(AssessmentRound.id).where(
        AssessmentRound.tenant_id == tenant_id,
        AssessmentRound.candidate_vacancy_id.in_(cv_ids),
    )
    sheet_ids = select(RecruitmentAssessment.id).where(
        RecruitmentAssessment.tenant_id == tenant_id,
        RecruitmentAssessment.round_id.in_(round_ids),
    )
    invite_ids = select(AssessmentInvite.id).where(
        AssessmentInvite.tenant_id == tenant_id,
        AssessmentInvite.candidate_vacancy_id.in_(cv_ids),
    )
    sheets = await db.execute(
        update(RecruitmentAssessment)
        .where(RecruitmentAssessment.id.in_(sheet_ids))
        .values(final_notes=None)
        .execution_options(synchronize_session=False)
    )
    for score_model in (AssessmentCompetenceScore, AssessmentIndicatorScore):
        await db.execute(
            update(score_model)
            .where(score_model.assessment_id.in_(sheet_ids))
            .values(comment=None)
            .execution_options(synchronize_session=False)
        )
    await db.execute(
        update(AssessmentRound)
        .where(AssessmentRound.id.in_(round_ids))
        .values(archived_reason=None)
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        update(AssessmentInvite)
        .where(AssessmentInvite.id.in_(invite_ids))
        .values(personal_message=None)
        .execution_options(synchronize_session=False)
    )
    affected["evaluator_sheets"] = sheets.rowcount  # type: ignore[attr-defined]

    # Generated questions quote the resume and name prior employers.
    q = await db.execute(
        update(CandidateQuestion)
        .where(
            CandidateQuestion.tenant_id == tenant_id,
            CandidateQuestion.candidate_id == candidate.id,
        )
        .values(
            question_text=REDACTED_TEXT,
            good_answer=REDACTED_TEXT,
            acceptable_answer=REDACTED_TEXT,
            poor_answer=REDACTED_TEXT,
            resume_fragment=None,
            purpose="redacted",
        )
        .execution_options(synchronize_session=False)
    )
    affected["questions"] = q.rowcount  # type: ignore[attr-defined]
    set_ids = select(QuestionSet.id).where(
        QuestionSet.tenant_id == tenant_id,
        QuestionSet.candidate_vacancy_id.in_(cv_ids),
    )
    await db.execute(
        update(QuestionSet)
        .where(QuestionSet.id.in_(set_ids))
        .values(coverage_note=None)
        .execution_options(synchronize_session=False)
    )
    qs = await db.execute(
        update(Question)
        .where(Question.tenant_id == tenant_id, Question.question_set_id.in_(set_ids))
        .values(
            text=REDACTED_TEXT,
            resume_anchor_jsonb=None,
            expected_answer_indicators=None,
            follow_ups=None,
            rationale=None,
        )
        .execution_options(synchronize_session=False)
    )
    affected["question_set_questions"] = qs.rowcount  # type: ignore[attr-defined]

    affected["consent_requests"] = _erase_consents(consents, revoke=True)

    # Consolidated reports that list the candidate: no whitelist means
    # "every active candidate of the vacancy".
    my_cvs = {str(i) for i in cv_ids}
    reports = [
        r
        for r in (
            await db.execute(
                select(ConsolidatedReport).where(
                    ConsolidatedReport.tenant_id == tenant_id,
                    ConsolidatedReport.vacancy_id.in_([cv.vacancy_id for cv in cvs]),
                )
            )
        ).scalars()
        if (wl := (r.report_data or {}).get("candidate_vacancy_ids")) is None
        or my_cvs & set(wl)
    ]
    report_ids = [r.id for r in reports]
    affected["reports"] = await _delete_reports(db, reports, file_ids)

    exports = list(
        (
            await db.execute(
                select(GDPRExportRequest).where(
                    GDPRExportRequest.tenant_id == tenant_id,
                    GDPRExportRequest.subject_id == candidate.id,
                )
            )
        ).scalars()
    )
    affected["export_files"] = _drop_export_files(exports, file_ids)

    affected.update(
        await _scrub_logs(
            db,
            tenant_id,
            needles,
            [
                [candidate.id, *cv_ids, *report_ids],
                [c.id for c in consents],
                [f.id for f in files],
                [iv.id for iv in interviews],
                [e.id for e in exports],
                select(AIAnalysisRun.id).where(
                    AIAnalysisRun.tenant_id == tenant_id,
                    AIAnalysisRun.candidate_vacancy_id.in_(cv_ids),
                ),
                select(HumanAssessment.id).where(
                    HumanAssessment.tenant_id == tenant_id,
                    HumanAssessment.candidate_vacancy_id.in_(cv_ids),
                ),
                round_ids,
                sheet_ids,
                invite_ids,
                set_ids,
            ],
        )
    )

    affected.update(await _drop_storage(db, tenant_id, file_ids, keys))

    log_row = GDPRErasureLog(
        tenant_id=tenant_id,
        requested_by=user_id,
        subject_type="candidate",
        subject_id=candidate.id,
        affected=affected,
    )
    db.add(log_row)
    await db.commit()
    await db.refresh(log_row)
    return log_row


# ─── Retention sweep (HRP-983) ───────────────────────────────────────


async def _redact_resume_derivatives(
    db: AsyncSession, tenant_id: uuid.UUID, candidate_ids: set[uuid.UUID]
) -> int:
    """What was computed from the resumes of candidates who have none left:
    resume-only AI runs (and the card mirror of an active one), resume
    quotes of generated questions and resume anchors of question sets."""
    cv_ids = select(CandidateVacancy.id).where(
        CandidateVacancy.tenant_id == tenant_id,
        CandidateVacancy.candidate_id.in_(candidate_ids),
    )
    runs = await _redact_runs(
        db,
        tenant_id,
        AIAnalysisRun.candidate_vacancy_id.in_(cv_ids)
        & AIAnalysisRun.interview_id.is_(None)
        & _not_redacted(AIAnalysisRun.analysis_data),
    )
    await db.execute(
        update(CandidateQuestion)
        .where(
            CandidateQuestion.tenant_id == tenant_id,
            CandidateQuestion.candidate_id.in_(candidate_ids),
            CandidateQuestion.resume_fragment.is_not(None),
        )
        .values(resume_fragment=None)
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        update(Question)
        .where(
            Question.tenant_id == tenant_id,
            Question.question_set_id.in_(
                select(QuestionSet.id).where(
                    QuestionSet.tenant_id == tenant_id,
                    QuestionSet.candidate_vacancy_id.in_(cv_ids),
                )
            ),
            Question.resume_anchor_jsonb.is_not(None),
        )
        .values(resume_anchor_jsonb=None)
        .execution_options(synchronize_session=False)
    )
    return runs


@dataclass(frozen=True)
class _RetentionWindows:
    """Plain copy of a retention row: a rollback expires ORM objects, and
    reading an expired attribute in async code raises MissingGreenlet."""

    config_id: uuid.UUID
    tenant_id: uuid.UUID
    interviews_days: int
    resumes_days: int
    consents_days: int
    reports_days: int


# Rows of one type erased per transaction: a tenant's first run after
# years of data must not hold every row (and its blobs) in one session.
_RETENTION_BATCH = 200


async def _apply_tenant_retention(
    db: AsyncSession, cfg: _RetentionWindows, now: datetime
) -> dict[str, int]:
    """Erase what is due in batches, a commit per batch, under one log row.

    Each batch picks only rows not yet emptied, so the loop ends when a
    batch comes back short.
    """
    totals: dict[str, int] = {}
    log_id: uuid.UUID | None = None
    while True:
        batch, log_id = await _retention_batch(db, cfg, now, log_id)
        for key, n in batch.items():
            totals[key] = totals.get(key, 0) + n
        if log_id is not None and batch:
            await db.execute(
                update(GDPRErasureLog)
                .where(GDPRErasureLog.id == log_id)
                .values(affected=dict(totals))
            )
        await db.commit()
        if all(
            batch.get(key, 0) < _RETENTION_BATCH
            for key in ("interviews", "resumes", "consent_requests", "reports")
        ):
            return totals


async def _retention_batch(
    db: AsyncSession,
    cfg: _RetentionWindows,
    now: datetime,
    log_id: uuid.UUID | None,
) -> tuple[dict[str, int], uuid.UUID | None]:
    tenant_id = cfg.tenant_id

    async def due(model: Any, days: int, *extra: Any) -> list[Any]:
        return list(
            (
                await db.execute(
                    select(model)
                    .where(
                        model.tenant_id == tenant_id,
                        model.created_at < now - timedelta(days=days),
                        *extra,
                    )
                    .order_by(model.created_at)
                    .limit(_RETENTION_BATCH)
                )
            ).scalars()
        )

    interviews = await due(
        Interview,
        cfg.interviews_days,
        _not_redacted(Interview.analysis_data),
        # A worker mid-run would write the transcript or analysis back;
        # such an interview waits for the next night.
        Interview.transcription_status != "processing",
        Interview.analysis_status != "processing",
    )
    resumes = await due(
        CandidateFile,
        cfg.resumes_days,
        CandidateFile.file_type == "resume",
        _not_redacted(CandidateFile.parsed_data),
    )
    consents = await due(
        ConsentRequest,
        cfg.consents_days,
        ~ConsentRequest.email.like("redacted-%@local"),
    )
    reports = await due(ConsolidatedReport, cfg.reports_days)
    affected = {
        "interviews": len(interviews),
        "resumes": len(resumes),
        "consent_requests": len(consents),
        "reports": len(reports),
    }
    if not any(affected.values()):
        return {}, log_id

    if log_id is None:
        # Logged before anything is erased, like a GDPR erase.
        log_row = GDPRErasureLog(
            tenant_id=tenant_id,
            requested_by=None,
            subject_type="retention",
            subject_id=cfg.config_id,
            affected=dict(affected),
        )
        db.add(log_row)
        await db.flush()
        log_id = log_row.id

    file_ids: set[uuid.UUID] = set()
    keys: set[str] = set()
    affected.update(await _erase_interviews(db, tenant_id, interviews, file_ids, keys))
    _erase_files(resumes, file_ids)
    # The card's parsed-resume copy goes with the candidate's last resume.
    touched = {r.candidate_id for r in resumes if r.candidate_id is not None}
    if touched:
        await db.flush()
        live = set(
            (
                await db.execute(
                    select(CandidateFile.candidate_id).where(
                        CandidateFile.tenant_id == tenant_id,
                        CandidateFile.candidate_id.in_(touched),
                        CandidateFile.file_type == "resume",
                        _not_redacted(CandidateFile.parsed_data),
                    )
                )
            ).scalars()
        )
        if gone := touched - live:
            await db.execute(
                update(Candidate)
                .where(Candidate.id.in_(gone))
                .values(parsed_resume_jsonb=null())
                .execution_options(synchronize_session=False)
            )
            affected["resume_derivatives"] = await _redact_resume_derivatives(
                db, tenant_id, gone
            )
    _erase_consents(consents)
    await _delete_reports(db, reports, file_ids)
    affected.update(await _drop_storage(db, tenant_id, file_ids, keys))
    return affected, log_id


async def _expire_export_files(db: AsyncSession, now: datetime) -> int:
    """HRP-978: an export file outlives its download link by nothing."""
    exports = list(
        (
            await db.execute(
                select(GDPRExportRequest).where(
                    GDPRExportRequest.file_id.is_not(None),
                    GDPRExportRequest.expires_at < now,
                )
            )
        ).scalars()
    )
    for tenant_id in {e.tenant_id for e in exports}:
        file_ids: set[uuid.UUID] = set()
        _drop_export_files([e for e in exports if e.tenant_id == tenant_id], file_ids)
        await _drop_storage(db, tenant_id, file_ids)
    await db.commit()
    return len(exports)


async def apply_retention(
    db: AsyncSession, *, now: datetime | None = None
) -> dict[str, int]:
    """Apply each tenant's recruitment retention settings (daily beat task).

    An object is due once its ``created_at`` is older than the tenant's
    window for its type. Interviews lose media, transcript and AI
    analysis; resumes lose the file and the parsed text; consent requests
    lose the signer's email, IP and browser (status and dates stay as
    proof of consent); reports are deleted. Rows that a GDPR erase or an
    earlier run already emptied are skipped. Each tenant run that erases
    anything writes a ``gdpr_erasure_log`` row first. The recruitment
    audit log is out of scope by decision (HRP-983). Expired GDPR export
    files are deleted too (HRP-978), and so are the blobs earlier runs or
    erasures queued in ``gdpr_pending_blob_deletes`` when the storage
    refused them.

    Tenants without a retention row are left alone: the row appears the
    first time the settings are opened.
    """
    now = now or datetime.now(timezone.utc)
    totals: dict[str, int] = {}
    configs = [
        _RetentionWindows(
            config_id=c.id,
            tenant_id=c.tenant_id,
            interviews_days=c.interviews_days,
            resumes_days=c.resumes_days,
            consents_days=c.consents_days,
            reports_days=c.reports_days,
        )
        for c in (await db.execute(select(RecruitmentRetentionConfig))).scalars()
    ]
    for cfg in configs:
        tenant_id = cfg.tenant_id
        try:
            done = await _apply_tenant_retention(db, cfg, now)
        except Exception:  # noqa: BLE001 — one tenant must not stall the rest
            logger.exception("recruitment retention failed for tenant %s", tenant_id)
            await db.rollback()
            continue
        for key, n in done.items():
            totals[key] = totals.get(key, 0) + n
    totals["export_files"] = await _expire_export_files(db, now)
    totals["pending_blobs_deleted"] = await _retry_pending_blob_deletes(db)
    return totals


async def list_export_requests(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    candidate_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[GDPRExportRequest]:
    q = select(GDPRExportRequest).where(GDPRExportRequest.tenant_id == tenant_id)
    if candidate_id:
        q = q.where(GDPRExportRequest.subject_id == candidate_id)
    q = q.order_by(GDPRExportRequest.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


def export_to_read(req: GDPRExportRequest, file_url: str | None = None) -> dict:
    return {
        "id": req.id,
        "subject_type": req.subject_type,
        "subject_id": req.subject_id,
        "status": req.status,
        "file_url": file_url,
        "expires_at": req.expires_at,
        "requested_by": req.requested_by,
        "error": req.error,
        "created_at": req.created_at,
    }


async def resolve_export_url(
    db: AsyncSession, tenant_id: uuid.UUID, req: GDPRExportRequest
) -> str | None:
    if req.file_id is None:
        return None
    file_row = await db.get(File, req.file_id)
    if file_row is None or file_row.tenant_id != tenant_id:
        return None
    return get_presigned_url(file_row.path, expires_in=EXPORT_PRESIGN_TTL_SECONDS)
