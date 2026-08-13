"""Assessment endpoints: questions, human scores, versions, invites, canvas, matrix, question sets."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Query,
    Request,
)
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.recruitment import (
    question_service,
    service,
)
from app.modules.recruitment.routers.common import recruitment_public_limiter
from app.modules.recruitment.schemas import (
    AssessmentRevertRequest,
    AssessmentScoreCreate,
    AssessmentScoreRead,
    AssessmentScoreUpdate,
    GenerateQuestionSetRequest,
    InviteCreate,
    InviteRead,
    QuestionCreate,
    QuestionCreate2,
    QuestionRead,
    QuestionRead2,
    QuestionSetExportRequest,
    QuestionSetRead,
    QuestionsPDFExportRequest,
    QuestionUpdate,
    QuestionUpdate2,
    VacancyQuestionsRead,
)

router = APIRouter(tags=["recruitment"])


# ── Candidate Questions ───────────────────────────────────────────


@router.get(
    "/recruitment/candidates/{candidate_id}/questions",
    response_model=list[QuestionRead],
)
async def list_questions(
    candidate_id: uuid.UUID,
    vacancy_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_questions(
        db, current_user.tenant_id, candidate_id, vacancy_id=vacancy_id
    )


@router.post(
    "/recruitment/candidates/{candidate_id}/vacancies/{vacancy_id}/questions",
    response_model=QuestionRead,
    status_code=201,
)
async def add_question(
    candidate_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    data: QuestionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hiring_manager")),
):
    return await service.add_question(
        db, current_user.tenant_id, candidate_id, vacancy_id, data
    )


@router.put(
    "/recruitment/questions/{question_id}",
    response_model=QuestionRead,
)
async def update_question(
    question_id: uuid.UUID,
    data: QuestionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hiring_manager")),
):
    return await service.update_question(db, current_user.tenant_id, question_id, data)


@router.delete("/recruitment/questions/{question_id}", status_code=204)
async def delete_question(
    question_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hiring_manager")),
):
    await service.delete_question(db, current_user.tenant_id, question_id)


@router.post(
    "/recruitment/candidates/{candidate_id}/vacancies/{vacancy_id}/questions/pdf"
)
async def export_questions_pdf(
    candidate_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    data: QuestionsPDFExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hiring_manager")),
):
    pdf_bytes = await service.export_questions_pdf(
        db,
        current_user.tenant_id,
        candidate_id,
        vacancy_id,
        include_good=data.include_good,
        include_acceptable=data.include_acceptable,
        include_poor=data.include_poor,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="questions-{candidate_id}.pdf"'
            )
        },
    )


@router.post(
    "/recruitment/candidates/{candidate_id}/vacancies/{vacancy_id}/generate-questions",
    status_code=202,
)
async def generate_questions(
    candidate_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    """Queue AI question generation task."""
    await service.get_candidate(db, current_user.tenant_id, candidate_id)
    await service.get_vacancy(db, current_user.tenant_id, vacancy_id)
    from app.modules.recruitment.tasks import generate_questions_task

    result = generate_questions_task.delay(
        str(candidate_id), str(vacancy_id), str(current_user.tenant_id)
    )
    return {"task_id": result.id, "status": "queued"}


# ── Human Assessments ─────────────────────────────────────────────


@router.post(
    "/recruitment/candidate-vacancies/{cv_id}/assessments",
    response_model=AssessmentScoreRead,
    status_code=201,
)
async def record_assessment(
    cv_id: uuid.UUID,
    data: AssessmentScoreCreate,
    response: Response,
    request: Request,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hiring_manager")),
):
    result = await service.record_human_assessment(
        db,
        current_user.tenant_id,
        cv_id,
        current_user.id,
        data,
        if_match=if_match,
        request=request,
    )
    response.headers["ETag"] = service.assessment_etag(result["version"])
    return result


@router.patch(
    "/recruitment/assessments/{assessment_id}",
    response_model=AssessmentScoreRead,
)
async def update_assessment(
    assessment_id: uuid.UUID,
    data: AssessmentScoreUpdate,
    response: Response,
    request: Request,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hiring_manager")),
):
    result = await service.update_human_assessment(
        db,
        current_user.tenant_id,
        assessment_id,
        data,
        if_match=if_match,
        initiator_id=current_user.id,
        request=request,
    )
    response.headers["ETag"] = service.assessment_etag(result["version"])
    return result


@router.get("/recruitment/candidate-vacancies/{cv_id}/assessments")
async def list_assessments(
    cv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_assessments(db, current_user.tenant_id, cv_id)


# ── Assessment Versions panel (HRP-266) ──────────────────────────


@router.get("/recruitment/vacancies/{vacancy_id}/assessment-history")
async def list_assessment_history(
    vacancy_id: uuid.UUID,
    evaluator_id: uuid.UUID | None = None,
    candidate_vacancy_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    only_divergence: bool = False,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role("admin", "recruiter", "hrd", "hr", "hiring_manager")
    ),
):
    """Versions-panel timeline — vacancy-scoped audit of assessment edits."""
    items, total = await service.list_assessment_history(
        db,
        current_user.tenant_id,
        vacancy_id,
        evaluator_id=evaluator_id,
        candidate_vacancy_id=candidate_vacancy_id,
        since=since,
        until=until,
        only_divergence=only_divergence,
        skip=skip,
        limit=limit,
    )
    return {"items": items, "total": total}


@router.post(
    "/recruitment/candidate-vacancies/{cv_id}/assessments"
    "/{competence_id}/evaluators/{evaluator_id}/revert",
    response_model=AssessmentScoreRead,
)
async def revert_assessment(
    cv_id: uuid.UUID,
    competence_id: uuid.UUID,
    evaluator_id: uuid.UUID,
    data: AssessmentRevertRequest,
    response: Response,
    request: Request,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hiring_manager")),
):
    """Restore an evaluator's cell to a prior audit-event score (HRP-266).

    The body must carry ``audit_event_id`` — the UI selects the source
    row from the Versions panel before confirming. Optional ``If-Match``
    refuses the revert when the cell advanced between the Versions panel
    render and the click. Role set matches the write endpoints (admin /
    recruiter / hiring_manager) so a HM who scored a 5 by mistake can
    self-revert via the same Versions panel they opened to inspect it.
    """
    result = await service.revert_human_assessment(
        db,
        current_user.tenant_id,
        cv_id,
        competence_id,
        evaluator_id,
        data.audit_event_id,
        initiator_id=current_user.id,
        if_match=if_match,
        request=request,
    )
    response.headers["ETag"] = service.assessment_etag(result["version"])
    return result


# ── Assessment Invites ────────────────────────────────────────────


@router.post(
    "/recruitment/candidate-vacancies/{cv_id}/invites",
    response_model=InviteRead,
    status_code=201,
)
async def create_invite(
    cv_id: uuid.UUID,
    data: InviteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    return await service.create_assessment_invite(
        db, current_user.tenant_id, cv_id, data
    )


@router.get("/recruitment/candidate-vacancies/{cv_id}/invites")
async def list_invites(
    cv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_invites(db, current_user.tenant_id, cv_id)


@router.get("/recruitment/invite/{token}")
@recruitment_public_limiter.limit("60/minute")
async def get_invite(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — no auth, token-based access."""
    invite = await service.get_invite_by_token(db, token)
    if not invite:
        from fastapi import status

        raise AppError("invite_not_found_or_expired", status.HTTP_404_NOT_FOUND)
    return invite


