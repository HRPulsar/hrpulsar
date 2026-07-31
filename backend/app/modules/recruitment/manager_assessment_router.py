"""HRP-186: routers for manager assessment + public invited-evaluator flow.

Internal endpoints live under ``/api/v1/...`` and require an authenticated
tenant member. The public endpoints under ``/api/v1/public/assessments/...``
use the invite token instead of a JWT and are rate-limited per-IP.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import client_ip
from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.recruitment import (
    manager_assessment_public as public_service,
)
from app.modules.recruitment import (
    manager_assessment_service as service,
)
from app.modules.recruitment.manager_assessment_schemas import (
    CompetenceScoreIn,
    ExtendInviteIn,
    IndicatorScoreIn,
    ManagerAssessmentInviteCreate,
    PublicEvaluatorNameUpdate,
    RoundCreate,
    RoundEvaluatorAdd,
    ScaleCreate,
    ScaleUpdate,
)

router = APIRouter(tags=["recruitment-manager-assessment"])
public_router = APIRouter(tags=["recruitment-public-assessment"])


# --- Scales ---------------------------------------------------------------


@router.get("/v1/tenants/me/assessment-scales")
async def list_scales_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await service.list_scales(db, current_user.tenant_id)


@router.get("/v1/assessment-scales/{scale_id}")
async def get_scale_endpoint(
    scale_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await service.get_scale(db, current_user.tenant_id, scale_id)


@router.post("/v1/tenants/me/assessment-scales", status_code=201)
async def create_scale_endpoint(
    payload: ScaleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
) -> dict[str, Any]:
    return await service.create_scale(
        db, current_user.tenant_id, current_user.id, payload
    )


@router.patch("/v1/assessment-scales/{scale_id}")
async def update_scale_endpoint(
    scale_id: uuid.UUID,
    payload: ScaleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
) -> dict[str, Any]:
    return await service.update_scale(
        db, current_user.tenant_id, current_user.id, scale_id, payload
    )


@router.post("/v1/assessment-scales/{scale_id}/archive")
async def archive_scale_endpoint(
    scale_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
) -> dict[str, Any]:
    return await service.archive_scale(
        db, current_user.tenant_id, current_user.id, scale_id
    )


@router.delete("/v1/assessment-scales/{scale_id}", status_code=204)
async def delete_scale_endpoint(
    scale_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
) -> None:
    await service.delete_scale(db, current_user.tenant_id, current_user.id, scale_id)


# --- Vacancy ↔ scale ------------------------------------------------------


@router.patch("/v1/vacancies/{vacancy_id}/assessment-scale")
async def set_vacancy_scale_endpoint(
    vacancy_id: uuid.UUID,
    payload: dict[str, uuid.UUID] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
) -> dict[str, Any]:
    scale_id = payload.get("assessment_scale_id")
    if scale_id is None:
        raise AppError("assessment_scale_id_required", status.HTTP_400_BAD_REQUEST)
    return await service.set_vacancy_scale(
        db, current_user.tenant_id, current_user.id, vacancy_id, scale_id
    )


# --- Rounds ---------------------------------------------------------------


@router.get("/v1/candidate-vacancies/{cv_id}/assessment-rounds")
async def list_rounds_endpoint(
    cv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await service.list_rounds(db, current_user.tenant_id, cv_id)


@router.post("/v1/candidate-vacancies/{cv_id}/assessment-rounds", status_code=201)
async def create_round_endpoint(
    cv_id: uuid.UUID,
    payload: RoundCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "manager")),
) -> dict[str, Any]:
    return await service.create_round(
        db, current_user.tenant_id, current_user.id, cv_id, payload
    )


@router.patch("/v1/assessment-rounds/{round_id}")
async def update_round_endpoint(
    round_id: uuid.UUID,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "manager")),
) -> dict[str, Any]:
    new_status = payload.get("status")
    if not isinstance(new_status, str):
        raise AppError("round_status_required", status.HTTP_400_BAD_REQUEST)
    return await service.update_round_status(
        db,
        current_user.tenant_id,
        current_user.id,
        round_id,
        new_status,
        archived_reason=payload.get("archived_reason"),
    )


@router.post("/v1/assessment-rounds/{round_id}/evaluators", status_code=201)
async def add_evaluator_endpoint(
    round_id: uuid.UUID,
    payload: RoundEvaluatorAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "manager")),
) -> dict[str, Any]:
    return await service.add_evaluator(
        db, current_user.tenant_id, current_user.id, round_id, payload.user_id
    )


@router.get("/v1/assessment-rounds/{round_id}/aggregate")
async def round_aggregate_endpoint(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await service.round_aggregate(db, current_user.tenant_id, round_id)


@router.get("/v1/assessment-rounds/{round_id}/assessments")
async def list_round_assessments_endpoint(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await service.list_assessments_for_round(
        db, current_user.tenant_id, round_id
    )


# --- Assessments — per-evaluator sheets ----------------------------------


@router.get("/v1/assessments/{assessment_id}")
async def get_assessment_endpoint(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await service.get_assessment(db, current_user.tenant_id, assessment_id)


@router.patch("/v1/assessments/{assessment_id}/competence-scores/{competence_id}")
async def set_competence_score_endpoint(
    assessment_id: uuid.UUID,
    competence_id: uuid.UUID,
    payload: CompetenceScoreIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "manager")),
) -> dict[str, Any]:
    return await service.set_competence_score(
        db,
        current_user.tenant_id,
        current_user.id,
        assessment_id,
        competence_id,
        payload,
    )


@router.patch("/v1/assessments/{assessment_id}/indicator-scores/{indicator_id}")
async def set_indicator_score_endpoint(
    assessment_id: uuid.UUID,
    indicator_id: uuid.UUID,
    payload: IndicatorScoreIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "manager")),
) -> dict[str, Any]:
    return await service.set_indicator_score(
        db,
        current_user.tenant_id,
        current_user.id,
        assessment_id,
        indicator_id,
        payload,
    )


@router.post("/v1/assessments/{assessment_id}/submit")
async def submit_assessment_endpoint(
    assessment_id: uuid.UUID,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "manager")),
) -> dict[str, Any]:
    return await service.submit_assessment(
        db,
        current_user.tenant_id,
        current_user.id,
        assessment_id,
        final_notes=payload.get("final_notes"),
    )


# --- Invites ---------------------------------------------------------------


@router.post(
    "/v1/candidate-vacancies/{cv_id}/manager-assessment-invites",
    status_code=201,
)
async def create_invites_endpoint(
    cv_id: uuid.UUID,
    payload: ManagerAssessmentInviteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "manager")),
) -> list[dict[str, Any]]:
    return await service.create_invites(
        db,
        current_user.tenant_id,
        current_user.id,
        cv_id,
        payload,
    )


@router.get("/v1/candidate-vacancies/{cv_id}/manager-assessment-invites")
async def list_invites_endpoint(
    cv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await service.list_manager_invites(db, current_user.tenant_id, cv_id)


@router.post("/v1/manager-assessment-invites/{invite_id}/revoke")
async def revoke_invite_endpoint(
    invite_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "manager")),
) -> dict[str, Any]:
    return await service.revoke_invite(
        db, current_user.tenant_id, current_user.id, invite_id
    )


@router.post("/v1/manager-assessment-invites/{invite_id}/extend")
async def extend_invite_endpoint(
    invite_id: uuid.UUID,
    payload: ExtendInviteIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "manager")),
) -> dict[str, Any]:
    return await service.extend_invite(
        db,
        current_user.tenant_id,
        current_user.id,
        invite_id,
        payload.additional_days,
    )


# --- Public token endpoints (no JWT) -------------------------------------


def _client_ip(request: Request) -> str:
    # Trusted-proxy-aware (review P2-29); public token endpoints key their
    # abuse counters on this, so behind the LB it must resolve the real client.
    return client_ip(request) or ""


def _security_headers(response: Response) -> None:
    """Apply public-endpoint hardening headers (CSP, robots).

    The stricter page-level CSP for the evaluator UI lives in the
    frontend proxy; these headers only harden the raw JSON responses
    (direct navigation, search-engine fetches).
    """
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    # The payload carries candidate PII and a presigned resume URL — keep
    # it out of shared/browser caches.
    response.headers["Cache-Control"] = "no-store"


@public_router.get("/v1/public/assessments/{token}")
async def public_get_endpoint(
    token: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _security_headers(response)
    return await public_service.public_get_context(db, token, ip=_client_ip(request))


@public_router.post("/v1/public/assessments/{token}/consent/accept")
async def public_accept_endpoint(
    token: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _security_headers(response)
    return await public_service.public_accept_consent(db, token, ip=_client_ip(request))


@public_router.post("/v1/public/assessments/{token}/consent/decline")
async def public_decline_endpoint(
    token: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _security_headers(response)
    return await public_service.public_decline(db, token, ip=_client_ip(request))


@public_router.patch("/v1/public/assessments/{token}/name")
async def public_update_name_endpoint(
    token: str,
    payload: PublicEvaluatorNameUpdate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _security_headers(response)
    return await public_service.public_update_name(
        db, token, payload.name, ip=_client_ip(request)
    )


@public_router.patch("/v1/public/assessments/{token}/notes")
async def public_save_notes_endpoint(
    token: str,
    request: Request,
    response: Response,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _security_headers(response)
    notes = payload.get("final_notes")
    if not isinstance(notes, str):
        raise AppError("final_notes_required", status.HTTP_400_BAD_REQUEST)
    return await public_service.public_save_final_notes(
        db, token, notes, ip=_client_ip(request)
    )


@public_router.post("/v1/public/assessments/{token}/submit")
async def public_submit_endpoint(
    token: str,
    request: Request,
    response: Response,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _security_headers(response)
    return await public_service.public_submit(
        db,
        token,
        ip=_client_ip(request),
        final_notes=payload.get("final_notes"),
    )


@public_router.patch("/v1/public/assessments/{token}/competence-scores/{competence_id}")
async def public_set_competence_score_endpoint(
    token: str,
    competence_id: uuid.UUID,
    request: Request,
    response: Response,
    payload: CompetenceScoreIn,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _security_headers(response)
    return await public_service.public_set_competence_score(
        db,
        token,
        competence_id,
        payload.score_value,
        payload.comment,
        ip=_client_ip(request),
    )


@public_router.patch("/v1/public/assessments/{token}/indicator-scores/{indicator_id}")
async def public_set_indicator_score_endpoint(
    token: str,
    indicator_id: uuid.UUID,
    request: Request,
    response: Response,
    payload: IndicatorScoreIn,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _security_headers(response)
    return await public_service.public_set_indicator_score(
        db,
        token,
        indicator_id,
        payload.competence_id,
        payload.score_value,
        payload.comment,
        ip=_client_ip(request),
    )


@router.get(
    "/v1/dev/manager-assessment-invites/{invite_id}/token",
)
async def dev_get_manager_invite_token(
    invite_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Reveal a manager-assessment invite's raw token. E2E-only.

    Mirrors ``/auth/dev/invitations/{id}/token`` so the Playwright suite
    can drive the HRP-186 public flow without poking the DB directly.
    Returns 404 when ``E2E_MODE`` is off, exactly like the auth equivalent.
    """
    from sqlalchemy import select

    from app.config import settings
    from app.modules.recruitment.models import AssessmentInvite

    if not settings.e2e_mode:
        # Deliberately a bare HTTPException, not AppError: the response must
        # stay indistinguishable from a nonexistent route — an error code
        # would fingerprint the hidden dev surface.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    inv = (
        await db.execute(
            select(AssessmentInvite).where(AssessmentInvite.id == invite_id)
        )
    ).scalar_one_or_none()
    if inv is None or inv.token is None:
        raise AppError("invite_not_found", status.HTTP_404_NOT_FOUND)
    return {"token": inv.token}


__all__ = ["router", "public_router"]
