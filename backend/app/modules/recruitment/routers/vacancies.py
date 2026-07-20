"""Vacancy endpoints: CRUD, profile, competences, attachments, funnel stages."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.recruitment import (
    service,
)
from app.modules.recruitment.routers.common import resolve_page_params
from app.modules.recruitment.schemas import (
    HiringManagerOption,
    VacancyAttachmentRead,
    VacancyCloseData,
    VacancyCompetenceRead,
    VacancyCompetencesUpdate,
    VacancyCreate,
    VacancyProfileGenerateRequest,
    VacancyProfileSessionApplyRequest,
    VacancyProfileSessionCancelRequest,
    VacancyProfileUpdate,
    VacancyRead,
    VacancyStageCreate,
    VacancyStageRead,
    VacancyStagesReplace,
    VacancyStageUpdate,
    VacancyUpdate,
)

router = APIRouter(tags=["recruitment"])


# ── Vacancies ───────────────────────────────────────────────────────


@router.post("/recruitment/vacancies", response_model=VacancyRead, status_code=201)
async def create_vacancy(
    data: VacancyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.create_vacancy(
        db, current_user.tenant_id, current_user.id, data
    )


@router.get("/recruitment/vacancies")
async def list_vacancies(
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    status: str | None = None,
    q: str | None = None,
    archived: Literal["only", "include", "exclude"] = "exclude",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    skip, limit = resolve_page_params(skip, limit, page, page_size)
    items, total = await service.list_vacancies(
        db,
        current_user.tenant_id,
        skip,
        limit,
        status=status,
        search=q,
        include_archived=archived == "include",
        archived_only=archived == "only",
    )
    return {
        "items": items,
        "total": total,
        "page": skip // limit + 1,
        "page_size": limit,
    }


@router.get("/recruitment/hiring-managers", response_model=list[HiringManagerOption])
async def list_hiring_managers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    """HRP-360: admin-tier users for the vacancy Hiring manager picker."""
    return await service.list_hiring_manager_options(db, current_user.tenant_id)


@router.get("/recruitment/vacancies/{vacancy_id}", response_model=VacancyRead)
async def get_vacancy(
    vacancy_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vacancy = await service.get_vacancy(db, current_user.tenant_id, vacancy_id)
    response.headers["ETag"] = service.vacancy_etag(vacancy)
    return vacancy


@router.put("/recruitment/vacancies/{vacancy_id}", response_model=VacancyRead)
async def update_vacancy(
    vacancy_id: uuid.UUID,
    data: VacancyUpdate,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    if_match = request.headers.get("if-match")
    vacancy = await service.update_vacancy(
        db, current_user.tenant_id, vacancy_id, data, if_match=if_match
    )
    response.headers["ETag"] = service.vacancy_etag(vacancy)
    return vacancy


@router.patch("/recruitment/vacancies/{vacancy_id}", response_model=VacancyRead)
async def patch_vacancy(
    vacancy_id: uuid.UUID,
    data: VacancyUpdate,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    """PATCH variant — same semantics as PUT but requires ``If-Match`` (HRP-177).

    The frontend edit form always sends PATCH with the ETag it captured
    when loading the vacancy; a missing header → 428, a stale one → 412
    so a concurrent edit cannot silently overwrite another user's work.
    """
    if_match = request.headers.get("if-match")
    if if_match is None:
        from fastapi import HTTPException
        from fastapi import status as http_status

        raise HTTPException(
            http_status.HTTP_428_PRECONDITION_REQUIRED,
            "If-Match header is required for PATCH /vacancies/{id}.",
        )
    vacancy = await service.update_vacancy(
        db, current_user.tenant_id, vacancy_id, data, if_match=if_match
    )
    response.headers["ETag"] = service.vacancy_etag(vacancy)
    return vacancy


@router.post("/recruitment/vacancies/{vacancy_id}/archive", response_model=VacancyRead)
async def archive_vacancy(
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.archive_vacancy(
        db, current_user.tenant_id, current_user.id, vacancy_id
    )


@router.post("/recruitment/vacancies/{vacancy_id}/restore", response_model=VacancyRead)
async def restore_vacancy(
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.restore_vacancy(db, current_user.tenant_id, vacancy_id)


@router.delete("/recruitment/vacancies/{vacancy_id}", status_code=204)
async def delete_vacancy(
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    await service.delete_vacancy(db, current_user.tenant_id, vacancy_id)
    return Response(status_code=204)


@router.post("/recruitment/vacancies/{vacancy_id}/close", response_model=VacancyRead)
async def close_vacancy(
    vacancy_id: uuid.UUID,
    data: VacancyCloseData,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.close_vacancy(db, current_user.tenant_id, vacancy_id, data)


@router.post("/recruitment/vacancies/{vacancy_id}/profile/generate")
async def generate_profile(
    vacancy_id: uuid.UUID,
    data: VacancyProfileGenerateRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    """Generate AI vacancy competency profile inline.

    Previously this endpoint queued a Celery task and returned ``202`` with
    a ``task_id``, but no worker is provisioned in dev/test and the
    frontend never polled the task — so users only ever saw the "Failed
    to generate profile" toast (HRP-134). The synchronous flow surfaces
    real errors and returns the generated payload in one round-trip.

    HRP-235 REDO (QA case 4): the result is parked on the session row for
    review — it is NOT saved to the vacancy profile until the recruiter
    applies it via ``PUT /profile``. Returns 409 when another generation
    session is already running for this vacancy (QA case 2).

    Accepts an optional body ``{"clarification": "…"}`` carrying the
    recruiter's free-form context from the Generate matrix modal — see
    HRP-134 REDO. Empty / missing body keeps the legacy fire-and-forget
    flow working.
    """
    return await service.generate_profile_now(
        db,
        current_user.tenant_id,
        current_user.id,
        vacancy_id,
        clarification=(data.clarification if data else None),
    )


@router.get("/recruitment/vacancies/{vacancy_id}/profile")
async def get_vacancy_profile(
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = await service.get_vacancy_profile(db, current_user.tenant_id, vacancy_id)
    if profile is None:
        return {"profile": None}
    return profile


@router.get("/recruitment/vacancies/{vacancy_id}/profile/sessions/active")
async def get_active_profile_session_route(
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HRP-134: surface the latest non-terminal generation session so a
    returning user sees `Generating…` while the sync LLM call is still
    in flight, or the Review-for-save banner when it has finished.

    HRP-235 REDO: the poll stays readable for every tenant member (it
    drives the shared banner), but the parked, not-yet-approved
    ``profile_data`` is stripped unless the caller could actually open
    the review dialog (admin-tier or recruiter) — other roles only see
    ``has_pending_result``.
    """
    from app.core import rbac_hooks

    role_codes = {r.code for r in current_user.roles}
    can_review = bool(
        role_codes & (rbac_hooks.admin_equivalent_codes() | {"recruiter"})
    )
    return await service.get_active_profile_session(
        db, current_user.tenant_id, vacancy_id, include_result=can_review
    )


