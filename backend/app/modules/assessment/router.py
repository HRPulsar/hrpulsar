import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.database import get_db
from app.modules.assessment import group_analytics, pdp_service, service
from app.modules.assessment.schemas import (
    AnswerRecord,
    AnswerScaleCreate,
    AnswerScaleDeleteResult,
    AnswerScaleDetailRead,
    AnswerScaleUpdate,
    AssessmentCreate,
    AssessmentDetail,
    AssessmentGroupDetail,
    AssessmentGroupUpdate,
    AssessmentList,
    AssessmentRead,
    AssessmentResultRead,
    AssessmentUpdate,
    BulkStatusChange,
    BulkStatusChangeResult,
    CalibrateRequest,
    CalibrateTotalsRequest,
    CPAAnalytics,
    CPACreate,
    CPACriteriaCreate,
    CPACriteriaRead,
    CPADetail,
    CPAParticipantAdd,
    CPAParticipantRead,
    CPARead,
    CriteriaUpdate,
    DetailedResultsResponse,
    ExternalAnswerSubmit,
    ExternalAssessmentInfo,
    ExternalReviewerCreate,
    ExternalReviewerRead,
    GradeOption,
    GroupAnalyticsResponse,
    GroupedAssessmentList,
    MassAssessmentCreate,
    ParticipantAdd,
    ParticipantRead,
    PDPCommentCreate,
    PDPCommentRead,
    PDPCreate,
    PDPDetail,
    PDPItemCreate,
    PDPItemPassUpdate,
    PDPItemRead,
    PDPItemReorder,
    PDPItemUpdate,
    PDPMaterialCreate,
    PDPMaterialRead,
    PDPMaterialUpdate,
    PDPRead,
    PDPUpdate,
    PDPVersionDetail,
    PDPVersionRead,
    ScaleAssign,
    SpecializationOption,
    StatusChange,
)
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User

router = APIRouter(tags=["assessments"])


# --- Assessment CRUD ---


