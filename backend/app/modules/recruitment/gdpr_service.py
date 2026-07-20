"""GDPR export & erasure (R4b, §9.2). 72h SLA target.

Export gathers everything we hold for a candidate (person, candidate,
resumes, candidate_vacancies, questions, assessments, interviews,
segments, consents, references to reports) into a single JSON document,
uploads it to S3 under ``gdpr_exports/{tenant_id}/{request_id}.json`` and
returns a presigned URL valid for 7 days.

Erasure is intentionally *soft*: PII fields are redacted in place and an
audit-trail row is added to ``gdpr_erasure_log`` so the company can prove
to regulators when the request was honoured.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.s3 import delete_file as s3_delete_file
from app.core.s3 import get_presigned_url, upload_file
from app.models import Person
from app.modules.recruitment.models import (
    AIAssessment,
    Candidate,
    CandidateFile,
    CandidateQuestion,
    CandidateVacancy,
    ConsentRequest,
    GDPRErasureLog,
    GDPRExportRequest,
    HumanAssessment,
    Interview,
    InterviewSegment,
)
from app.modules.recruitment.settings_schemas import GDPRExportRequestCreate
from app.modules.storage.models import File

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
    }


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
        "person_id": str(c.person_id),
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")

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

    try:
        payload = await _gather_candidate_payload(db, tenant_id, candidate)
        # default=str so datetime / UUID values inside ``parsed_data`` JSON
        # blobs (which we accept as arbitrary dicts from third-party
        # resume parsers) don't break the dump on TypeError.
        body = json.dumps(
            payload, ensure_ascii=False, indent=2, default=str
        ).encode("utf-8")
        path = f"gdpr_exports/{tenant_id}/{request_row.id}.json"

        file_row: File | None = None
        if settings.s3_endpoint:
            upload_result = upload_file(body, path, "application/json")
            if upload_result is None:
                request_row.status = "failed"
                request_row.error = "S3 upload failed"
                await db.commit()
                return {"status": "failed", "request_id": str(request_id)}

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
        request_row = await db.get(GDPRExportRequest, request_id)
        if request_row is not None:
            request_row.status = "failed"
            request_row.error = str(exc)[:500]
            await db.commit()
        return {"status": "failed", "request_id": str(request_id)}


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
    """

    candidate = await db.get(Candidate, candidate_id)
    if candidate is None or candidate.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")

    person = await db.get(Person, candidate.person_id) if candidate.person_id else None
    affected: dict[str, int] = {}

    if person is not None:
        person.first_name = "redacted"
        person.last_name = "redacted"
        person.middle_name = None
        person.email = f"redacted-{uuid.uuid4().hex[:12]}@local"
        person.phone = None
        affected["person"] = 1

    # HRP-181 REDO: redact the denormalised canonical Candidate PII
    # columns. Externally-sourced rows have person_id=None — without this
    # block their full_name/email/phone/parsed resume keep PII verbatim
    # after erase. Keep ``full_name`` non-empty (NOT NULL column) and
    # use a unique placeholder email so the partial unique index on
    # ``(tenant_id, lower(email))`` stays satisfiable across re-imports.
    candidate.full_name = "redacted"
    candidate.email = f"redacted-{uuid.uuid4().hex[:12]}@local"
    candidate.phone = None
    candidate.linkedin_url = None
    candidate.location = None
    candidate.current_position = None
    candidate.years_of_experience = None
    candidate.parsed_resume_jsonb = {"redacted": True}
    affected["candidate"] = 1

    # HRP-181 REDO: delete the actual S3 blobs (resume PDFs, interview
    # audio/video/transcripts) — blanking raw_text without removing the
    # underlying object lets any presigned URL still hand out the
    # original file.
    res_q = await db.execute(
        select(CandidateFile).where(
            CandidateFile.tenant_id == tenant_id, CandidateFile.candidate_id == candidate.id
        )
    )
    resumes = list(res_q.scalars().all())
    storage_file_ids: set[uuid.UUID] = set()
    for r in resumes:
        r.raw_text = None
        r.parsed_data = {"redacted": True}
        r.original_filename = "redacted.pdf"
        if r.file_id:
            storage_file_ids.add(r.file_id)
        r.file_id = None
    affected["resumes"] = len(resumes)

    cv_q = await db.execute(
        select(CandidateVacancy).where(
            CandidateVacancy.tenant_id == tenant_id,
            CandidateVacancy.candidate_id == candidate.id,
        )
    )
    cv_ids = [cv.id for cv in cv_q.scalars().all()]

    interviews: list[Interview] = []
    segments_count = 0
    ai_assessments_count = 0
    human_assessments_count = 0
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
            iv.transcript = "[redacted]"
            iv.notes = None
            iv.analysis_data = {"redacted": True}
            # HRP-181 REDO: drop file references on Interview so the
            # presigner can't surface the original media. The actual
            # storage rows are deleted below in the storage cleanup loop.
            for fk in (iv.audio_file_id, iv.video_file_id, iv.transcript_file_id):
                if fk:
                    storage_file_ids.add(fk)
            iv.audio_file_id = None
            iv.video_file_id = None
            iv.transcript_file_id = None
            iv.file_s3_key = None
            for seg in iv.segments:
                seg.text = "[redacted]"
                segments_count += 1

        # Human assessments — comment is free text and may quote the
        # candidate ("She said her last manager was abusive…"), so it
        # must be redacted alongside the resume/interview content.
        ha_q = await db.execute(
            select(HumanAssessment).where(
                HumanAssessment.tenant_id == tenant_id,
                HumanAssessment.candidate_vacancy_id.in_(cv_ids),
            )
        )
        for ha in ha_q.scalars().all():
            ha.comment = "[redacted]"
            human_assessments_count += 1

        # AI assessments — reasoning quotes the transcript verbatim and
        # citations carry timestamps that map back to the redacted
        # segments; both must be cleared.
        if interviews:
            ai_q = await db.execute(
                select(AIAssessment).where(
                    AIAssessment.tenant_id == tenant_id,
                    AIAssessment.interview_id.in_([i.id for i in interviews]),
                )
            )
            for ai in ai_q.scalars().all():
                ai.reasoning = "[redacted]"
                ai.citations = []
                ai_assessments_count += 1
    affected["interviews"] = len(interviews)
    affected["interview_segments"] = segments_count
    affected["human_assessments"] = human_assessments_count
    affected["ai_assessments"] = ai_assessments_count

    # Generated questions can include role-specific or sensitive answer
    # templates that name the candidate's prior employers / skills.
    q_q = await db.execute(
        select(CandidateQuestion).where(
            CandidateQuestion.tenant_id == tenant_id,
            CandidateQuestion.candidate_id == candidate.id,
        )
    )
    questions_count = 0
    for q in q_q.scalars().all():
        q.good_answer = "[redacted]"
        q.acceptable_answer = "[redacted]"
        q.poor_answer = "[redacted]"
        q.purpose = "redacted"
        questions_count += 1
    affected["questions"] = questions_count

    cons_q = await db.execute(
        select(ConsentRequest).where(
            ConsentRequest.tenant_id == tenant_id,
            ConsentRequest.candidate_id == candidate.id,
        )
    )
    consents = list(cons_q.scalars().all())
    for c in consents:
        c.email = f"redacted-{uuid.uuid4().hex[:12]}@local"
        c.signed_ip = None
        c.signed_user_agent = None
    affected["consent_requests"] = len(consents)

    candidate.notes = None

    # HRP-181 REDO: drop the underlying storage.File rows and S3 objects
    # collected above. Best-effort on S3 — log + continue so a missing
    # blob doesn't block the erasure audit.
    storage_objects_deleted = 0
    if storage_file_ids:
        import contextlib

        files_q = await db.execute(
            select(File).where(File.id.in_(list(storage_file_ids)))
        )
        for file_row in files_q.scalars().all():
            if file_row.tenant_id != tenant_id:
                continue
            if settings.s3_endpoint and file_row.path:
                # Best-effort: a missing blob must not block the erasure
                # audit row.
                with contextlib.suppress(Exception):
                    s3_delete_file(file_row.path)
            await db.delete(file_row)
            storage_objects_deleted += 1
    affected["storage_files"] = storage_objects_deleted

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