@router.get("/recruitment/invite/{token}/canvas")
@recruitment_public_limiter.limit("60/minute")
async def get_invite_canvas(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public canvas for an invited evaluator — scoped to the invite's CV."""
    return await service.get_invite_canvas(db, token)


@router.get("/recruitment/invite/{token}/context")
@recruitment_public_limiter.limit("60/minute")
async def get_invite_context(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public bundle for the invited-evaluator page (resume + questions + vacancy)."""
    return await service.get_invite_context(db, token)


@router.post("/recruitment/invite/{token}/assessments")
@recruitment_public_limiter.limit("20/minute")
async def record_invite_assessment(
    request: Request,
    token: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """Public mutation: record an evaluator score via invite token."""
    return await service.record_invite_assessment(db, token, payload)


# ── Canvas API ────────────────────────────────────────────────────


@router.get("/recruitment/vacancies/{vacancy_id}/canvas")
async def get_canvas(
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_canvas(db, current_user.tenant_id, vacancy_id)


# ── Assessment matrix (HRP-265 — Compact matrix aggregates) ──────


@router.get("/recruitment/vacancies/{vacancy_id}/assessment-matrix")
async def get_assessment_matrix(
    vacancy_id: uuid.UUID,
    round: str = Query(
        default="latest",
        description="AI round scope: 'latest', 'all', or a 1-based round number.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role("admin", "recruiter", "hrd", "hr", "hiring_manager")
    ),
):
    """Aggregated matrix for the Assessments tab and the % match column.

    Restricted to recruitment roles so candidate / invited-evaluator
    tokens cannot read the full vacancy roster's AI scores and divergence
    flags. HM scoping at the per-row level is a separate ticket — for now
    every recruitment role inside the tenant sees the full matrix, same as
    the existing ``/canvas`` endpoint.

    ``round`` (HRP-510) scopes the AI side to an interview round; manager
    scores have no round dimension and are unaffected.
    """
    return await service.get_assessment_matrix(
        db, current_user.tenant_id, vacancy_id, round_filter=round
    )


@router.get("/recruitment/vacancies/{vacancy_id}/assessment-matrix/export.xlsx")
async def export_assessment_matrix_xlsx(
    vacancy_id: uuid.UUID,
    round: str = Query(default="latest"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role("admin", "recruiter", "hrd", "hr", "hiring_manager")
    ),
):
    """HRP-510 — the fullscreen canvas' XLSX export.

    Same data and the same role gate as the matrix endpoint; rendered
    server-side because openpyxl already lives here and the browser has
    no zip writer.
    """
    payload = await service.get_assessment_matrix(
        db, current_user.tenant_id, vacancy_id, round_filter=round
    )
    vacancy = await service.get_vacancy(db, current_user.tenant_id, vacancy_id)
    title = getattr(vacancy, "title", None) or "Vacancy"
    from app.modules.recruitment.report_xlsx import render_canvas_xlsx

    content = render_canvas_xlsx(payload, vacancy_title=title)
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (f'attachment; filename="canvas-{vacancy_id}.xlsx"')
        },
    )


@router.get(
    "/recruitment/vacancies/{vacancy_id}/assessment-matrix"
    "/cells/{candidate_vacancy_id}/{competence_id}"
)
async def get_assessment_matrix_cell_detail(
    vacancy_id: uuid.UUID,
    candidate_vacancy_id: uuid.UUID,
    competence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role("admin", "recruiter", "hrd", "hr", "hiring_manager")
    ),
):
    """Footer-info drill-down for a single Compact matrix cell."""
    return await service.get_assessment_matrix_cell_detail(
        db,
        current_user.tenant_id,
        vacancy_id,
        candidate_vacancy_id,
        competence_id,
    )


# ── HRP-205: Question sets (new) ──────────────────────────────────


@router.get(
    "/v1/candidates/{candidate_id}/question-sets",
    response_model=list[QuestionSetRead],
)
async def list_candidate_question_sets(
    candidate_id: uuid.UUID,
    vacancy_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await question_service.list_question_sets(
        db, current_user.tenant_id, candidate_id, vacancy_id=vacancy_id
    )


@router.get(
    # The aggregator router carries no prefix — every sibling spells out
    # ``/recruitment`` itself. Dropping it here published the route at
    # /api/vacancies/... while the frontend called /api/recruitment/...
    "/recruitment/vacancies/{vacancy_id}/question-sets",
    response_model=VacancyQuestionsRead,
)
async def list_vacancy_question_sets(
    vacancy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    # Same gate as the enriched candidates listing: this payload is the
    # vacancy's whole roster (names + the questions prepared for them),
    # so it must not be enumerable by any authenticated employee.
    current_user: User = Depends(
        require_role("admin", "recruiter", "hrd", "hr", "hiring_manager")
    ),
):
    """HRP-504: every candidate's latest question set for this vacancy,
    plus the vacancy competences, for the Questions tab filters."""
    return await question_service.list_vacancy_question_sets(
        db, current_user.tenant_id, vacancy_id
    )


@router.get(
    "/v1/question-sets/sample",
    response_model=QuestionSetRead,
)
async def get_question_set_sample(
    current_user: User = Depends(get_current_user),
):
    """Static preview shown when credits < generation threshold.

    Free for the tenant (no credits charged) — wired into
    ``BILLING_EXEMPT`` so the wrapper is a no-op. Auth still required so
    we don't leak the sample to unauthenticated traffic.
    """
    return question_service.get_sample_question_set()


@router.post(
    "/v1/candidate-vacancies/{cv_id}/question-sets",
    response_model=QuestionSetRead,
    status_code=201,
)
async def generate_question_set(
    cv_id: uuid.UUID,
    data: GenerateQuestionSetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hiring_manager")),
):
    """Generate, regenerate or evolve a question set (8 credits)."""
    return await question_service.generate_question_set(
        db,
        current_user.tenant_id,
        cv_id,
        data,
        current_user_id=current_user.id,
    )


@router.post(
    "/v1/question-sets/{set_id}/questions",
    response_model=QuestionRead2,
    status_code=201,
)
async def add_question_to_set(
    set_id: uuid.UUID,
    data: QuestionCreate2,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hiring_manager")),
):
    return await question_service.add_question_to_set(
        db,
        current_user.tenant_id,
        set_id,
        data,
        current_user_id=current_user.id,
    )


@router.patch(
    "/v1/questions/{question_id}",
    response_model=QuestionRead2,
)
async def patch_question(
    question_id: uuid.UUID,
    data: QuestionUpdate2,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hiring_manager")),
):
    return await question_service.update_question_v2(
        db,
        current_user.tenant_id,
        question_id,
        data,
        current_user_id=current_user.id,
    )


@router.delete("/v1/questions/{question_id}", status_code=204)
async def delete_question_v2(
    question_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hiring_manager")),
):
    await question_service.soft_delete_question(db, current_user.tenant_id, question_id)


@router.post(
    "/v1/question-sets/{set_id}/export-pdf",
)
async def export_question_set_pdf(
    set_id: uuid.UUID,
    data: QuestionSetExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "recruiter", "hiring_manager")),
):
    pdf_bytes = await question_service.export_question_set_pdf(
        db,
        current_user.tenant_id,
        set_id,
        fmt=data.format,
        include_indicators=data.include_indicators,
        include_follow_ups=data.include_follow_ups,
        include_rationale=data.include_rationale,
        include_resume_anchor=data.include_resume_anchor,
        sort=data.sort,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (f'attachment; filename="question-set-{set_id}.pdf"')
        },
    )