@router.post("/recruitment/vacancies/{vacancy_id}/profile/sessions/apply")
async def apply_profile_session_route(
    vacancy_id: uuid.UUID,
    data: VacancyProfileSessionApplyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    """HRP-235 REDO (QA case 4): persist a reviewed generation result.

    Atomically saves the recruiter's kept + edited ``profile_data`` to
    the vacancy profile (with AI provenance fields) and flips the
    ``ready`` session to ``applied`` — one transaction, so the
    Review-for-save banner can never outlive a successful save.
    """
    return await service.apply_profile_session(
        db,
        current_user.tenant_id,
        vacancy_id,
        data.session_id,
        VacancyProfileUpdate(profile_data=data.profile_data),
    )


@router.post("/recruitment/vacancies/{vacancy_id}/profile/sessions/cancel")
async def cancel_active_profile_session_route(
    vacancy_id: uuid.UUID,
    data: VacancyProfileSessionCancelRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    """HRP-235: dismiss the in-progress profile-generation banner.

    Marks a ``running``/``failed``/``ready`` session as ``cancelled`` so
    the ``/profile/sessions/active`` endpoint stops returning it. For a
    running session the LLM call may still complete server-side — the UI
    just stops waiting and the result is dropped; for a ``ready`` session
    this is how the review dialog consumes the pending result (Discard,
    or the cleanup after Apply persisted it).

    HRP-134 REDO: an optional ``{"session_id": …}`` body pins the cancel
    to that exact session; an omitted/empty body keeps the legacy
    latest-match behaviour.
    """
    return await service.cancel_active_profile_session(
        db,
        current_user.tenant_id,
        vacancy_id,
        session_id=(data.session_id if data else None),
    )


@router.put("/recruitment/vacancies/{vacancy_id}/profile")
async def save_vacancy_profile(
    vacancy_id: uuid.UUID,
    data: VacancyProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.save_profile(db, current_user.tenant_id, vacancy_id, data)


# ── HRP-136: Vacancy competences ────────────────────────────────────


@router.get(
    "/recruitment/vacancies/{vacancy_id}/competences",
    response_model=list[VacancyCompetenceRead],
)
async def list_vacancy_competences(
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_vacancy_competences(
        db, current_user.tenant_id, vacancy_id
    )


@router.patch(
    "/recruitment/vacancies/{vacancy_id}/competences",
    response_model=list[VacancyCompetenceRead],
)
async def set_vacancy_competences(
    vacancy_id: uuid.UUID,
    data: VacancyCompetencesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.set_vacancy_competences(
        db, current_user.tenant_id, vacancy_id, data
    )


# ── HRP-135: Vacancy attachments ────────────────────────────────────


@router.get(
    "/recruitment/vacancies/{vacancy_id}/attachments",
    response_model=list[VacancyAttachmentRead],
)
async def list_vacancy_attachments(
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_vacancy_attachments(
        db, current_user.tenant_id, vacancy_id
    )


@router.post(
    "/recruitment/vacancies/{vacancy_id}/attachments",
    response_model=VacancyAttachmentRead,
    status_code=201,
)
async def upload_vacancy_attachment(
    vacancy_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.upload_vacancy_attachment(
        db, current_user.tenant_id, current_user.id, vacancy_id, file
    )


@router.delete(
    "/recruitment/vacancies/{vacancy_id}/attachments/{attachment_id}",
    status_code=204,
)
async def delete_vacancy_attachment(
    vacancy_id: uuid.UUID,
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    await service.delete_vacancy_attachment(
        db, current_user.tenant_id, vacancy_id, attachment_id
    )
    return Response(status_code=204)


# ── Funnel Stages ───────────────────────────────────────────────────


@router.get("/recruitment/stages", response_model=list[VacancyStageRead])
async def list_stages(
    vacancy_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_stages(db, current_user.tenant_id, vacancy_id=vacancy_id)


@router.post("/recruitment/stages", response_model=VacancyStageRead, status_code=201)
async def create_stage(
    data: VacancyStageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.create_stage(db, current_user.tenant_id, data)


@router.put("/recruitment/stages/{stage_id}", response_model=VacancyStageRead)
async def update_stage(
    stage_id: uuid.UUID,
    data: VacancyStageUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.update_stage(db, current_user.tenant_id, stage_id, data)


@router.delete("/recruitment/stages/{stage_id}", status_code=204)
async def delete_stage(
    stage_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_stage(db, current_user.tenant_id, stage_id)


@router.post(
    "/recruitment/vacancies/{vacancy_id}/stages",
    response_model=VacancyStageRead,
    status_code=201,
)
async def create_vacancy_stage_override(
    vacancy_id: uuid.UUID,
    data: VacancyStageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.create_vacancy_stage_override(
        db, current_user.tenant_id, vacancy_id, data
    )


@router.get(
    "/recruitment/recruitment-stages",
    response_model=list[VacancyStageRead],
)
async def list_tenant_default_stages(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_tenant_default_stages(db, current_user.tenant_id)


@router.get(
    "/recruitment/vacancies/{vacancy_id}/funnel-stages",
    response_model=list[VacancyStageRead],
)
async def list_effective_vacancy_stages(
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_effective_vacancy_stages(
        db, current_user.tenant_id, vacancy_id
    )


@router.put(
    "/recruitment/vacancies/{vacancy_id}/funnel-stages",
    response_model=list[VacancyStageRead],
)
async def replace_vacancy_funnel_stages(
    vacancy_id: uuid.UUID,
    data: VacancyStagesReplace,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.replace_vacancy_stages_override(
        db, current_user.tenant_id, vacancy_id, data
    )
