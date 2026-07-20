"""REST endpoints for recruitment settings hub, audit log, GDPR (R4b)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.recruitment import (
    audit_service,
    gdpr_service,
    settings_service,
)
from app.modules.recruitment.settings_schemas import (
    BrandingRead,
    BrandingUpdate,
    GDPREraseRequest,
    GDPRErasureRead,
    GDPRExportRead,
    GDPRExportRequestCreate,
    LLMProviderCreate,
    LLMProviderRead,
    LLMProviderUpdate,
    MatrixSettingsRead,
    MatrixSettingsUpdate,
    RecruitmentRoleRead,
    RetentionRead,
    RetentionUpdate,
    ScaleConfigCreate,
    ScaleConfigRead,
    ScaleConfigUpdate,
    TranscriptionProviderCreate,
    TranscriptionProviderRead,
    TranscriptionProviderUpdate,
)

router = APIRouter(tags=["recruitment-settings"])


# ─── Scales ─────────────────────────────────────────────────────────
#
# list_scales / get_active_scale are intentionally gated only by
# ``get_current_user`` (no ``require_role``) because every recruitment
# UI that renders a score — interview-analysis page, candidate cards,
# review forms — must read the active scale regardless of the viewer's
# role. Mutating endpoints below still require admin. The corresponding
# entries in ``BILLING_EXEMPT`` carry the same justification.


@router.get("/recruitment/settings/scales", response_model=list[ScaleConfigRead])
async def list_scales(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await settings_service.list_scales(db, current_user.tenant_id)


@router.get(
    "/recruitment/settings/scales/active",
    response_model=ScaleConfigRead | None,
)
async def get_active_scale(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await settings_service.get_active_scale(db, current_user.tenant_id)


@router.post(
    "/recruitment/settings/scales",
    response_model=ScaleConfigRead,
    status_code=201,
)
async def create_scale(
    data: ScaleConfigCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    scale = await settings_service.create_scale(db, current_user.tenant_id, data)
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="scale.create",
        entity_type="scale",
        entity_id=scale.id,
        payload_diff={"after": data.model_dump()},
        request=request,
    )
    return scale


@router.put("/recruitment/settings/scales/{scale_id}", response_model=ScaleConfigRead)
async def update_scale(
    scale_id: uuid.UUID,
    data: ScaleConfigUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    scale = await settings_service.update_scale(
        db, current_user.tenant_id, scale_id, data
    )
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="scale.update",
        entity_type="scale",
        entity_id=scale.id,
        payload_diff={"changes": data.model_dump(exclude_unset=True)},
        request=request,
    )
    return scale


@router.delete("/recruitment/settings/scales/{scale_id}", status_code=204)
async def delete_scale(
    scale_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await settings_service.delete_scale(db, current_user.tenant_id, scale_id)
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="scale.delete",
        entity_type="scale",
        entity_id=scale_id,
        request=request,
    )
    return Response(status_code=204)


# ─── LLM providers ──────────────────────────────────────────────────


@router.get(
    "/recruitment/settings/llm-providers",
    response_model=list[LLMProviderRead],
)
async def list_llm_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    rows = await settings_service.list_llm_providers(db, current_user.tenant_id)
    return [settings_service.llm_provider_to_read(r) for r in rows]


@router.post(
    "/recruitment/settings/llm-providers",
    response_model=LLMProviderRead,
    status_code=201,
)
async def create_llm_provider(
    data: LLMProviderCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    cfg = await settings_service.create_llm_provider(db, current_user.tenant_id, data)
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="llm_provider.create",
        entity_type="llm_provider",
        entity_id=cfg.id,
        payload_diff={
            "provider": data.provider,
            "model": data.model,
            "is_active": data.is_active,
        },
        request=request,
    )
    return settings_service.llm_provider_to_read(cfg)


@router.put(
    "/recruitment/settings/llm-providers/{config_id}",
    response_model=LLMProviderRead,
)
async def update_llm_provider(
    config_id: uuid.UUID,
    data: LLMProviderUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    cfg = await settings_service.update_llm_provider(
        db, current_user.tenant_id, config_id, data
    )
    diff = data.model_dump(exclude_unset=True)
    if "api_key" in diff:
        diff["api_key"] = "[redacted]"
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="llm_provider.update",
        entity_type="llm_provider",
        entity_id=cfg.id,
        payload_diff={"changes": diff},
        request=request,
    )
    return settings_service.llm_provider_to_read(cfg)


@router.delete("/recruitment/settings/llm-providers/{config_id}", status_code=204)
async def delete_llm_provider(
    config_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await settings_service.delete_llm_provider(db, current_user.tenant_id, config_id)
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="llm_provider.delete",
        entity_type="llm_provider",
        entity_id=config_id,
        request=request,
    )
    return Response(status_code=204)


# ─── Transcription providers ────────────────────────────────────────


@router.get(
    "/recruitment/settings/transcription-providers",
    response_model=list[TranscriptionProviderRead],
)
async def list_transcription_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    rows = await settings_service.list_transcription_providers(
        db, current_user.tenant_id
    )
    return [settings_service.transcription_provider_to_read(r) for r in rows]


@router.post(
    "/recruitment/settings/transcription-providers",
    response_model=TranscriptionProviderRead,
    status_code=201,
)
async def create_transcription_provider(
    data: TranscriptionProviderCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    cfg = await settings_service.create_transcription_provider(
        db, current_user.tenant_id, data
    )
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="transcription_provider.create",
        entity_type="transcription_provider",
        entity_id=cfg.id,
        payload_diff={"provider": data.provider, "is_active": data.is_active},
        request=request,
    )
    return settings_service.transcription_provider_to_read(cfg)


@router.put(
    "/recruitment/settings/transcription-providers/{config_id}",
    response_model=TranscriptionProviderRead,
)
async def update_transcription_provider(
    config_id: uuid.UUID,
    data: TranscriptionProviderUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    cfg = await settings_service.update_transcription_provider(
        db, current_user.tenant_id, config_id, data
    )
    diff = data.model_dump(exclude_unset=True)
    if "api_key" in diff:
        diff["api_key"] = "[redacted]"
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="transcription_provider.update",
        entity_type="transcription_provider",
        entity_id=cfg.id,
        payload_diff={"changes": diff},
        request=request,
    )
    return settings_service.transcription_provider_to_read(cfg)


@router.delete(
    "/recruitment/settings/transcription-providers/{config_id}",
    status_code=204,
)
async def delete_transcription_provider(
    config_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await settings_service.delete_transcription_provider(
        db, current_user.tenant_id, config_id
    )
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="transcription_provider.delete",
        entity_type="transcription_provider",
        entity_id=config_id,
        request=request,
    )
    return Response(status_code=204)


# ─── Branding ───────────────────────────────────────────────────────


@router.get("/recruitment/settings/ui")
async def get_ui_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HRP-205 REDO: read-only tenant UI flags for any authenticated user.

    Deliberately NOT behind ``require_role`` — hiring managers use
    ``hm_questions_above_resume`` to reorder candidate-page sections,
    and the branding hub endpoint is closed to them.
    """
    return await settings_service.get_ui_settings(db, current_user.tenant_id)


