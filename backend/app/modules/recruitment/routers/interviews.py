"""Interview endpoints: CRUD, TUS-style upload, transcripts, AI analysis runs (HRP-204)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Query,
)
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.recruitment import (
    service,
)
from app.modules.recruitment.schemas import (
    AbortUploadRequest,
    AIAnalysisEnqueueRequest,
    AIAnalysisEnqueueResponse,
    AIAnalysisRunRead,
    BulkAnalyzeRequest,
    BulkAnalyzeResponse,
    CompleteUploadRequest,
    InitUploadRequest,
    InitUploadResponse,
    InterviewArchiveRequest,
    InterviewCreate,
    InterviewRead,
    InterviewSegmentRead,
    InterviewSegmentUpdate,
    InterviewUpdate,
    PartUrlRequest,
    PartUrlResponse,
    TextTranscriptRequest,
    TopupEligibilityResponse,
    TranscriptUpdate,
    UploadChunkAck,
)

router = APIRouter(tags=["recruitment"])


# ── Interviews / Consent / Upload (R3a) ───────────────────────────


@router.post(
    "/recruitment/candidate-vacancies/{cv_id}/interviews",
    response_model=InterviewRead,
    status_code=201,
)
async def create_interview(
    cv_id: uuid.UUID,
    data: InterviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.create_interview(
        db, current_user.tenant_id, current_user.id, cv_id, data
    )


@router.get(
    "/recruitment/candidate-vacancies/{cv_id}/interviews",
)
async def list_cv_interviews(
    cv_id: uuid.UUID,
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_interviews(
        db,
        current_user.tenant_id,
        cv_id,
        role=service.resolve_user_role(current_user),
        include_archived=include_archived,
    )


@router.get("/recruitment/interviews/{interview_id}", response_model=InterviewRead)
async def get_interview(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_interview(
        db,
        current_user.tenant_id,
        interview_id,
        role=service.resolve_user_role(current_user),
    )


@router.put("/recruitment/interviews/{interview_id}", response_model=InterviewRead)
async def update_interview(
    interview_id: uuid.UUID,
    data: InterviewUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    """Update interview metadata.

    Accepts an optional ``If-Match: W/"{version}"`` header (HRP-202).
    When the header is present and the stored version does not match,
    the service returns ``412 Precondition Failed`` and the client must
    reload.
    """

    expected_version: int | None = None
    if if_match:
        stripped = if_match.strip().lstrip("Ww/").strip('"')
        try:
            expected_version = int(stripped)
        except ValueError:
            expected_version = None
    return await service.update_interview(
        db,
        current_user.tenant_id,
        interview_id,
        data,
        if_match_version=expected_version,
    )


@router.put(
    "/recruitment/interviews/{interview_id}/transcript",
    response_model=InterviewRead,
)
async def update_transcript(
    interview_id: uuid.UUID,
    data: TranscriptUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.update_transcript(
        db, current_user.tenant_id, interview_id, data
    )


@router.put(
    "/recruitment/interviews/{interview_id}/segments/{segment_id}",
    response_model=InterviewSegmentRead,
)
async def update_interview_segment(
    interview_id: uuid.UUID,
    segment_id: uuid.UUID,
    data: InterviewSegmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.update_segment(
        db, current_user.tenant_id, interview_id, segment_id, data
    )


@router.post(
    "/recruitment/interviews/{interview_id}/upload/init",
    response_model=InitUploadResponse,
)
async def init_interview_upload(
    interview_id: uuid.UUID,
    data: InitUploadRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.init_interview_upload(
        db,
        current_user.tenant_id,
        interview_id,
        data,
        user_id=current_user.id,
    )


@router.head(
    "/recruitment/interviews/{interview_id}/upload/{upload_id}",
    status_code=200,
)
async def head_interview_upload(
    interview_id: uuid.UUID,
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    """TUS-style HEAD: returns ``Upload-Offset`` and ``Upload-Length``.

    The frontend hits this after a page reload to figure out where to
    resume from.
    """

    state = await service.get_upload_session_head(
        db, current_user.tenant_id, interview_id, upload_id
    )
    return Response(
        status_code=200,
        headers={
            "Upload-Offset": str(state["upload_offset"]),
            "Upload-Length": str(state["upload_length"]),
            "Tus-Resumable": "1.0.0",
            "Cache-Control": "no-store",
        },
    )


@router.patch(
    "/recruitment/interviews/{interview_id}/upload/{upload_id}",
)
async def patch_interview_upload(
    interview_id: uuid.UUID,
    upload_id: str,
    ack: UploadChunkAck,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
    upload_offset: int | None = Header(default=None, alias="Upload-Offset"),
):
    """TUS-style PATCH companion: acks one part-N upload to S3.

    The bytes themselves are PUT directly to S3 via the part-url
    pre-signed URL; this endpoint records the part so the next HEAD can
    return the correct offset and the orphan-cleanup task knows the
    session is still active.
    """

    state = await service.ack_uploaded_chunk(
        db, current_user.tenant_id, interview_id, upload_id, ack
    )
    return Response(
        status_code=204,
        headers={
            "Upload-Offset": str(state["upload_offset"]),
            "Tus-Resumable": "1.0.0",
            "Cache-Control": "no-store",
        },
    )


@router.delete(
    "/recruitment/interviews/{interview_id}/upload/{upload_id}",
    status_code=204,
)
async def delete_interview_upload(
    interview_id: uuid.UUID,
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    """TUS-style cancel — aborts the S3 multipart and marks the session."""

    await service.abort_interview_upload(
        db,
        current_user.tenant_id,
        interview_id,
        AbortUploadRequest(upload_id=upload_id),
    )
    return Response(status_code=204)


@router.post(
    "/recruitment/interviews/{interview_id}/upload/part-url",
    response_model=PartUrlResponse,
)
async def get_interview_upload_part_url(
    interview_id: uuid.UUID,
    data: PartUrlRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.get_upload_part_url(
        db, current_user.tenant_id, interview_id, data
    )


@router.post(
    "/recruitment/interviews/{interview_id}/upload/complete",
    response_model=InterviewRead,
)
async def complete_interview_upload(
    interview_id: uuid.UUID,
    data: CompleteUploadRequest,
    kind: Literal["audio", "video"] = Query("audio"),
    filename: str = Query("interview.bin"),
    mime_type: str = Query("application/octet-stream"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.complete_interview_upload(
        db,
        current_user.tenant_id,
        current_user.id,
        interview_id,
        data,
        kind=kind,
        filename=filename,
        mime_type=mime_type,
    )


@router.get(
    "/recruitment/interviews/{interview_id}/media-url",
)
async def get_interview_media_url(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Presigned GET URL for the interview's media file (audio preferred)."""
    role = service.resolve_user_role(current_user)
    allow_evaluator = await _tenant_allows_invited_evaluator_playback(
        db, current_user.tenant_id
    )
    return await service.get_interview_media_url(
        db,
        current_user.tenant_id,
        interview_id,
        role=role,
        allow_invited_evaluator_playback=allow_evaluator,
    )