@router.post("/assessments", response_model=AssessmentRead, status_code=201)
async def create_assessment(
    data: AssessmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_assessment(
        db, current_user.tenant_id, current_user.id, data
    )


@router.get("/assessments", response_model=AssessmentList)
async def list_assessments(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    employee_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.access_scope import get_visible_employee_ids, is_employee_only

    visible_ids = await get_visible_employee_ids(db, current_user)
    items, total = await service.list_assessments(
        db,
        current_user.tenant_id,
        employee_id,
        skip,
        limit,
        visible_employee_ids=visible_ids,
        participant_user_id=current_user.id,
        restrict_to_active=is_employee_only(current_user),
    )
    return {"items": items, "total": total}


@router.get("/assessments/{assessment_id}", response_model=AssessmentDetail)
async def get_assessment(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.access_scope import get_visible_employee_ids, is_employee_only

    visible_ids = await get_visible_employee_ids(db, current_user)
    return await service.get_assessment_detail(
        db,
        current_user.tenant_id,
        assessment_id,
        visible_employee_ids=visible_ids,
        participant_user_id=current_user.id,
        restrict_to_active=is_employee_only(current_user),
        hide_results_for_employee=is_employee_only(current_user),
    )


@router.post("/assessments/{assessment_id}/status", response_model=AssessmentRead)
async def change_status(
    assessment_id: uuid.UUID,
    data: StatusChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.change_status(
        db, current_user.tenant_id, assessment_id, data.status_code
    )


@router.patch("/assessments/{assessment_id}", response_model=AssessmentRead)
async def update_assessment(
    assessment_id: uuid.UUID,
    data: AssessmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    # Honour PATCH semantics: only forward fields the client actually sent.
    # `data.ended_at = None` means "clear deadline"; absence means "leave it".
    kwargs: dict[str, Any] = {}
    if "title" in data.model_fields_set:
        kwargs["title"] = data.title
    if "ended_at" in data.model_fields_set:
        kwargs["ended_at"] = data.ended_at
    return await service.update_assessment(
        db, current_user.tenant_id, assessment_id, **kwargs
    )


# --- Participants ---


@router.post(
    "/assessments/{assessment_id}/participants",
    response_model=ParticipantRead,
    status_code=201,
)
async def add_participant(
    assessment_id: uuid.UUID,
    data: ParticipantAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.add_participant(
        db, current_user.tenant_id, assessment_id, data
    )


# --- Competences / Criteria ---


class _LegacyCompetenceIds(BaseModel):
    competence_ids: list[uuid.UUID]


@router.post("/assessments/{assessment_id}/competences", status_code=201)
async def add_competences(
    assessment_id: uuid.UUID,
    data: _LegacyCompetenceIds,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.add_competences(
        db, current_user.tenant_id, assessment_id, data.competence_ids
    )


@router.put("/assessments/{assessment_id}/criteria", response_model=AssessmentDetail)
async def set_assessment_criteria(
    assessment_id: uuid.UUID,
    data: CriteriaUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.set_assessment_criteria(
        db, current_user.tenant_id, assessment_id, data
    )


@router.put(
    "/assessment-groups/{group_id}/criteria", response_model=AssessmentGroupDetail
)
async def set_group_criteria(
    group_id: uuid.UUID,
    data: CriteriaUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.set_group_criteria(db, current_user.tenant_id, group_id, data)


@router.get(
    "/assessments/criteria/specializations",
    response_model=list[SpecializationOption],
)
async def list_criteria_specializations(
    include_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    # HRP-292: include_id keeps a saved-but-deactivated specialization
    # selectable in the criteria sheet.
    return await service.list_criteria_specializations(
        db, current_user.tenant_id, include_id=include_id
    )


@router.get(
    "/assessments/criteria/specializations/{specialization_id}/grades",
    response_model=list[GradeOption],
)
async def list_criteria_grades(
    specialization_id: uuid.UUID,
    include_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.list_criteria_grades(
        db, current_user.tenant_id, specialization_id, include_id=include_id
    )


# --- Answers ---


@router.post("/assessments/{assessment_id}/answers", status_code=201)
async def record_answer(
    assessment_id: uuid.UUID,
    data: AnswerRecord,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.record_answer(
        db, current_user.tenant_id, current_user.id, assessment_id, data
    )


@router.get("/assessments/{assessment_id}/my-answers")
async def get_my_answers(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HRP-146: caller's own draft answers so the survey Sheet can
    rehydrate previously selected options when reopened."""
    return await service.get_participant_answers(
        db, current_user.tenant_id, current_user.id, assessment_id
    )


# --- Results ---


@router.get(
    "/assessments/{assessment_id}/results", response_model=list[AssessmentResultRead]
)
async def get_results(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # HRP-112: results inherit the same scope fence as `GET /assessments/{id}`.
    # Without this, a restricted caller can read calibrated scores via the URL.
    from app.core.access_scope import get_visible_employee_ids, is_employee_only

    visible_ids = await get_visible_employee_ids(db, current_user)
    return await service.get_results(
        db,
        current_user.tenant_id,
        assessment_id,
        visible_employee_ids=visible_ids,
        participant_user_id=current_user.id,
        restrict_to_active=is_employee_only(current_user),
        hide_results_for_employee=is_employee_only(current_user),
    )


@router.get(
    "/assessments/{assessment_id}/detailed-results",
    response_model=DetailedResultsResponse,
)
async def get_detailed_results(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role("admin", "manager", "platform_admin")
    ),
):
    """HRP-154: per-competence/skill-level/indicator breakdown for the
    Results page. RBAC matches the spec — Platform admin, Admin and
    Manager only; Employees get 403 from ``require_role``. The
    employee-id scope from ``get_results`` is reused so a manager
    can't peek at out-of-division assessments via the URL.
    """
    from app.core.access_scope import get_visible_employee_ids

    visible_ids = await get_visible_employee_ids(db, current_user)
    return await service.get_detailed_results(
        db,
        current_user.tenant_id,
        assessment_id,
        visible_employee_ids=visible_ids,
    )


@router.post(
    "/assessments/{assessment_id}/calibrate", response_model=list[AssessmentResultRead]
)
async def calibrate(
    assessment_id: uuid.UUID,
    data: CalibrateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.calibrate(
        db, current_user.tenant_id, assessment_id, data.results
    )


# HRP-185: per-indicator Total calibration -----------------------------------


@router.post(
    "/assessments/{assessment_id}/calibration/start",
    response_model=AssessmentDetail,
)
async def start_calibration(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.start_calibration(
        db, current_user.tenant_id, assessment_id
    )


@router.post(
    "/assessments/{assessment_id}/calibration/save",
    response_model=AssessmentDetail,
)
async def save_calibration(
    assessment_id: uuid.UUID,
    data: CalibrateTotalsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.save_calibration(
        db, current_user.tenant_id, assessment_id, data.totals
    )


@router.post(
    "/assessments/{assessment_id}/calibration/cancel",
    response_model=AssessmentDetail,
)
async def cancel_calibration(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.cancel_calibration(
        db, current_user.tenant_id, assessment_id
    )


# --- Answer Scales ---


@router.get("/answer-scales", response_model=list[AnswerScaleDetailRead])
async def list_scales(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_scales(db, current_user.tenant_id)


@router.post("/answer-scales", response_model=AnswerScaleDetailRead, status_code=201)
async def create_answer_scale(
    data: AnswerScaleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_answer_scale(db, current_user.tenant_id, data)


@router.get("/answer-scales/{scale_id}", response_model=AnswerScaleDetailRead)
async def get_answer_scale(
    scale_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_answer_scale(db, current_user.tenant_id, scale_id)


@router.put("/answer-scales/{scale_id}", response_model=AnswerScaleDetailRead)
async def update_answer_scale(
    scale_id: uuid.UUID,
    data: AnswerScaleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_answer_scale(db, current_user.tenant_id, scale_id, data)


@router.delete("/answer-scales/{scale_id}", response_model=AnswerScaleDeleteResult)
async def delete_answer_scale(
    scale_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.delete_answer_scale(db, current_user.tenant_id, scale_id)


@router.put("/assessments/{assessment_id}/scale", response_model=AssessmentDetail)
async def set_assessment_scale(
    assessment_id: uuid.UUID,
    data: ScaleAssign,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.set_assessment_scale(
        db, current_user.tenant_id, assessment_id, data.scale_id
    )


@router.put("/assessment-groups/{group_id}/scale", response_model=AssessmentGroupDetail)
async def set_group_scale(
    group_id: uuid.UUID,
    data: ScaleAssign,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.set_group_scale(
        db, current_user.tenant_id, group_id, data.scale_id
    )


# --- Mass Assessment (Groups) ---


@router.post(
    "/assessment-groups",
    response_model=AssessmentGroupDetail,
    status_code=201,
)
async def create_mass_assessment(
    data: MassAssessmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_mass_assessment(
        db, current_user.tenant_id, current_user.id, data
    )


@router.get("/assessments-grouped", response_model=GroupedAssessmentList)
async def list_assessments_grouped(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    # HRP-193: server-side filters so X-Y of N + pagination follow the
    # filtered slice instead of the (already-paged) raw list. Mirrors
    # the contract used by /employees: case-insensitive search + repeated
    # query params for multi-select filters (type=self&type=360&status=cancelled).
    search: str | None = Query(None, max_length=200),
    type: list[str] | None = Query(None),
    status: list[str] | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.access_scope import get_visible_employee_ids, is_employee_only

    visible_ids = await get_visible_employee_ids(db, current_user)
    items, total = await service.list_assessments_grouped(
        db,
        current_user.tenant_id,
        skip,
        limit,
        visible_employee_ids=visible_ids,
        participant_user_id=current_user.id,
        restrict_to_active=is_employee_only(current_user),
        search=search,
        type_codes=type,
        status_codes=status,
    )
    return {"items": items, "total": total}


@router.get("/assessment-groups/{group_id}", response_model=AssessmentGroupDetail)
async def get_assessment_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.access_scope import get_visible_employee_ids, is_employee_only

    visible_ids = await get_visible_employee_ids(db, current_user)
    return await service.get_assessment_group(
        db,
        current_user.tenant_id,
        group_id,
        visible_employee_ids=visible_ids,
        participant_user_id=current_user.id,
        restrict_to_active=is_employee_only(current_user),
    )


@router.get(
    "/assessment-groups/{group_id}/analytics",
    response_model=GroupAnalyticsResponse,
)
async def get_group_analytics(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HRP-528: aggregated analytics for a mass assessment.

    Read-only companion to ``GET /assessment-groups/{group_id}``, and it must
    carry exactly the same guard: tenant check plus the HRP-40 scope predicate
    (subtree / participant) and the Draft filter for regular employees.
    Without the scope arguments this route would hand any authenticated user
    every assessee's results in the group — the group page's own endpoint is
    scoped, so an unscoped analytics route would be the way around it.

    The scope predicate alone is not enough, though: its participant arm lets
    a respondent through to a colleague's child assessment, and this payload
    carries the results (percent, per-competence and per-grade matches) that
    ``GET /assessments/{id}/results`` deliberately withholds from an
    employee-only caller. Hence the same ``hide_results_for_employee`` gate as
    on the results route.
    """
    from app.core.access_scope import get_visible_employee_ids, is_employee_only

    visible_ids = await get_visible_employee_ids(db, current_user)
    return await group_analytics.get_group_analytics(
        db,
        current_user.tenant_id,
        group_id,
        visible_employee_ids=visible_ids,
        participant_user_id=current_user.id,
        restrict_to_active=is_employee_only(current_user),
        hide_results_for_employee=is_employee_only(current_user),
    )


@router.patch(
    "/assessment-groups/{group_id}",
    response_model=AssessmentGroupDetail,
)
async def update_assessment_group(
    group_id: uuid.UUID,
    data: AssessmentGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_assessment_group(
        db, current_user.tenant_id, group_id, title=data.title
    )


@router.post(
    "/assessment-groups/{group_id}/status",
    response_model=BulkStatusChangeResult,
)
async def bulk_change_status(
    group_id: uuid.UUID,
    data: BulkStatusChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.bulk_change_status(
        db, current_user.tenant_id, group_id, data.status_code
    )


# --- CPA ---


@router.post("/cpa", response_model=CPARead, status_code=201)
async def create_cpa(
    data: CPACreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_cpa(db, current_user.tenant_id, current_user.id, data)


@router.get("/cpa", response_model=list[CPARead])
async def list_cpas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.list_cpas(db, current_user.tenant_id)


@router.get("/cpa/{cpa_id}", response_model=CPADetail)
async def get_cpa_detail(
    cpa_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.get_cpa_detail(db, current_user.tenant_id, cpa_id)


@router.post("/cpa/{cpa_id}/criteria", response_model=CPACriteriaRead, status_code=201)
async def add_cpa_criteria(
    cpa_id: uuid.UUID,
    data: CPACriteriaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.add_cpa_criteria(db, current_user.tenant_id, cpa_id, data)


@router.post(
    "/cpa/{cpa_id}/participants", response_model=CPAParticipantRead, status_code=201
)
async def add_cpa_participant(
    cpa_id: uuid.UUID,
    data: CPAParticipantAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.add_cpa_participant(db, current_user.tenant_id, cpa_id, data)


@router.get("/cpa/{cpa_id}/analytics", response_model=CPAAnalytics)
async def get_cpa_analytics(
    cpa_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.get_cpa_analytics(db, current_user.tenant_id, cpa_id)


class CPACopyRequest(BaseModel):
    title: str = Field(max_length=255)


@router.post("/cpa/{cpa_id}/copy", response_model=CPARead, status_code=201)
async def copy_cpa(
    cpa_id: uuid.UUID,
    data: CPACopyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.copy_cpa(
        db, current_user.tenant_id, current_user.id, cpa_id, data.title
    )


# ===================================================================
# GF4: External Reviewers (anonymous / open access)
# ===================================================================


@router.post(
    "/assessments/{assessment_id}/external-reviewers",
    response_model=ExternalReviewerRead,
    status_code=201,
)
async def create_external_reviewer(
    assessment_id: uuid.UUID,
    data: ExternalReviewerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_external_reviewer(
        db, current_user.tenant_id, assessment_id, data.name, data.email, data.role
    )


@router.get(
    "/assessments/{assessment_id}/external-reviewers",
    response_model=list[ExternalReviewerRead],
)
async def list_external_reviewers(
    assessment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.list_external_reviewers(
        db, current_user.tenant_id, assessment_id
    )


@router.delete(
    "/assessments/{assessment_id}/external-reviewers/{reviewer_id}",
    response_model=ExternalReviewerRead,
)
async def delete_external_reviewer(
    assessment_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.delete_external_reviewer(
        db, current_user.tenant_id, reviewer_id
    )


# --- Public endpoints (no auth) ---


@router.get("/review/{token}", response_model=ExternalAssessmentInfo)
async def get_external_assessment(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    return await service.get_external_assessment(db, token)


@router.post("/review/{token}/submit")
async def submit_external_answers(
    token: str,
    data: ExternalAnswerSubmit,
    db: AsyncSession = Depends(get_db),
):
    return await service.submit_external_answers(db, token, data.answers)


# ===================================================================
# PDP
# ===================================================================


@router.post("/pdp", response_model=PDPRead, status_code=201)
async def create_pdp(
    data: PDPCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await pdp_service.create_pdp(
        db, current_user.tenant_id, current_user.id, data
    )


@router.get("/pdp", response_model=list[PDPRead])
async def list_pdps(
    employee_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.access_scope import (
        ADMIN_ROLE_CODES,
        MANAGER_ROLE_CODES,
        get_visible_employee_ids,
    )

    visible_ids = await get_visible_employee_ids(db, current_user)
    # HRP-19 + HRP-142: only the plan owner is hidden from drafts (their own
    # authoring queue is irrelevant to them). Admins/HR/platform_admin and
    # division managers (incl. deputies) see drafts inside their visibility
    # scope so they can pick up Plans created for their team.
    privileged = any(
        r.code in (ADMIN_ROLE_CODES | MANAGER_ROLE_CODES)
        for r in current_user.roles
    )
    return await pdp_service.list_pdps(
        db,
        current_user.tenant_id,
        employee_id,
        visible_employee_ids=visible_ids,
        hide_drafts=not privileged,
    )


@router.get("/pdp/{pdp_id}", response_model=PDPDetail)
async def get_pdp(
    pdp_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await pdp_service.get_pdp_detail(
        db,
        current_user.tenant_id,
        pdp_id,
        viewer_user_id=current_user.id,
    )


@router.patch("/pdp/{pdp_id}", response_model=PDPRead)
async def update_pdp(
    pdp_id: uuid.UUID,
    data: PDPUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await pdp_service.update_pdp(db, current_user.tenant_id, pdp_id, data)


@router.post("/pdp/{pdp_id}/status", response_model=PDPRead)
async def change_pdp_status(
    pdp_id: uuid.UUID,
    data: StatusChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # HRP-19: the plan owner needs a single transition path — submit for
    # review — out of sent / in_progress / returned. Admins / managers keep
    # the full transition graph as before. We do the role/owner split here
    # rather than via two endpoints so the frontend keeps using one URL.
    from app.core.access_scope import ADMIN_ROLE_CODES, MANAGER_ROLE_CODES

    privileged = any(
        r.code in (ADMIN_ROLE_CODES | MANAGER_ROLE_CODES) for r in current_user.roles
    )
    if not privileged:
        from fastapi import status as http_status
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.modules.assessment.models import PDP, PDPItem

        pdp = await pdp_service._get_pdp(db, current_user.tenant_id, pdp_id)
        employee_user_id = getattr(getattr(pdp, "employee", None), "user_id", None)
        is_owner = employee_user_id is not None and employee_user_id == current_user.id
        owner_allowed = (
            is_owner
            and pdp.status in {"sent", "in_progress", "returned"}
            and data.status_code == "review"
        )
        if not owner_allowed:
            raise AppError(
                "pdp_status_change_forbidden", http_status.HTTP_403_FORBIDDEN
            )
        # HRP-19 case 2: the owner can only submit for review once every item
        # is marked passed. UI keeps the button disabled until then but we
        # block bypass at the API too.
        items_result = await db.execute(
            select(PDP).options(selectinload(PDP.items)).where(PDP.id == pdp_id)
        )
        pdp_with_items = items_result.scalar_one()
        items: list[PDPItem] = list(pdp_with_items.items)
        if not items or any(not it.is_passed for it in items):
            raise AppError(
                "pdp_mark_all_items_before_review",
                http_status.HTTP_409_CONFLICT,
            )
        # HRP-19 case 3: the strict transition map only allows admins to
        # bounce a returned plan back to sent/cancelled, but the owner can
        # legitimately submit for review out of ``returned``. We've already
        # confirmed the owner case above, so let the service skip the map.
        return await pdp_service.change_pdp_status(
            db,
            current_user.tenant_id,
            pdp_id,
            data.status_code,
            bypass_transition_check=True,
        )
    return await pdp_service.change_pdp_status(
        db, current_user.tenant_id, pdp_id, data.status_code
    )


@router.post("/pdp/{pdp_id}/items", response_model=PDPItemRead, status_code=201)
async def add_pdp_item(
    pdp_id: uuid.UUID,
    data: PDPItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await pdp_service.add_item(db, current_user.tenant_id, pdp_id, data)


@router.patch("/pdp/{pdp_id}/items/{item_id}", response_model=PDPItemRead)
async def update_pdp_item(
    pdp_id: uuid.UUID,
    item_id: uuid.UUID,
    data: PDPItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await pdp_service.update_item(
        db, current_user.tenant_id, pdp_id, item_id, data
    )


@router.delete("/pdp/{pdp_id}/items/{item_id}", status_code=204)
async def delete_pdp_item(
    pdp_id: uuid.UUID,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    await pdp_service.delete_item(db, current_user.tenant_id, pdp_id, item_id)
    return None


@router.post("/pdp/{pdp_id}/items/reorder", response_model=list[PDPItemRead])
async def reorder_pdp_items(
    pdp_id: uuid.UUID,
    data: PDPItemReorder,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await pdp_service.reorder_items(
        db, current_user.tenant_id, pdp_id, data.ordered_ids
    )


@router.post("/pdp/{pdp_id}/items/{item_id}/pass")
async def mark_item_passed(
    pdp_id: uuid.UUID,
    item_id: uuid.UUID,
    data: PDPItemPassUpdate = Body(default=PDPItemPassUpdate()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # HRP-13/19/130: who can toggle depends on the plan status — owner while
    # the plan is in sent/in_progress/returned, admin or assigned reviewer
    # while it's under review. The service enforces both axes.
    from app.core.access_scope import ADMIN_ROLE_CODES

    is_admin = any(r.code in ADMIN_ROLE_CODES for r in current_user.roles)
    return await pdp_service.mark_item_passed(
        db,
        current_user.tenant_id,
        pdp_id,
        item_id,
        current_user.id,
        is_passed=data.is_passed,
        is_admin=is_admin,
    )


@router.post(
    "/pdp/{pdp_id}/items/{item_id}/materials",
    response_model=PDPMaterialRead,
    status_code=201,
)
async def add_pdp_material(
    pdp_id: uuid.UUID,
    item_id: uuid.UUID,
    data: PDPMaterialCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await pdp_service.add_material(
        db, current_user.tenant_id, pdp_id, item_id, data
    )


@router.patch(
    "/pdp/{pdp_id}/items/{item_id}/materials/{material_id}",
    response_model=PDPMaterialRead,
)
async def update_pdp_material(
    pdp_id: uuid.UUID,
    item_id: uuid.UUID,
    material_id: uuid.UUID,
    data: PDPMaterialUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await pdp_service.update_material(
        db, current_user.tenant_id, pdp_id, item_id, material_id, data
    )


@router.delete(
    "/pdp/{pdp_id}/items/{item_id}/materials/{material_id}",
    status_code=204,
)
async def delete_pdp_material(
    pdp_id: uuid.UUID,
    item_id: uuid.UUID,
    material_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    await pdp_service.delete_material(
        db, current_user.tenant_id, pdp_id, item_id, material_id
    )
    return None


@router.post("/pdp/{pdp_id}/comments", response_model=PDPCommentRead, status_code=201)
async def add_pdp_comment(
    pdp_id: uuid.UUID,
    data: PDPCommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await pdp_service.add_comment(
        db, current_user.tenant_id, pdp_id, current_user.id, data
    )


# --- GF12: PDP Versions ---


@router.get("/pdp/{pdp_id}/versions", response_model=list[PDPVersionRead])
async def list_pdp_versions(
    pdp_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await pdp_service.list_versions(db, current_user.tenant_id, pdp_id)


@router.get("/pdp/{pdp_id}/versions/{version_id}", response_model=PDPVersionDetail)
async def get_pdp_version(
    pdp_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await pdp_service.get_version(db, current_user.tenant_id, pdp_id, version_id)


@router.post("/pdp/{pdp_id}/versions/{version_id}/restore")
async def restore_pdp_version(
    pdp_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await pdp_service.restore_version(
        db, current_user.tenant_id, pdp_id, version_id
    )