@router.get("/recruitment/settings/branding", response_model=BrandingRead)
async def get_branding(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hrd")),
):
    return await settings_service.get_branding(db, current_user.tenant_id)


@router.put("/recruitment/settings/branding", response_model=BrandingRead)
async def update_branding(
    data: BrandingUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await settings_service.update_branding(db, current_user.tenant_id, data)
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="branding.update",
        entity_type="branding",
        entity_id=current_user.tenant_id,
        payload_diff={"changes": data.model_dump(exclude_unset=True)},
        request=request,
    )
    return result


# ─── Retention ──────────────────────────────────────────────────────


@router.get("/recruitment/settings/retention", response_model=RetentionRead)
async def get_retention(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hrd")),
):
    return await settings_service.get_retention(db, current_user.tenant_id)


@router.put("/recruitment/settings/retention", response_model=RetentionRead)
async def update_retention(
    data: RetentionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await settings_service.update_retention(db, current_user.tenant_id, data)
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="retention.update",
        entity_type="retention",
        entity_id=current_user.tenant_id,
        payload_diff={"changes": data.model_dump(exclude_unset=True)},
        request=request,
    )
    return result


# ─── Matrix settings (HRP-265) ──────────────────────────────────────


@router.get("/recruitment/settings/matrix", response_model=MatrixSettingsRead)
async def get_matrix_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role("admin", "recruiter", "hrd", "hr", "hiring_manager")
    ),
):
    """Read-only view of the divergence threshold used by Compact matrix.

    Every recruitment role needs the threshold to render the matrix
    consistently; only admins can edit it via PUT.
    """
    return await settings_service.get_matrix_settings(db, current_user.tenant_id)