@router.get(
    "/recruitment/interviews/{interview_id}/file/signed-url",
)
async def get_interview_file_signed_url(
    interview_id: uuid.UUID,
    expires_in: int = Query(300, ge=60, le=3600),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HRP-202 explicit signed-URL endpoint with caller-tunable TTL.

    Kept distinct from ``media-url`` so the UI can refresh URLs on the
    same connection without scrambling the existing client.
    """

    role = service.resolve_user_role(current_user)
    allow_evaluator = await _tenant_allows_invited_evaluator_playback(
        db, current_user.tenant_id
    )
    return await service.get_interview_media_url(
        db,
        current_user.tenant_id,
        interview_id,
        role=role,
        allow_invited_evaluator_playback=allow_evaluator,
    )


async def _tenant_allows_invited_evaluator_playback(
    db: AsyncSession, tenant_id: uuid.UUID
) -> bool:
    """Read the tenant flag controlling invited-evaluator playback.

    Defaults to ``False`` — invited evaluators get the AI canvas, never
    the raw recording, unless the tenant has explicitly opted in via the
    recruitment-settings hub.
    """

    from app.modules.recruitment import settings_service as rs_settings

    try:
        branding = await rs_settings.get_branding(db, tenant_id)
        if isinstance(branding, dict):
            return bool(branding.get("invited_evaluator_can_play_media"))
    except Exception:  # noqa: BLE001 - fails closed: no media access
        return False
    return False


@router.post(
    "/recruitment/interviews/{interview_id}/transcript-text",
    response_model=InterviewRead,
)
async def paste_text_transcript(
    interview_id: uuid.UUID,
    data: TextTranscriptRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    """HRP-202: inline-paste a transcript (no media file)."""
    return await service.paste_text_transcript(
        db, current_user.tenant_id, interview_id, data
    )


@router.post(
    "/recruitment/interviews/{interview_id}/archive",
    response_model=InterviewRead,
)
async def archive_interview(
    interview_id: uuid.UUID,
    data: InterviewArchiveRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.archive_interview(
        db,
        current_user.tenant_id,
        current_user.id,
        interview_id,
        data,
    )


@router.post(
    "/recruitment/interviews/{interview_id}/restore",
    response_model=InterviewRead,
)
async def restore_interview(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.restore_interview(
        db,
        current_user.tenant_id,
        current_user.id,
        interview_id,
    )


@router.post(
    "/recruitment/interviews/{interview_id}/replace-file",
    response_model=InterviewRead,
)
async def replace_interview_file(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.replace_interview_file(
        db, current_user.tenant_id, interview_id
    )


@router.post(
    "/recruitment/interviews/{interview_id}/upload/abort",
    status_code=200,
)
async def abort_interview_upload(
    interview_id: uuid.UUID,
    data: AbortUploadRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.abort_interview_upload(
        db, current_user.tenant_id, interview_id, data
    )


@router.post(
    "/recruitment/interviews/{interview_id}/transcribe",
    status_code=202,
)
async def enqueue_transcribe(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.enqueue_transcribe(
        db, current_user.tenant_id, interview_id
    )


@router.post(
    "/recruitment/interviews/{interview_id}/analyze",
)
async def enqueue_analyze(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    from fastapi.responses import JSONResponse

    result = await service.enqueue_analyze_or_cached(
        db, current_user.tenant_id, interview_id
    )
    # Cache hit → analysis is already complete (200 OK). Cache miss →
    # the Celery task has been queued (202 Accepted). Keeping the two
    # paths under one decorator with an explicit response avoids the
    # "202 + completed body" semantic mismatch.
    status_code = 200 if result.get("status") == "completed" else 202
    return JSONResponse(content=result, status_code=status_code)


# ── HRP-204: resume-only / top-up / bulk / history ─────────────────


@router.post(
    "/recruitment/candidate-vacancies/{candidate_vacancy_id}/ai-analyses",
    status_code=202,
    response_model=AIAnalysisEnqueueResponse,
)
async def enqueue_ai_analysis(
    candidate_vacancy_id: uuid.UUID,
    data: AIAnalysisEnqueueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    """Single entry point for resume-only / top-up / full triggers.

    ``mode='resume_only'`` — 20 cr per (HRP-204).
    ``mode='topup_to_full'`` — 20 cr; rejects with structured 409 when
    eligibility checks fail (no transcript, run too old, profile
    changed).
    ``mode='full'`` — redirect to the legacy interview-page entry point
    (40 cr); ``interview_id`` required.
    """

    from app.modules.recruitment import resume_analysis_service

    if data.mode == "resume_only":
        res = await resume_analysis_service.enqueue_resume_only_analysis(
            db, current_user.tenant_id, candidate_vacancy_id, current_user.id
        )
        return AIAnalysisEnqueueResponse(
            task_id=res.get("task_id"),
            run_id=uuid.UUID(res["run_id"]),
            status="queued",
            mode="resume_only",
        )
    if data.mode == "topup_to_full":
        res = await resume_analysis_service.enqueue_topup_to_full(
            db, current_user.tenant_id, candidate_vacancy_id, current_user.id
        )
        return AIAnalysisEnqueueResponse(
            task_id=res.get("task_id"),
            run_id=uuid.UUID(res["run_id"]),
            status="queued",
            mode="full",
            supersedes_id=uuid.UUID(res["supersedes_id"]),
        )
    # mode='full' — must come with an interview_id; reuses the
    # legacy interview-analyze entry point (still billable at 40 cr).
    if data.interview_id is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="interview_id is required for mode='full'",
        )
    # HRP-269: verify the interview is scoped to the URL's
    # candidate-vacancy. ``enqueue_analyze_or_cached`` enforces
    # tenant_id only, so without this check a recruiter could POST a
    # foreign cv's interview against this URL and the analysis would
    # land on the wrong cv (cost manipulation + audit pollution).
    from sqlalchemy import select as _select

    from app.modules.recruitment.models import Interview as _Interview

    interview_row = await db.scalar(
        _select(_Interview).where(
            _Interview.id == data.interview_id,
            _Interview.tenant_id == current_user.tenant_id,
        )
    )
    if interview_row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Interview not found")
    if interview_row.candidate_vacancy_id != candidate_vacancy_id:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="interview_id does not belong to this candidate-vacancy",
        )
    res = await service.enqueue_analyze_or_cached(
        db, current_user.tenant_id, data.interview_id
    )
    # ``enqueue_analyze_or_cached`` returns ``{"task_id", "status"}`` on
    # cache miss and ``{"status": "completed", "cached": True}`` on hit.
    # No ``AIAnalysisRun`` row exists for cache hits — the legacy
    # interview-page entry point predates the runs table. Surface
    # ``run_id=None`` so the schema does not lie with a fake UUID
    # that the frontend might key list rows by or 404 against.
    return AIAnalysisEnqueueResponse(
        task_id=res.get("task_id"),
        run_id=None,
        status="queued"
        if res.get("status") != "completed"
        else "completed",
        mode="full",
    )


@router.post(
    "/recruitment/ai-analyses/{run_id}/cancel",
    status_code=200,
)
async def cancel_ai_analysis(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
) -> dict:
    """HRP-270: cancel an in-flight AI analysis run.

    Revokes the Celery task (best-effort), refunds 100% credits iff
    the worker had not reached the first LLM-spending stage, and
    writes an ``ai.analyze_cancelled`` audit log entry.
    """
    from app.modules.recruitment import resume_analysis_service

    return await resume_analysis_service.cancel_ai_analysis_run(
        db, current_user.tenant_id, run_id, current_user.id
    )


@router.get(
    "/recruitment/candidate-vacancies/{candidate_vacancy_id}/ai-analyses",
    response_model=list[AIAnalysisRunRead],
)
async def list_ai_analyses(
    candidate_vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    from app.modules.recruitment import resume_analysis_service

    rows = await resume_analysis_service.list_runs_for_cv(
        db, current_user.tenant_id, candidate_vacancy_id
    )
    # HRP-271: serialize through the explicit helper so ``resume_excerpts``
    # is populated and the raw ``analysis_data`` blob never reaches the
    # wire.
    # HRP-272: pass the current parsed-resume hash so each run flips
    # ``resume_outdated`` on when the candidate uploaded a fresh CV
    # after the run was enqueued — drives the "Resume updated —
    # re-analyze" banner.
    # Review #3 (HRP-272): short-circuit the extra two queries +
    # SHA256 when no run carries a stamped snapshot (full-mode-only
    # history, legacy rows without a hash, empty list) — the
    # serializer would discard the result anyway.
    needs_hash = any(
        r.mode == "resume_only" and r.resume_snapshot_hash is not None
        for r in rows
    )
    current_hash = (
        await resume_analysis_service.current_resume_hash_for_cv(
            db, current_user.tenant_id, candidate_vacancy_id
        )
        if needs_hash
        else None
    )
    return [
        resume_analysis_service.serialize_run_for_read(r, current_hash)
        for r in rows
    ]


@router.get(
    "/recruitment/candidate-vacancies/{candidate_vacancy_id}/ai-analyses/topup-eligibility",
    response_model=TopupEligibilityResponse,
)
async def get_topup_eligibility(
    candidate_vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    from app.modules.recruitment import resume_analysis_service

    return await resume_analysis_service.evaluate_topup_eligibility(
        db, current_user.tenant_id, candidate_vacancy_id
    )


@router.post(
    "/recruitment/vacancies/{vacancy_id}/ai-analyses/bulk",
    response_model=BulkAnalyzeResponse,
)
async def bulk_analyze_resume_only(
    vacancy_id: uuid.UUID,
    data: BulkAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    """Fan-out resume-only analysis over a recruiter selection. Hiring
    Manager role is **not** allowed (bulk × 20 cr is a budget risk —
    spec §14 RBAC)."""

    from app.modules.recruitment import resume_analysis_service

    return await resume_analysis_service.enqueue_bulk_resume_only(
        db,
        current_user.tenant_id,
        vacancy_id,
        data.candidate_vacancy_ids,
        current_user.id,
    )
