"""Interview service — schedule, chunked upload, transcript, AV scan.

Extracted from ``service.py`` during the M-5 split (R4d) and extended in
HRP-202 (interview upload overhaul). Re-exports back into ``service``
are provided by a module ``__getattr__`` in ``service.py`` so legacy
callers using ``service.create_interview(...)`` continue to resolve to
the (potentially billing-wrapped) function in this module.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import status
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError

# Role constants live in recruitment.common because resolve_user_role()
# (also kept there) shares them with compare_candidates. Import here to
# keep the RBAC filter local to interview reads.
from app.modules.recruitment.common import _FULL_ROLES, _HM_ROLES, _publish_event
from app.modules.recruitment.models import (
    AIAssessment,
    Candidate,
    CandidateVacancy,
    Interview,
    InterviewInterviewer,
    InterviewSegment,
    UploadSession,
)
from app.modules.recruitment.schemas import (
    AbortUploadRequest,
    CompleteUploadRequest,
    InitUploadRequest,
    InterviewArchiveRequest,
    InterviewCreate,
    InterviewSegmentUpdate,
    InterviewUpdate,
    PartUrlRequest,
    TextTranscriptRequest,
    TranscriptUpdate,
    UploadChunkAck,
)
from app.modules.storage.models import File

logger = logging.getLogger(__name__)

# HRP-202: TUS-style upload sessions linger for 24h before the orphan
# cleanup task aborts the underlying S3 multipart and deletes the row.
UPLOAD_SESSION_TTL = timedelta(hours=24)

# Strict MIME allow-list per acceptance criteria. The frontend pre-checks
# this same set; the backend re-checks because client-side validation
# cannot be trusted.
_AUDIO_MIME = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mp4",
    "audio/x-m4a",
    "audio/m4a",
}
_VIDEO_MIME = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    # HRP-202 REDO: AVI recordings from legacy meeting-room hardware.
    "video/x-msvideo",
    "video/avi",
}
_TRANSCRIPT_MIME = {
    "application/pdf",
    "text/plain",
}

_MEDIA_MAX_BYTES = 500 * 1024 * 1024
_TRANSCRIPT_MAX_BYTES = 10 * 1024 * 1024

# Pre-signed playback URLs default to a short TTL so a leaked URL has
# narrow blast radius. The frontend auto-refreshes before expiry.
_SIGNED_URL_TTL = 300


def _kind_for_mime(mime: str) -> str | None:
    m = (mime or "").lower()
    if m in _AUDIO_MIME or m.startswith("audio/"):
        return "audio"
    if m in _VIDEO_MIME or m.startswith("video/"):
        return "video"
    if m in _TRANSCRIPT_MIME:
        return "text_transcript"
    return None


def _validate_upload_payload(
    mime: str, size_bytes: int, kind: str, *, is_demo: bool = False
) -> None:
    detected_kind = _kind_for_mime(mime)
    if detected_kind is None:
        raise AppError(
            "unsupported_mime_type",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            mime=mime,
        )
    if kind == "audio" and detected_kind != "audio":
        raise AppError(
            "kind_audio_requires_audio_mime",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if kind == "video" and detected_kind != "video":
        raise AppError(
            "kind_video_requires_video_mime",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    # HRP-253 (D5): demo sandbox is text-only. The killswitch from D4 also
    # replaces the AI output, but blocking media at the upload door means
    # we never even spend S3 bytes on a sandbox transcript request.
    # HRP-276 / L5: message text is neutral so the error doesn't double
    # as a "this is a demo tenant" oracle for unauthenticated probes.
    if is_demo and detected_kind != "text_transcript":
        raise AppError(
            "media_upload_not_allowed_for_account",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    if is_demo:
        from app.config import settings

        demo_limit = settings.demo_max_upload_mb * 1024 * 1024
        if size_bytes > demo_limit:
            raise AppError(
                "file_exceeds_upload_limit",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                max_mb=settings.demo_max_upload_mb,
            )
        return
    limit = (
        _TRANSCRIPT_MAX_BYTES
        if detected_kind == "text_transcript"
        else _MEDIA_MAX_BYTES
    )
    if size_bytes > limit:
        raise AppError(
            "file_exceeds_size_limit",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            max_mb=limit // (1024 * 1024),
        )


async def _enforce_demo_upload_quota(tenant_id: uuid.UUID) -> None:
    """HRP-253 (D5): per-session upload counter for demo tenants.

    Backed by ``demo:uploads:{tenant_id}`` in Redis with TTL anchored to
    the FIRST upload of the window so the counter expires together with
    the sandbox instead of sliding indefinitely. ``DEMO_QUOTA_UPLOADS ==
    0`` disables the cap. Redis errors degrade open — a flaky cache must
    not lock a paid tenant out of a feature it shares with demo via the
    same code path.
    """
    import contextlib

    import redis.asyncio as aioredis
    from redis.exceptions import RedisError

    from app.config import settings

    if settings.demo_quota_uploads <= 0:
        return
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        key = f"demo:uploads:{tenant_id}"
        async with client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            # ``nx=True`` makes EXPIRE a no-op when the key already has a
            # TTL, anchoring the window to the first upload so an
            # actively-retrying client can't push expiry out indefinitely.
            pipe.expire(key, settings.demo_session_ttl_seconds, nx=True)
            count, _ = await pipe.execute()
        if count > settings.demo_quota_uploads:
            raise AppError(
                "upload_quota_exhausted",
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
    except AppError:
        raise
    except (RedisError, ConnectionError, TimeoutError) as exc:
        # Narrow on purpose: a TypeError/ValueError out of the pipeline
        # unpack would mean a redis-py contract change, and silently
        # failing open across all demo tenants on that is worse than
        # surfacing the regression.
        logger.warning(
            "demo upload quota: redis unavailable, allowing tenant=%s (%s)",
            tenant_id,
            exc,
        )
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()  # type: ignore[attr-defined]


async def _get_interview_with_relations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    *,
    include_archived: bool = True,
) -> Interview:
    stmt = (
        select(Interview)
        .options(
            selectinload(Interview.segments),
            selectinload(Interview.interviewers),
        )
        .where(
            Interview.id == interview_id,
            Interview.tenant_id == tenant_id,
        )
    )
    if not include_archived:
        stmt = stmt.where(Interview.archived_at.is_(None))
    interview = (await db.execute(stmt)).scalar_one_or_none()
    if not interview:
        raise AppError("interview_not_found", status.HTTP_404_NOT_FOUND)
    return interview


def _role_filter_analysis(
    analysis_data: dict | None,
    role: str | None,
) -> dict | None:
    """Apply RBAC to the AI analysis payload (RECRUITING_MODULE.md §9.5)."""

    if analysis_data is None:
        return None

    role_norm = (role or "").lower()
    if role_norm in _FULL_ROLES:
        return analysis_data

    if role_norm in _HM_ROLES:
        out = dict(analysis_data)

        findings = out.get("process_findings") or []
        out["process_findings"] = [
            {
                "finding_type": f.get("finding_type"),
                "positive_reframe": f.get("positive_reframe"),
            }
            for f in findings
            if isinstance(f, dict) and f.get("positive_reframe")
        ]
        out.pop("red_flags", None)

        assessments = out.get("competence_assessments") or []
        trimmed: list[dict] = []
        for a in assessments:
            if not isinstance(a, dict):
                continue
            trimmed.append(
                {
                    "competence_id": a.get("competence_id"),
                    "score": a.get("score"),
                    "status": a.get("status"),
                    "citations": a.get("citations") or [],
                }
            )
        out["competence_assessments"] = trimmed
        return out

    return None


def _interview_to_read(
    interview: Interview,
    *,
    role: str | None = None,
    ai_assessments: list[AIAssessment] | None = None,
) -> dict:
    segments = sorted((interview.segments or []), key=lambda s: (s.start_sec, s.id))
    ai_payload: list[dict] = []
    if ai_assessments and (role or "").lower() != "invited_evaluator":
        for ai in ai_assessments:
            ai_payload.append(
                {
                    "id": ai.id,
                    "interview_id": ai.interview_id,
                    "competence_id": ai.competence_id,
                    "score": ai.score,
                    "status": ai.status,
                    "citations": ai.citations or [],
                    "reasoning": (
                        ai.reasoning if (role or "").lower() in _FULL_ROLES else None
                    ),
                }
            )

    interviewer_ids = [link.user_id for link in (interview.interviewers or [])]
    if interview.interviewer_id and interview.interviewer_id not in interviewer_ids:
        interviewer_ids.insert(0, interview.interviewer_id)

    return {
        "id": interview.id,
        "candidate_vacancy_id": interview.candidate_vacancy_id,
        "title": interview.title,
        "type": interview.type,
        "timezone": interview.timezone,
        "duration_minutes": interview.duration_minutes,
        "interviewer_id": interview.interviewer_id,
        "interviewer_ids": interviewer_ids,
        "interview_date": interview.interview_date,
        "duration_seconds": interview.duration_seconds,
        "audio_file_id": interview.audio_file_id,
        "video_file_id": interview.video_file_id,
        "transcript_file_id": interview.transcript_file_id,
        "file_s3_key": interview.file_s3_key,
        "file_size_bytes": interview.file_size_bytes,
        "file_mime": interview.file_mime,
        "transcript": interview.transcript,
        "notes": interview.notes,
        "status": interview.status,
        "av_status": interview.av_status,
        "av_scanned_at": interview.av_scanned_at,
        "version": interview.version,
        "archived_at": interview.archived_at,
        "created_by": interview.created_by,
        "transcription_provider": interview.transcription_provider,
        "transcription_status": interview.transcription_status,
        "analysis_status": interview.analysis_status,
        "transcription_error": interview.transcription_error,
        "analysis_error": interview.analysis_error,
        "auto_process": interview.auto_process,
        "consent_signed_at": interview.consent_signed_at,
        "consent_template_id": interview.consent_template_id,
        "segments": [
            {
                "id": s.id,
                "interview_id": s.interview_id,
                "speaker": s.speaker,
                "start_sec": s.start_sec,
                "end_sec": s.end_sec,
                "text": s.text,
                "confidence": s.confidence,
            }
            for s in segments
        ],
        "ai_assessments": ai_payload,
        "analysis": _role_filter_analysis(interview.analysis_data, role),
    }


def _parse_speaker_segments(text: str) -> list[dict]:
    """Parse ``Interviewer: …`` / ``Candidate: …`` speaker labels.

    HRP-202 acceptance: when a transcript is pasted or uploaded as text,
    speaker prefixes are extracted into ``InterviewSegment`` rows so the
    AI analysis stage gets structured input. Unlabelled lines collapse
    into the prior speaker's segment to keep the segment count sane.
    """

    speakers = {
        "interviewer": "speaker_0",
        "candidate": "speaker_1",
    }
    segments: list[dict] = []
    current_speaker = "speaker_0"
    current_text: list[str] = []

    def flush() -> None:
        nonlocal current_text
        if current_text:
            segments.append(
                {
                    "speaker": current_speaker,
                    "text": " ".join(current_text).strip(),
                }
            )
            current_text = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        head, sep, rest = line.partition(":")
        key = head.strip().lower()
        if sep and key in speakers:
            flush()
            current_speaker = speakers[key]
            if rest.strip():
                current_text.append(rest.strip())
        else:
            current_text.append(line)
    flush()
    return segments


async def create_interview(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    cv_id: uuid.UUID,
    data: InterviewCreate,
) -> dict:
    """Create an interview attached to a candidate-vacancy link.

    HRP-202: accepts the full Schedule modal payload — title, multiple
    interviewers, timezone, planned duration, type. Falls back to the
    legacy minimal R3a payload so existing callers keep working.
    """

    cv = (
        await db.execute(
            select(CandidateVacancy).where(
                CandidateVacancy.id == cv_id,
                CandidateVacancy.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not cv:
        raise AppError("candidate_vacancy_link_not_found", status.HTTP_404_NOT_FOUND)

    primary_interviewer = data.interviewer_id
    if not primary_interviewer and data.interviewers:
        primary_interviewer = data.interviewers[0]
    if not primary_interviewer:
        primary_interviewer = user_id

    # HRP-202 REDO: inherit the candidate's most recent *signed* consent.
    # ``sign_consent`` only back-fills interviews that existed at signing
    # time; without this, every interview created afterwards (e.g. the
    # bulk-upload flow, one row per file) would demand a fresh signature.
    from app.modules.recruitment.models import ConsentRequest

    signed_consent = (
        await db.execute(
            select(ConsentRequest)
            .where(
                ConsentRequest.candidate_id == cv.candidate_id,
                ConsentRequest.tenant_id == tenant_id,
                ConsentRequest.status == "signed",
            )
            .order_by(ConsentRequest.signed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    interview = Interview(
        tenant_id=tenant_id,
        candidate_vacancy_id=cv_id,
        title=data.title,
        type=data.type or "undecided",
        timezone=data.timezone,
        duration_minutes=data.duration_minutes,
        interviewer_id=primary_interviewer,
        interview_date=data.interview_date,
        notes=data.notes,
        created_by=user_id,
        status="scheduled",
        transcription_status="pending",
        analysis_status="pending",
        consent_signed_at=signed_consent.signed_at if signed_consent else None,
        consent_template_id=signed_consent.template_id if signed_consent else None,
    )
    db.add(interview)
    await db.flush()

    seen: set[uuid.UUID] = set()
    additional = list(data.interviewers or [])
    if primary_interviewer:
        additional = [primary_interviewer] + [
            u for u in additional if u != primary_interviewer
        ]
    for uid in additional:
        if uid in seen:
            continue
        seen.add(uid)
        db.add(
            InterviewInterviewer(
                tenant_id=tenant_id,
                interview_id=interview.id,
                user_id=uid,
            )
        )
    await db.commit()
    await db.refresh(interview, attribute_names=["segments", "interviewers"])

    cv_row = (
        await db.execute(
            select(CandidateVacancy)
            .options(
                selectinload(CandidateVacancy.candidate).selectinload(Candidate.person),
                selectinload(CandidateVacancy.vacancy),
            )
            .where(CandidateVacancy.id == cv_id)
        )
    ).scalar_one_or_none()
    candidate_name = None
    vacancy_title = None
    owner_id: uuid.UUID | None = None
    if cv_row:
        if cv_row.candidate and cv_row.candidate.person:
            p = cv_row.candidate.person
            candidate_name = f"{p.first_name} {p.last_name}".strip()
        if cv_row.vacancy:
            vacancy_title = cv_row.vacancy.title
            owner_id = cv_row.vacancy.owner_id
    await _publish_event(
        "recruitment.interview.scheduled",
        {
            "tenant_id": str(tenant_id),
            "interview_id": str(interview.id),
            "interviewer_id": (
                str(interview.interviewer_id) if interview.interviewer_id else None
            ),
            "owner_id": str(owner_id) if owner_id else None,
            "candidate_name": candidate_name,
            "vacancy_title": vacancy_title,
            "interview_date": (
                interview.interview_date.isoformat()
                if interview.interview_date
                else None
            ),
        },
    )
    return _interview_to_read(interview, role="recruiter")


async def update_interview(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    data: InterviewUpdate,
    *,
    if_match_version: int | None = None,
) -> dict:
    interview = await _get_interview_with_relations(db, tenant_id, interview_id)

    if if_match_version is not None and interview.version != if_match_version:
        raise AppError(
            "interview_version_conflict",
            status.HTTP_412_PRECONDITION_FAILED,
        )

    if data.title is not None:
        interview.title = data.title
    if data.interviewer_id is not None:
        interview.interviewer_id = data.interviewer_id
    if data.interview_date is not None:
        interview.interview_date = data.interview_date
    if data.timezone is not None:
        interview.timezone = data.timezone
    if data.duration_minutes is not None:
        interview.duration_minutes = data.duration_minutes
    if data.type is not None:
        interview.type = data.type
    if data.status is not None:
        interview.status = data.status
    if data.notes is not None:
        interview.notes = data.notes

    if data.interviewers is not None:
        await db.execute(
            delete(InterviewInterviewer).where(
                InterviewInterviewer.interview_id == interview.id
            )
        )
        seen: set[uuid.UUID] = set()
        for uid in data.interviewers:
            if uid in seen:
                continue
            seen.add(uid)
            db.add(
                InterviewInterviewer(
                    tenant_id=tenant_id,
                    interview_id=interview.id,
                    user_id=uid,
                )
            )

    interview.version = (interview.version or 1) + 1
    await db.commit()
    await db.refresh(interview, attribute_names=["segments", "interviewers"])
    return _interview_to_read(interview, role="recruiter")


async def list_interviews(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    cv_id: uuid.UUID,
    role: str | None = None,
    *,
    include_archived: bool = False,
) -> list[dict]:
    stmt = (
        select(Interview)
        .options(
            selectinload(Interview.segments),
            selectinload(Interview.interviewers),
        )
        .where(
            Interview.tenant_id == tenant_id,
            Interview.candidate_vacancy_id == cv_id,
        )
        .order_by(Interview.created_at.asc())
    )
    if not include_archived:
        stmt = stmt.where(Interview.archived_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    return [_interview_to_read(i, role=role) for i in rows]


async def get_interview(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    role: str | None = None,
) -> dict:
    interview = await _get_interview_with_relations(db, tenant_id, interview_id)
    ai_rows = (
        (
            await db.execute(
                select(AIAssessment).where(
                    AIAssessment.interview_id == interview_id,
                    AIAssessment.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return _interview_to_read(interview, role=role, ai_assessments=list(ai_rows))


async def update_transcript(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    data: TranscriptUpdate,
) -> dict:
    from app.core.pii_filter import redact_pii

    interview = await _get_interview_with_relations(db, tenant_id, interview_id)
    interview.transcript = redact_pii(data.transcript)
    await db.commit()
    await db.refresh(interview, attribute_names=["segments", "interviewers"])
    return _interview_to_read(interview, role="recruiter")


async def paste_text_transcript(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    data: TextTranscriptRequest,
) -> dict:
    """HRP-202: inline-paste a text transcript.

    Skips S3 entirely, stores the redacted text on the interview row,
    parses ``Interviewer:`` / ``Candidate:`` prefixes into
    ``InterviewSegment`` rows so the AI analysis stage gets structured
    input, and flips the interview into ``uploaded`` so the rest of the
    UI treats it the same way as a freshly-uploaded media file.
    """

    from app.core.pii_filter import redact_pii

    interview = await _get_interview_with_relations(db, tenant_id, interview_id)
    if interview.archived_at is not None:
        raise AppError("interview_archived", status.HTTP_409_CONFLICT)

    text = redact_pii(data.text)
    interview.transcript = text
    interview.type = "text_transcript"
    interview.status = "uploaded"
    interview.transcription_status = "completed"
    interview.av_status = "skipped"

    await db.execute(
        delete(InterviewSegment).where(
            InterviewSegment.interview_id == interview.id,
            InterviewSegment.tenant_id == tenant_id,
        )
    )

    cursor = 0.0
    for parsed in _parse_speaker_segments(text):
        segment_text = parsed["text"]
        if not segment_text:
            continue
        approx_seconds = max(1.0, len(segment_text.split()) / 2.5)
        db.add(
            InterviewSegment(
                tenant_id=tenant_id,
                interview_id=interview.id,
                speaker=parsed["speaker"],
                start_sec=cursor,
                end_sec=cursor + approx_seconds,
                text=segment_text,
            )
        )
        cursor += approx_seconds

    interview.version = (interview.version or 1) + 1
    await db.commit()
    await db.refresh(interview, attribute_names=["segments", "interviewers"])
    return _interview_to_read(interview, role="recruiter")


async def update_segment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    segment_id: uuid.UUID,
    data: InterviewSegmentUpdate,
) -> dict:
    from app.core.pii_filter import redact_pii

    segment = (
        await db.execute(
            select(InterviewSegment).where(
                InterviewSegment.id == segment_id,
                InterviewSegment.tenant_id == tenant_id,
                InterviewSegment.interview_id == interview_id,
            )
        )
    ).scalar_one_or_none()
    if not segment:
        raise AppError("interview_segment_not_found", status.HTTP_404_NOT_FOUND)

    if data.speaker is not None:
        segment.speaker = data.speaker
    if data.text is not None:
        segment.text = redact_pii(data.text)
    if data.start_sec is not None:
        segment.start_sec = data.start_sec
    if data.end_sec is not None:
        segment.end_sec = data.end_sec
    await db.commit()
    return {
        "id": segment.id,
        "interview_id": segment.interview_id,
        "speaker": segment.speaker,
        "start_sec": segment.start_sec,
        "end_sec": segment.end_sec,
        "text": segment.text,
        "confidence": segment.confidence,
    }


# ---------------------------------------------------------------------------
# Chunked upload (HRP-202: S3 multipart + TUS-style upload sessions)
# ---------------------------------------------------------------------------


def _interview_storage_key(tenant_id: uuid.UUID, interview_id: uuid.UUID) -> str:
    """Deterministic, tenant-prefixed S3 key for an interview's media.

    Each interview has at most one media file at a time. The
    ``<tenant>/…`` prefix is what enforces tenant isolation at the
    object-storage layer; never drop it.
    """

    return f"{tenant_id}/interviews/{interview_id}/upload"


async def init_interview_upload(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    data: InitUploadRequest,
    *,
    user_id: uuid.UUID | None = None,
) -> dict:
    """Create an S3 multipart upload and durable ``UploadSession`` row.

    The session row makes the upload resumable across page reloads and
    gives the orphan-cleanup task something concrete to abort against.
    """

    from app.core.s3 import DEFAULT_PART_SIZE, init_multipart_upload
    from app.modules.demo.utils import is_demo_tenant

    interview = await _get_interview_with_relations(db, tenant_id, interview_id)
    if interview.archived_at is not None:
        raise AppError("interview_archived", status.HTTP_409_CONFLICT)
    if interview.consent_signed_at is None:
        raise AppError("consent_required", status.HTTP_409_CONFLICT)
    is_demo = await is_demo_tenant(db, tenant_id)
    _validate_upload_payload(
        data.mime_type, data.size_bytes, data.kind, is_demo=is_demo
    )

    key = _interview_storage_key(tenant_id, interview_id)
    upload_id = init_multipart_upload(key, data.mime_type)
    if not upload_id:
        raise AppError(
            "object_storage_not_configured",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # Debit the demo quota AFTER S3 init succeeds — otherwise a transient
    # S3 503 would burn a slot for an upload that never happened.
    if is_demo:
        await _enforce_demo_upload_quota(tenant_id)

    part_size = DEFAULT_PART_SIZE
    total_parts = max(1, (data.size_bytes + part_size - 1) // part_size)

    session = UploadSession(
        tenant_id=tenant_id,
        interview_id=interview_id,
        filename=data.filename,
        mime_type=data.mime_type,
        kind=data.kind,
        total_size=data.size_bytes,
        uploaded_bytes=0,
        part_size=part_size,
        s3_upload_id=upload_id,
        s3_key=key,
        s3_parts=[],
        status="active",
        expires_at=datetime.now(timezone.utc) + UPLOAD_SESSION_TTL,
        created_by=user_id,
    )
    db.add(session)

    if interview.status == "scheduled":
        interview.status = "uploading"

    await db.commit()
    await db.refresh(session)

    return {
        "upload_id": upload_id,
        "session_id": session.id,
        "path": key,
        "part_size": part_size,
        "total_parts": int(total_parts),
    }


async def _get_active_session(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    upload_id: str,
) -> UploadSession | None:
    return (
        await db.execute(
            select(UploadSession).where(
                UploadSession.tenant_id == tenant_id,
                UploadSession.interview_id == interview_id,
                UploadSession.s3_upload_id == upload_id,
                UploadSession.status == "active",
            )
        )
    ).scalar_one_or_none()


async def get_upload_session_head(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    upload_id: str,
) -> dict:
    """TUS-style HEAD: return the offset for an in-flight upload."""

    await _get_interview_with_relations(db, tenant_id, interview_id)
    session = await _get_active_session(db, tenant_id, interview_id, upload_id)
    if not session:
        raise AppError("upload_session_not_found", status.HTTP_404_NOT_FOUND)
    return {
        "upload_offset": session.uploaded_bytes,
        "upload_length": session.total_size,
        "status": session.status,
        "parts": session.s3_parts,
        "expires_at": session.expires_at,
    }


async def ack_uploaded_chunk(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    upload_id: str,
    ack: UploadChunkAck,
) -> dict:
    """TUS-style PATCH companion: record one uploaded chunk.

    The bytes are PUT directly to S3 via the pre-signed URL returned by
    ``get_upload_part_url``; this endpoint just persists what landed so
    the next HEAD returns the correct offset and the cleanup task can
    tell active sessions from orphans.
    """

    await _get_interview_with_relations(db, tenant_id, interview_id)
    session = await _get_active_session(db, tenant_id, interview_id, upload_id)
    if not session:
        raise AppError("upload_session_not_found", status.HTTP_404_NOT_FOUND)
    if session.expires_at <= datetime.now(timezone.utc):
        session.status = "expired"
        await db.commit()
        raise AppError("upload_session_expired", status.HTTP_410_GONE)

    parts: list[dict] = list(session.s3_parts or [])
    parts = [p for p in parts if p.get("part_number") != ack.part_number]
    parts.append(
        {
            "part_number": ack.part_number,
            "etag": ack.etag,
            "size": ack.size,
        }
    )
    parts.sort(key=lambda p: p.get("part_number", 0))
    session.s3_parts = parts
    session.uploaded_bytes = sum(int(p.get("size", 0)) for p in parts)
    await db.commit()
    return {
        "upload_offset": session.uploaded_bytes,
        "upload_length": session.total_size,
        "part_number": ack.part_number,
    }


async def get_upload_part_url(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    data: PartUrlRequest,
) -> dict:
    """Sign a presigned URL for one part of an in-flight multipart upload."""

    from app.core.s3 import get_part_presigned_url

    await _get_interview_with_relations(db, tenant_id, interview_id)

    key = _interview_storage_key(tenant_id, interview_id)
    url = get_part_presigned_url(key, data.upload_id, data.part_number)
    if not url:
        raise AppError(
            "object_storage_not_configured",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return {
        "part_number": data.part_number,
        "url": url,
        "expires_in": 3600,
    }


async def complete_interview_upload(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    interview_id: uuid.UUID,
    data: CompleteUploadRequest,
    *,
    filename: str = "interview.bin",
    mime_type: str = "application/octet-stream",
    kind: str = "audio",
) -> dict:
    """Finalize an S3 multipart upload and attach the file to the interview."""

    from app.core.s3 import complete_multipart_upload, head_object
    from app.modules.demo.utils import is_demo_tenant

    if kind not in {"audio", "video", "text_transcript"}:
        raise AppError("invalid_upload_kind", status.HTTP_422_UNPROCESSABLE_ENTITY)

    # HRP-253 (D5): re-enforce the demo whitelist on complete — the init
    # gate alone is bypassable because S3 doesn't validate body-vs-mime
    # and the caller picks ``kind`` here independently from init.
    if await is_demo_tenant(db, tenant_id) and kind != "text_transcript":
        raise AppError(
            "media_upload_not_allowed_for_account",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    locked = await db.execute(
        select(Interview)
        .where(
            Interview.id == interview_id,
            Interview.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    interview = locked.scalar_one_or_none()
    if not interview:
        raise AppError("interview_not_found", status.HTTP_404_NOT_FOUND)
    if interview.archived_at is not None:
        raise AppError("interview_archived", status.HTTP_409_CONFLICT)
    if interview.consent_signed_at is None:
        raise AppError("consent_required", status.HTTP_409_CONFLICT)

    key = _interview_storage_key(tenant_id, interview_id)
    parts_payload = [{"PartNumber": p.part_number, "ETag": p.etag} for p in data.parts]
    location = complete_multipart_upload(key, data.upload_id, parts_payload)
    if not location:
        raise AppError(
            "object_storage_not_configured",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    head = head_object(key) or {}
    size = int(head.get("ContentLength") or 0)

    # HRP-276 / M8: re-validate size on complete for demo tenants.
    # init_interview_upload already enforces a per-part / total cap,
    # but S3 doesn't refuse parts that exceed it — the abuser can
    # finish a multipart upload above ``demo_max_upload_mb`` and the
    # init guard alone wouldn't catch it. Re-check here, delete the
    # now-finalized object so the blob isn't durably stored, and
    # raise 413. (``abort_multipart_upload`` is a no-op once the
    # upload has been completed — review found this on first pass —
    # so we issue an explicit ``delete_object`` instead.)
    if await is_demo_tenant(db, tenant_id):
        from app.config import settings
        from app.core.s3 import delete_file

        cap_bytes = settings.demo_max_upload_mb * 1024 * 1024
        if cap_bytes > 0 and size > cap_bytes:
            try:
                delete_file(key)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "demo: oversize cleanup delete_file failed for %s", key
                )
            raise AppError(
                "upload_exceeds_account_size_limit",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

    file_record = File(
        tenant_id=tenant_id,
        name=key.rsplit("/", 1)[-1],
        original_name=filename,
        path=key,
        size=size,
        mime_type=mime_type,
        uploaded_by=user_id,
        entity_type="interview",
        entity_id=interview_id,
    )
    db.add(file_record)
    await db.flush()

    if kind == "video":
        interview.video_file_id = file_record.id
    elif kind == "text_transcript":
        interview.transcript_file_id = file_record.id
    else:
        interview.audio_file_id = file_record.id
    interview.file_s3_key = key
    interview.file_size_bytes = size
    interview.file_mime = mime_type
    interview.type = kind if kind in {"audio", "video"} else "text_transcript"
    interview.status = "uploaded"
    interview.av_status = "pending"
    interview.transcription_status = "pending"
    interview.analysis_status = "pending"
    interview.auto_process = bool(data.auto_process) and kind in {"audio", "video"}

    # Mark the persistent upload-session as completed so the orphan-
    # cleanup task knows not to touch the now-finalized object.
    session = await _get_active_session(db, tenant_id, interview_id, data.upload_id)
    if session:
        session.status = "completed"

    # Probe duration so per-minute transcribe billing has an accurate
    # amount when the recruiter later clicks "Transcribe".
    if kind in {"audio", "video"}:
        import asyncio

        from app.modules.recruitment.media_duration import probe_s3_audio_duration

        probed = await asyncio.to_thread(probe_s3_audio_duration, key)
        if probed is not None and probed > 0:
            interview.duration_seconds = int(round(probed))

    interview.version = (interview.version or 1) + 1
    await db.commit()
    await db.refresh(interview, attribute_names=["segments", "interviewers"])

    # Best-effort AV-scan handoff. The Celery task is pluggable
    # (ClamAV stub by default) and the synchronous result of the .delay
    # call is not awaited.
    try:
        from app.modules.recruitment.tasks import scan_interview_media_task

        scan_interview_media_task.delay(str(interview_id), str(tenant_id))
    except Exception:
        logger.exception("Failed to enqueue AV scan for interview %s", interview_id)

    # HRP-202 REDO: auto-processing does NOT start here. Transcription is
    # chained from ``scan_interview_media_task`` once the AV verdict is
    # clean/skipped — starting it on upload-complete would race the malware
    # scan and could hand an infected recording to the ASR provider. The
    # persisted ``auto_process`` flag is the signal the AV task reads.

    return _interview_to_read(interview, role="recruiter")


async def get_interview_media_url(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    role: str | None = None,
    *,
    allow_invited_evaluator_playback: bool = False,
) -> dict:
    """Issue a short-lived presigned GET URL for the interview's media.

    Audio takes precedence over video. For ``invited_evaluator`` the URL
    is only emitted when the tenant has enabled invited-evaluator
    playback — and even then, the TTL stays at 5 minutes so a leaked URL
    has narrow blast radius. Download (long-lived) is never issued.
    """

    from app.core.s3 import get_presigned_url
    from app.modules.storage.models import File as FileModel

    role_norm = (role or "").lower()
    if role_norm == "invited_evaluator" and not allow_invited_evaluator_playback:
        raise AppError(
            "invited_evaluator_playback_disabled",
            status.HTTP_403_FORBIDDEN,
        )

    interview = await _get_interview_with_relations(db, tenant_id, interview_id)
    file_id = (
        interview.audio_file_id
        or interview.video_file_id
        or interview.transcript_file_id
    )
    if file_id is None:
        raise AppError("interview_has_no_media_file", status.HTTP_404_NOT_FOUND)

    file_record = (
        await db.execute(
            select(FileModel).where(
                FileModel.id == file_id,
                FileModel.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not file_record:
        raise AppError("interview_media_file_not_found", status.HTTP_404_NOT_FOUND)

    url = get_presigned_url(file_record.path, expires_in=_SIGNED_URL_TTL)
    if not url:
        raise AppError(
            "object_storage_not_configured",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if interview.audio_file_id == file_id:
        kind = "audio"
    elif interview.video_file_id == file_id:
        kind = "video"
    else:
        kind = "text_transcript"
    return {
        "url": url,
        "expires_in": _SIGNED_URL_TTL,
        "kind": kind,
        "mime_type": file_record.mime_type,
        "filename": file_record.original_name,
    }


async def abort_interview_upload(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    data: AbortUploadRequest,
) -> dict:
    from app.core.s3 import abort_multipart_upload

    interview = await _get_interview_with_relations(db, tenant_id, interview_id)
    key = _interview_storage_key(tenant_id, interview_id)
    abort_multipart_upload(key, data.upload_id)

    session = await _get_active_session(db, tenant_id, interview_id, data.upload_id)
    if session:
        session.status = "aborted"
    if interview.status == "uploading":
        interview.status = "upload_failed"
    await db.commit()
    return {"status": "aborted"}


async def replace_interview_file(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
) -> dict:
    """Detach the current media file so a new one can be uploaded.

    Drops the old transcript, segments and AI analysis because they are
    now stale — the UI shows a confirmation step before calling this.
    """

    from app.core.s3 import delete_file

    interview = await _get_interview_with_relations(db, tenant_id, interview_id)
    if interview.archived_at is not None:
        raise AppError("interview_archived", status.HTTP_409_CONFLICT)
    old_key = interview.file_s3_key

    interview.audio_file_id = None
    interview.video_file_id = None
    interview.transcript_file_id = None
    interview.file_s3_key = None
    interview.file_size_bytes = None
    interview.file_mime = None
    interview.transcript = None
    interview.av_status = "pending"
    interview.av_scanned_at = None
    interview.status = "scheduled"
    interview.transcription_status = "pending"
    interview.analysis_status = "pending"
    interview.analysis_data = None
    interview.duration_seconds = None
    # HRP-202 REDO: auto-processing was a per-upload decision; the next
    # upload makes its own.
    interview.auto_process = False

    await db.execute(
        delete(InterviewSegment).where(
            InterviewSegment.interview_id == interview.id,
            InterviewSegment.tenant_id == tenant_id,
        )
    )
    await db.execute(
        delete(AIAssessment).where(
            AIAssessment.interview_id == interview.id,
            AIAssessment.tenant_id == tenant_id,
        )
    )
    interview.version = (interview.version or 1) + 1
    await db.commit()
    await db.refresh(interview, attribute_names=["segments", "interviewers"])

    if old_key:
        # Best-effort — if the bucket is misconfigured we still let the
        # recruiter proceed with a fresh upload, the object becomes an
        # orphan that lifecycle policies sweep.
        try:
            delete_file(old_key)
        except Exception:
            logger.exception("Failed to delete old interview media %s", old_key)

    return _interview_to_read(interview, role="recruiter")


async def archive_interview(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    interview_id: uuid.UUID,
    data: InterviewArchiveRequest | None = None,
) -> dict:
    """Soft-delete an interview (HRP-202)."""

    interview = await _get_interview_with_relations(db, tenant_id, interview_id)
    if interview.archived_at is not None:
        return _interview_to_read(interview, role="recruiter")
    interview.archived_at = datetime.now(timezone.utc)
    interview.archived_by = user_id
    interview.status = "archived"
    if data and data.reason:
        note_prefix = "[Archived] "
        interview.notes = f"{note_prefix}{data.reason}\n{interview.notes or ''}".strip()
    interview.version = (interview.version or 1) + 1
    await db.commit()
    await db.refresh(interview, attribute_names=["segments", "interviewers"])
    return _interview_to_read(interview, role="recruiter")


async def restore_interview(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    interview_id: uuid.UUID,
) -> dict:
    """Restore an archived interview, if still within the retention window."""

    interview = await _get_interview_with_relations(db, tenant_id, interview_id)
    if interview.archived_at is None:
        return _interview_to_read(interview, role="recruiter")

    retention_cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    archived_at = interview.archived_at
    if archived_at.tzinfo is None:
        archived_at = archived_at.replace(tzinfo=timezone.utc)
    if archived_at < retention_cutoff:
        raise AppError("interview_retention_window_passed", status.HTTP_410_GONE)

    interview.archived_at = None
    interview.archived_by = None
    interview.status = (
        "uploaded"
        if (interview.audio_file_id or interview.video_file_id or interview.transcript)
        else "scheduled"
    )
    interview.version = (interview.version or 1) + 1
    await db.commit()
    await db.refresh(interview, attribute_names=["segments", "interviewers"])
    return _interview_to_read(interview, role="recruiter")


# ---------------------------------------------------------------------------
# Antivirus stub (pluggable per-tenant)
# ---------------------------------------------------------------------------


async def record_av_scan_result(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    *,
    verdict: str,
) -> dict:
    """Persist the antivirus verdict on the interview row.

    ``verdict`` is one of ``clean`` / ``infected`` / ``skipped`` /
    ``error``. ``infected`` deletes the S3 object and flips the
    interview into ``upload_failed`` so the recruiter sees the failure
    in the list view.
    """

    from app.core.s3 import delete_file

    interview = await _get_interview_with_relations(db, tenant_id, interview_id)
    interview.av_status = verdict
    interview.av_scanned_at = datetime.now(timezone.utc)
    if verdict == "infected":
        if interview.file_s3_key:
            try:
                delete_file(interview.file_s3_key)
            except Exception:
                logger.exception(
                    "Failed to delete infected file %s", interview.file_s3_key
                )
        interview.audio_file_id = None
        interview.video_file_id = None
        interview.transcript_file_id = None
        interview.file_s3_key = None
        interview.status = "upload_failed"
    interview.version = (interview.version or 1) + 1
    await db.commit()
    await db.refresh(interview, attribute_names=["segments", "interviewers"])
    return _interview_to_read(interview, role="recruiter")


# ---------------------------------------------------------------------------
# Orphan-session cleanup (HRP-202)
# ---------------------------------------------------------------------------


async def cleanup_orphan_upload_sessions(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Abort + delete upload sessions whose TTL has elapsed.

    Designed to be called from a Celery beat task ("cleanup orphan
    upload_sessions older than 24h"). Returns the number of sessions
    that were aborted so callers can emit a metric.
    """

    from app.core.s3 import abort_multipart_upload

    cutoff = now or datetime.now(timezone.utc)
    rows = (
        (
            await db.execute(
                select(UploadSession).where(
                    and_(
                        UploadSession.status == "active",
                        UploadSession.expires_at <= cutoff,
                    )
                )
            )
        )
        .scalars()
        .all()
    )

    aborted = 0
    for session in rows:
        try:
            abort_multipart_upload(session.s3_key, session.s3_upload_id)
        except Exception:
            logger.exception("Failed to abort orphan upload session %s", session.id)
        session.status = "expired"
        aborted += 1
    if aborted:
        await db.commit()
    return aborted