@router.put("/recruitment/settings/matrix", response_model=MatrixSettingsRead)
async def update_matrix_settings(
    data: MatrixSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await settings_service.update_matrix_settings(
        db, current_user.tenant_id, data
    )
    # Only emit an audit row when the caller actually changed something —
    # an empty body or a body with only explicit ``null`` fields silently
    # no-ops in the service layer, and a noisy ``matrix_settings.update``
    # with ``changes: {}`` / ``{threshold: null}`` confuses the forensic
    # timeline ("who changed the threshold?" answers itself).
    raw_changes = data.model_dump(exclude_unset=True)
    changes = {k: v for k, v in raw_changes.items() if v is not None}
    if changes:
        await audit_service.record_event(
            db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="matrix_settings.update",
            entity_type="matrix_settings",
            entity_id=current_user.tenant_id,
            payload_diff={"changes": changes},
            request=request,
        )
    return result


# ─── Roles read-only ────────────────────────────────────────────────


@router.get("/recruitment/settings/roles", response_model=list[RecruitmentRoleRead])
async def list_roles(
    current_user: User = Depends(require_role("admin", "hrd")),
):
    return settings_service.list_roles()


# ─── Audit log ──────────────────────────────────────────────────────


@router.get("/recruitment/audit-log", response_model=dict)
async def list_audit_events(
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    action: str | None = None,
    user_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hrd")),
):
    items, total = await audit_service.list_events(
        db,
        current_user.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        user_id=user_id,
        since=since,
        until=until,
        skip=skip,
        limit=limit,
    )
    return {"items": items, "total": total}


# ─── GDPR ────────────────────────────────────────────────────────────


@router.post(
    "/recruitment/gdpr-export",
    response_model=GDPRExportRead,
    status_code=202,
)
async def gdpr_export(
    data: GDPRExportRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hrd")),
):
    req = await gdpr_service.gdpr_export(
        db, current_user.tenant_id, current_user.id, data
    )
    # Export now runs on Celery; the row comes back ``processing`` and the
    # download link lands once the worker finishes. Audit the request itself
    # (who/when/IP) — completion/failure is reflected in the row status the
    # GDPR page polls.
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="gdpr.export",
        entity_type="candidate",
        entity_id=req.subject_id,
        payload_diff={"export_id": str(req.id), "status": req.status},
        request=request,
    )
    file_url = await gdpr_service.resolve_export_url(db, current_user.tenant_id, req)
    return gdpr_service.export_to_read(req, file_url=file_url)


@router.post("/recruitment/gdpr-erase", response_model=GDPRErasureRead, status_code=200)
async def gdpr_erase(
    data: GDPREraseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hrd")),
):
    if not data.confirm:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Erasure requires confirm=true",
        )
    log_row = await gdpr_service.gdpr_erase(
        db, current_user.tenant_id, current_user.id, data.candidate_id
    )
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="gdpr.erase",
        entity_type="candidate",
        entity_id=data.candidate_id,
        payload_diff={"affected": log_row.affected},
        request=request,
    )
    return {
        "id": log_row.id,
        "subject_type": log_row.subject_type,
        "subject_id": log_row.subject_id,
        "requested_by": log_row.requested_by,
        "affected": log_row.affected,
        "created_at": log_row.created_at,
    }


@router.get(
    "/recruitment/gdpr-requests",
    response_model=dict,
)
async def list_gdpr_requests(
    candidate_id: uuid.UUID | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hrd")),
):
    rows = await gdpr_service.list_export_requests(
        db,
        current_user.tenant_id,
        candidate_id=candidate_id,
        skip=skip,
        limit=limit,
    )
    items = []
    for r in rows:
        url = await gdpr_service.resolve_export_url(db, current_user.tenant_id, r)
        items.append(gdpr_service.export_to_read(r, file_url=url))
    return {"items": items, "total": len(items)}
