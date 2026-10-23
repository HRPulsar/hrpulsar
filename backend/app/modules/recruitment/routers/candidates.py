"""Candidate and candidate-vacancy endpoints: CRUD, resumes, bulk upload, canonical card."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    Query,
    UploadFile,
)
from fastapi.responses import Response
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.recruitment import (
    service,
)
from app.modules.recruitment.models import Vacancy
from app.modules.recruitment.routers.common import (
    evaluates,
    resolve_page_params,
    runs_all_hiring,
    runs_hiring,
)
from app.modules.recruitment.schemas import (
    BatchFinalizeRequest,
    BulkResumeUploadItem,
    CandidateCanonicalCardRead,
    CandidateCanonicalPatch,
    CandidateCanonicalRead,
    CandidateCreate,
    CandidateManualCreate,
    CandidateRead,
    CandidateUpdate,
    CandidateVacancyCreate,
    CandidateVacancyEnrichedRead,
    CandidateVacancyPatch,
    CandidateVacancyRead,
    CandidateVacancyStatusUpdate,
    ResumeDedupPreviewItem,
    ResumeParseStatusResponse,
)
from app.modules.recruitment.scope import (
    RecruitmentScope,
    assert_candidate_linkable,
    assert_every_application_in_scope,
    assert_in_scope,
    candidate_reachable,
    candidate_scope,
    cv_scope,
    hidden_duplicate,
    list_scope_filter,
    recruitment_scope,
    resume_scope,
    vacancy_query_scope,
    vacancy_scope,
)

router = APIRouter(tags=["recruitment"])


# ── Candidates ──────────────────────────────────────────────────────


@router.post("/recruitment/candidates", response_model=CandidateRead, status_code=201)
async def create_candidate(
    data: CandidateCreate,
    db: AsyncSession = Depends(get_db),
    # HRP-830 REDO: a candidate on no vacancy is in nobody's scope - a scoped
    # caller adds candidates from one of their vacancies.
    current_user: User = Depends(runs_all_hiring),
):
    return await service.create_candidate(
        db, current_user.tenant_id, current_user.id, data
    )


@router.get("/recruitment/candidates")
async def list_candidates(
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    q: str | None = None,
    vacancy_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope_filter: ColumnElement[bool] | None = Depends(list_scope_filter),
    _query_scope: None = Depends(vacancy_query_scope),
):
    # HRP-363: the candidates page sends page/page_size; the endpoint used
    # to silently ignore them and always return the first page.
    skip, limit = resolve_page_params(skip, limit, page, page_size)
    items, total = await service.list_candidates(
        db,
        current_user.tenant_id,
        skip,
        limit,
        search=q,
        vacancy_id=vacancy_id,
        scope_filter=scope_filter,
    )
    return {
        "items": items,
        "total": total,
        "page": skip // limit + 1,
        "page_size": limit,
    }


@router.get("/recruitment/candidates/{candidate_id}", response_model=CandidateRead)
async def get_candidate(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(candidate_scope),
):
    return await service.get_candidate(db, current_user.tenant_id, candidate_id)


@router.put("/recruitment/candidates/{candidate_id}", response_model=CandidateRead)
async def update_candidate(
    candidate_id: uuid.UUID,
    data: CandidateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(runs_hiring),
):
    return await service.update_candidate(
        db, current_user.tenant_id, candidate_id, data
    )


@router.get("/recruitment/candidates/{candidate_id}/resumes")
async def list_candidate_resumes(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(candidate_scope),
):
    return await service.list_candidate_resumes(
        db, current_user.tenant_id, candidate_id
    )


@router.put("/recruitment/resumes/{resume_id}/parsed-data")
async def update_resume_parsed_data(
    resume_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(runs_hiring),
):
    return await service.update_resume_parsed_data(
        db, current_user.tenant_id, resume_id, payload
    )


@router.get("/recruitment/resumes/{resume_id}/download")
async def get_resume_download_url(
    resume_id: uuid.UUID,
    disposition: Literal["inline", "attachment"] = Query(default="inline"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(resume_scope),
):
    return await service.get_resume_download_url(
        db, current_user.tenant_id, resume_id, disposition=disposition
    )


@router.get("/recruitment/candidates/{candidate_id}/vacancies")
async def list_candidate_vacancies(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(candidate_scope),
    scope_filter: ColumnElement[bool] | None = Depends(list_scope_filter),
):
    return await service.list_candidate_vacancies(
        db,
        current_user.tenant_id,
        candidate_id,
        scope_filter=scope_filter,
    )


# ── Candidate-Vacancy ───────────────────────────────────────────────


@router.post(
    "/recruitment/candidate-vacancies",
    response_model=CandidateVacancyRead,
    status_code=201,
)
async def attach_candidate(
    data: CandidateVacancyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(runs_hiring),
    scope: RecruitmentScope = Depends(recruitment_scope),
):
    # HRP-830 REDO: both ride in the body, past the path guard - the
    # vacancy and the candidate are each in scope.
    await assert_in_scope(
        db, current_user, scope, select(Vacancy.id).where(Vacancy.id == data.vacancy_id)
    )
    await assert_candidate_linkable(db, current_user, scope, data.candidate_id)
    return await service.attach_candidate(
        db, current_user.tenant_id, current_user.id, data
    )


@router.patch(
    "/recruitment/candidate-vacancies/{cv_id}/status",
    response_model=CandidateVacancyRead,
)
async def change_candidate_status(
    cv_id: uuid.UUID,
    data: CandidateVacancyStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(evaluates),
    _scope: None = Depends(cv_scope),
):
    return await service.change_candidate_status(
        db, current_user.tenant_id, cv_id, data, user_id=current_user.id
    )


@router.get(
    "/recruitment/candidate-vacancies/{cv_id}",
    response_model=CandidateVacancyRead,
)
async def get_candidate_vacancy(
    cv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(cv_scope),
):
    return await service.get_candidate_vacancy(db, current_user.tenant_id, cv_id)


@router.get("/recruitment/vacancies/{vacancy_id}/candidates")
async def list_vacancy_candidates(
    vacancy_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(vacancy_scope),
):
    items, total = await service.list_vacancy_candidates(
        db, current_user.tenant_id, vacancy_id, skip, limit
    )
    return {"items": items, "total": total}


# ── HRP-181 REDO Stage 2 — canonical candidate API ─────────────────


@router.post(
    "/recruitment/vacancies/{vacancy_id}/candidates",
    status_code=201,
)
async def add_candidate_manual(
    vacancy_id: uuid.UUID,
    data: CandidateManualCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(runs_hiring),
    scope: RecruitmentScope = Depends(recruitment_scope),
):
    if data.link_candidate_id is not None:
        # HRP-830 REDO: only a candidate already in scope links.
        await assert_candidate_linkable(db, current_user, scope, data.link_candidate_id)
    try:
        return await service.add_candidate_to_vacancy_manual(
            db, current_user.tenant_id, current_user.id, vacancy_id, data
        )
    except AppError as exc:
        # HRP-830 REDO review: a scoped caller learns the address is taken,
        # never whose card it is - a recruiter or HR attaches that person.
        if (hidden := await hidden_duplicate(db, current_user, scope, exc)) is not None:
            raise hidden from exc
        raise


@router.post(
    "/recruitment/vacancies/{vacancy_id}/candidates/from-parsed",
    status_code=201,
)
async def finalize_candidates_from_parsed(
    vacancy_id: uuid.UUID,
    data: BatchFinalizeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(runs_hiring),
    scope: RecruitmentScope = Depends(recruitment_scope),
):
    # HRP-830 REDO: only a candidate already in scope links.
    for item in data.files:
        if item.link_candidate_id is not None:
            await assert_candidate_linkable(
                db, current_user, scope, item.link_candidate_id
            )
    result = await service.finalize_candidates_from_parsed(
        db, current_user.tenant_id, current_user.id, vacancy_id, data
    )
    # A skipped duplicate names the existing candidate - not to a scoped
    # caller who cannot reach them (HRP-830 REDO review).
    for row in result.get("skipped", []):
        existing = row.get("existing_candidate_id")
        if existing and not await candidate_reachable(
            db, current_user, scope, uuid.UUID(str(existing))
        ):
            row.pop("existing_candidate_id")
    return result


# ── HRP-181 REDO Stage 3 — bulk resume upload + parsing poll ───────


@router.post(
    "/recruitment/vacancies/{vacancy_id}/resumes/bulk-upload",
    response_model=list[BulkResumeUploadItem],
    status_code=201,
)
async def bulk_upload_resumes(
    vacancy_id: uuid.UUID,
    files: list[UploadFile] = File(default_factory=list),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(runs_hiring),
):
    """Bulk resume upload — up to 50 files × 10 MB PDF/DOCX per batch.

    Each file is persisted detached (``candidate_id IS NULL``) and queued
    for LLM parsing. The client drives the modal poll via
    ``GET ../resumes/parsing-status`` and finalises through
    ``POST ../candidates/from-parsed``.
    """
    return await service.bulk_upload_resumes(
        db, current_user.tenant_id, current_user.id, vacancy_id, files
    )


@router.get(
    "/recruitment/vacancies/{vacancy_id}/resumes/parsing-status",
    response_model=ResumeParseStatusResponse,
)
async def get_resumes_parsing_status(
    vacancy_id: uuid.UUID,
    file_ids: list[uuid.UUID] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(vacancy_scope),
):
    return await service.get_resumes_parsing_status(
        db,
        current_user.tenant_id,
        current_user.id,
        vacancy_id,
        file_ids,
    )


@router.get(
    "/recruitment/vacancies/{vacancy_id}/resumes/dedup-preview",
    response_model=list[ResumeDedupPreviewItem],
)
async def get_resumes_dedup_preview(
    vacancy_id: uuid.UUID,
    file_ids: list[uuid.UUID] = Query(default_factory=list),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(vacancy_scope),
    scope: RecruitmentScope = Depends(recruitment_scope),
):
    items = await service.get_resumes_dedup_preview(
        db, current_user.tenant_id, vacancy_id, file_ids
    )
    # HRP-830 REDO review: a duplicate outside a scoped caller's reach is
    # flagged, not named - a recruiter or HR attaches that person.
    for item in items:
        existing = item.get("existing_candidate_id")
        if existing and not await candidate_reachable(
            db, current_user, scope, uuid.UUID(str(existing))
        ):
            item.update(
                existing_candidate_id=None,
                existing_candidate_full_name=None,
                duplicate_elsewhere=True,
            )
    return items


@router.get(
    "/recruitment/vacancies/{vacancy_id}/candidates/enriched",
    response_model=list[CandidateVacancyEnrichedRead],
)
async def list_vacancy_candidates_enriched(
    vacancy_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    # HRP-267: rationale identical to GET /assessment-matrix —
    # candidate / invited-evaluator tokens must not be able to enumerate
    # the full roster's AI scores and per-cell divergence previews. HRP-830:
    # like that matrix, ``view`` in scope reads it - the role list left the
    # manager role out, and the vacancy's candidate table came up empty.
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(vacancy_scope),
):
    items, _total = await service.list_vacancy_candidates_enriched(
        db, current_user.tenant_id, vacancy_id, skip=skip, limit=limit
    )
    return items


@router.patch(
    "/recruitment/candidate-vacancies/{cv_id}",
    response_model=CandidateVacancyEnrichedRead,
)
async def patch_candidate_vacancy(
    cv_id: uuid.UUID,
    data: CandidateVacancyPatch,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(evaluates),
    if_match: str | None = Header(default=None, alias="If-Match"),
    _scope: None = Depends(cv_scope),
):
    payload = await service.patch_candidate_vacancy(
        db,
        current_user.tenant_id,
        cv_id,
        data,
        if_match=if_match,
        user_id=current_user.id,
    )
    etag = payload.pop("etag", None)
    if etag is not None:
        response.headers["ETag"] = etag
    return payload


@router.delete(
    "/recruitment/candidate-vacancies/{cv_id}",
    status_code=204,
)
async def delete_candidate_vacancy(
    cv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(runs_hiring),
):
    """HRP-181 REDO: drop the candidate from a vacancy funnel."""
    await service.delete_candidate_vacancy(
        db, current_user.tenant_id, cv_id, user_id=current_user.id
    )
    return Response(status_code=204)


@router.get(
    "/recruitment/candidates/{candidate_id}/card",
    response_model=CandidateCanonicalCardRead,
)
async def get_candidate_full_card(
    candidate_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(candidate_scope),
    scope_filter: ColumnElement[bool] | None = Depends(list_scope_filter),
):
    payload = await service.get_candidate_full_card(
        db,
        current_user.tenant_id,
        candidate_id,
        scope_filter=scope_filter,
    )
    etag = payload.pop("etag", None)
    if etag is not None:
        response.headers["ETag"] = etag
    return payload


@router.patch(
    "/recruitment/candidates/{candidate_id}",
    response_model=CandidateCanonicalRead,
)
async def patch_candidate(
    candidate_id: uuid.UUID,
    data: CandidateCanonicalPatch,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(runs_hiring),
    if_match: str | None = Header(default=None, alias="If-Match"),
    scope: RecruitmentScope = Depends(recruitment_scope),
):
    try:
        payload = await service.patch_candidate(
            db,
            current_user.tenant_id,
            candidate_id,
            data,
            if_match=if_match,
        )
    except AppError as exc:
        # HRP-830 REDO review: an email change onto someone else's address.
        if (hidden := await hidden_duplicate(db, current_user, scope, exc)) is not None:
            raise hidden from exc
        raise
    etag = payload.pop("etag", None)
    if etag is not None:
        response.headers["ETag"] = etag
    return payload


@router.delete(
    "/recruitment/candidates/{candidate_id}",
    status_code=204,
)
async def archive_candidate(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(runs_hiring),
    scope: RecruitmentScope = Depends(recruitment_scope),
):
    # HRP-830 REDO review: archiving is tenant-wide - every application has
    # to be the caller's; otherwise they detach it from their vacancy.
    await assert_every_application_in_scope(db, current_user, scope, candidate_id)
    await service.archive_candidate(
        db, current_user.tenant_id, candidate_id, user_id=current_user.id
    )
    return Response(status_code=204)