# ---------------------------------------------------------------------------
# Transcribe / Analyze enqueue
# ---------------------------------------------------------------------------


async def enqueue_transcribe(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
) -> dict:
    from app.modules.demo.utils import is_demo_tenant
    from app.modules.recruitment.tasks import transcribe_interview_task

    # Existence check first so a bogus interview_id returns 404
    # regardless of tenant class — keeps the demo gate from leaking a
    # 409-vs-404 oracle to an attacker enumerating interview ids.
    interview = await _get_interview_with_relations(db, tenant_id, interview_id)

    # HRP-253 (D5): defense-in-depth. The upload gate already prevents
    # demo tenants from attaching media, but if a caller stitches an
    # ``Interview`` row to a stale media file out-of-band, we still
    # refuse to dispatch a Whisper job from a sandbox.
    if await is_demo_tenant(db, tenant_id):
        raise AppError("transcription_not_allowed", status.HTTP_409_CONFLICT)

    if not (interview.audio_file_id or interview.video_file_id):
        raise AppError("interview_no_uploaded_media", status.HTTP_409_CONFLICT)
    if interview.transcription_status == "processing":
        raise AppError("transcription_already_in_progress", status.HTTP_409_CONFLICT)

    interview.transcription_status = "processing"
    interview.transcription_error = None
    await db.commit()

    task = transcribe_interview_task.delay(str(interview_id), str(tenant_id))
    return {"task_id": task.id, "status": "queued"}


