"""Report endpoints: generation, templates, comparison, sharing, analytics (R4a/R4c)."""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
)
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.recruitment import (
    analytics_service,
    audit_service,
    service,
    share_service,
)
from app.modules.recruitment.routers.common import recruitment_public_limiter
from app.modules.recruitment.schemas import (
    AnalyticsSummary,
    ComparisonRadar,
    ComparisonRead,
    ReportExportRead,
    ReportGenerateRequest,
    ReportGenerateResponse,
    ReportPreviewRead,
    ReportShareCreate,
    ReportSharePublicView,
    ReportShareRead,
    ReportTemplateCreate,
    ReportTemplateRead,
    ReportTemplateUpdate,
    VacancyAnalytics,
)

router = APIRouter(tags=["recruitment"])


# ── Reports & Templates (R4a) ────────────────────────────────────────


@router.post(
    "/recruitment/vacancies/{vacancy_id}/reports",
    response_model=ReportGenerateResponse,
    status_code=202,
)
async def generate_vacancy_report(
    vacancy_id: uuid.UUID,
    data: ReportGenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hr", "hrd")),
):
    """Enqueue an XLSX consolidated report for the given vacancy."""

    result = await service.enqueue_report(
        db, current_user.tenant_id, current_user.id, vacancy_id, data
    )
    # HRP-268 — augment the generic ``report.generate`` audit row with
    # the audience + candidate-set scope so a downstream auditor can
    # answer "who shipped a hiring-manager-redacted report to whom".
    candidate_scope = (
        len(data.candidate_vacancy_ids)
        if data.candidate_vacancy_ids
        else "all"
    )
    await audit_service.record_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="report.generate.scope",
        entity_type="report",
        entity_id=result["export_id"],
        payload_diff={
            "audience": (data.audience or "recruiter"),
            "candidate_scope": candidate_scope,
        },
        request=request,
    )
    return result


@router.get("/recruitment/vacancies/{vacancy_id}/reports")
async def list_vacancy_reports(
    vacancy_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = await service.list_reports(
        db,
        current_user.tenant_id,
        vacancy_id=vacancy_id,
        status_filter=status,
        skip=skip,
        limit=limit,
    )
    return {"items": items, "total": total}


@router.get("/recruitment/reports")
async def list_all_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    vacancy_id: uuid.UUID | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = await service.list_reports(
        db,
        current_user.tenant_id,
        vacancy_id=vacancy_id,
        status_filter=status,
        skip=skip,
        limit=limit,
    )
    return {"items": items, "total": total}


@router.get("/recruitment/reports/{export_id}", response_model=ReportExportRead)
async def get_report(
    export_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_report(db, current_user.tenant_id, export_id)


@router.delete("/recruitment/reports/{export_id}", status_code=204)
async def delete_report(
    export_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    await service.delete_report(db, current_user.tenant_id, export_id)
    return Response(status_code=204)


@router.get(
    "/recruitment/reports/{export_id}/preview",
    response_model=ReportPreviewRead,
)
async def get_report_preview(
    export_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Inline XLSX preview — every sheet rendered as a JSON cell matrix."""
    return await service.get_report_preview(db, current_user.tenant_id, export_id)


@router.get(
    "/recruitment/report-templates",
    response_model=list[ReportTemplateRead],
)
async def list_report_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_report_templates(db, current_user.tenant_id)


@router.post(
    "/recruitment/report-templates",
    response_model=ReportTemplateRead,
    status_code=201,
)
async def create_report_template(
    data: ReportTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.create_report_template(
        db, current_user.tenant_id, data
    )


@router.put(
    "/recruitment/report-templates/{template_id}",
    response_model=ReportTemplateRead,
)
async def update_report_template(
    template_id: uuid.UUID,
    data: ReportTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.update_report_template(
        db, current_user.tenant_id, template_id, data
    )


@router.delete(
    "/recruitment/report-templates/{template_id}",
    status_code=204,
)
async def delete_report_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_report_template(
        db, current_user.tenant_id, template_id
    )
    return Response(status_code=204)


# ── Candidate comparison (R4a, SCR-55/56) ────────────────────────────


@router.get(
    "/recruitment/vacancies/{vacancy_id}/comparison",
    response_model=ComparisonRead,
)
async def compare_vacancy_candidates(
    vacancy_id: uuid.UUID,
    candidate_ids: list[uuid.UUID] = Query(..., alias="candidate_ids"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    role = service.resolve_user_role(current_user)
    return await service.compare_candidates(
        db,
        current_user.tenant_id,
        vacancy_id,
        candidate_ids,
        role=role,
    )


# ── R4c: Report sharing (FR-22, SCR-84) ──────────────────────────────


@router.post(
    "/recruitment/reports/{report_id}/share",
    response_model=ReportShareRead,
    status_code=201,
)
async def share_report(
    report_id: uuid.UUID,
    data: ReportShareCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await share_service.create_share(
        db,
        current_user.tenant_id,
        current_user.id,
        report_id,
        recipients=[str(e) for e in data.recipients],
        expires_in_days=data.expires_in_days,
        message=data.message,
    )


@router.get(
    "/recruitment/reports/{report_id}/shares",
    response_model=list[ReportShareRead],
)
async def list_report_shares(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await share_service.list_shares(
        db, current_user.tenant_id, report_id
    )


@router.delete(
    "/recruitment/reports/{report_id}/shares/{share_id}",
    status_code=204,
)
async def revoke_report_share(
    report_id: uuid.UUID,
    share_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    await share_service.revoke_share(
        db, current_user.tenant_id, current_user.id, report_id, share_id
    )
    return Response(status_code=204)


@router.get(
    "/reports/share/{token}",
    response_model=ReportSharePublicView,
    tags=["recruitment-public"],
)
@recruitment_public_limiter.limit("60/minute")
async def open_shared_report(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    return await share_service.open_share(db, token)


# ── R4c: Analytics (SCR-16, SCR-28, SCR-56) ──────────────────────────


@router.get(
    "/recruitment/vacancies/{vacancy_id}/analytics",
    response_model=VacancyAnalytics,
)
async def get_vacancy_analytics(
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await analytics_service.vacancy_analytics(
        db, current_user.tenant_id, vacancy_id
    )


@router.get(
    "/recruitment/analytics/summary",
    response_model=AnalyticsSummary,
)
async def get_recruitment_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hr", "hrd", "recruiter")),
):
    return await analytics_service.recruitment_summary(
        db, current_user.tenant_id
    )


@router.get(
    "/recruitment/vacancies/{vacancy_id}/comparison-radar",
    response_model=ComparisonRadar,
)
async def get_comparison_radar(
    vacancy_id: uuid.UUID,
    candidate_ids: list[uuid.UUID] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await analytics_service.comparison_radar(
        db, current_user.tenant_id, vacancy_id, candidate_ids
    )