async def enqueue_analyze(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
) -> dict:
    from app.modules.recruitment.tasks import analyze_interview_task

    interview = await _get_interview_with_relations(db, tenant_id, interview_id)
    if interview.transcription_status != "completed":
        raise AppError("analysis_requires_transcription", status.HTTP_409_CONFLICT)
    if interview.analysis_status == "processing":
        raise AppError("analysis_already_in_progress", status.HTTP_409_CONFLICT)

    interview.analysis_status = "processing"
    interview.analysis_error = None
    await db.commit()

    task = analyze_interview_task.delay(str(interview_id), str(tenant_id))
    return {"task_id": task.id, "status": "queued"}


async def enqueue_analyze_or_cached(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
) -> dict:
    """HRP-252 (D4): cache-aware analyze entry point.

    Used by the public endpoint instead of ``enqueue_analyze`` directly.
    On a cache hit (same transcript + vacancy profile), copies the cached
    analysis onto the interview synchronously and returns
    ``{"status": "completed", "cached": True}`` — without enqueuing a
    Celery task and without going through ``ee/billing.py``'s precheck +
    consume. Cache miss falls through to ``enqueue_analyze`` which is
    still wrapped by the billing layer (40 credits flat).
    """
    from app.modules.recruitment.analysis_cache_service import (
        apply_cached_analysis,
        compute_cache_key_for_interview,
        lookup_cached_analysis,
    )

    interview = await _get_interview_with_relations(db, tenant_id, interview_id)
    if interview.transcription_status != "completed":
        raise AppError("analysis_requires_transcription", status.HTTP_409_CONFLICT)
    if interview.analysis_status == "processing":
        raise AppError("analysis_already_in_progress", status.HTTP_409_CONFLICT)

    cache_key = await compute_cache_key_for_interview(db, tenant_id, interview)
    if cache_key is not None:
        cached = await lookup_cached_analysis(db, tenant_id, cache_key)
        if cached is not None:
            # HRP-276 / M3: take a row-level lock on the interview before
            # writing the cached payload so two parallel /analyze hits
            # can't race past the pre-check and clobber each other's
            # writes. ``populate_existing`` forces the in-session row
            # to refresh from the locked SELECT (see memory:
            # feedback_sqlalchemy_race_fix — same pattern as the
            # async cross-request TOCTOU fix).
            locked = (
                await db.execute(
                    select(Interview)
                    .where(
                        Interview.id == interview_id,
                        Interview.tenant_id == tenant_id,
                    )
                    .options(
                        selectinload(Interview.segments),
                        selectinload(Interview.interviewers),
                    )
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if locked is None:
                raise AppError("interview_not_found", status.HTTP_404_NOT_FOUND)
            if locked.analysis_status == "processing":
                # Another worker grabbed the row between the pre-check
                # and the lock — back off and let it finish.
                raise AppError(
                    "analysis_already_in_progress",
                    status.HTTP_409_CONFLICT,
                )
            interview = locked
            interviewer_id = interview.interviewer_id
            await apply_cached_analysis(db, tenant_id, interview, cached)
            await db.commit()
            # Mirror the real-path N-06 fan-out so demo / repeat-analyze
            # users still get the "analysis_ready" signal — without it
            # the UI silently leaves the activity feed empty after a
            # cache hit.
            from app.modules.recruitment.common import _publish_event

            await _publish_event(
                "recruitment.interview.analysis_ready",
                {
                    "tenant_id": str(tenant_id),
                    "interview_id": str(interview_id),
                    "interviewer_id": str(interviewer_id) if interviewer_id else None,
                    "candidate_name": None,
                    "cached": True,
                },
            )
            return {"status": "completed", "cached": True}

    return await enqueue_analyze(db, tenant_id, interview_id)


# Backwards-compat for callers that imported helpers from this module.
__all__: list[str] = [
    "UPLOAD_SESSION_TTL",
    "ack_uploaded_chunk",
    "abort_interview_upload",
    "archive_interview",
    "cleanup_orphan_upload_sessions",
    "complete_interview_upload",
    "create_interview",
    "enqueue_analyze",
    "enqueue_analyze_or_cached",
    "enqueue_transcribe",
    "get_interview",
    "get_interview_media_url",
    "get_upload_part_url",
    "get_upload_session_head",
    "init_interview_upload",
    "list_interviews",
    "paste_text_transcript",
    "record_av_scan_result",
    "replace_interview_file",
    "restore_interview",
    "update_interview",
    "update_segment",
    "update_transcript",
]


def __getattr__(name: str) -> Any:
    # Soft-fail for accidental imports of removed legacy names.
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
