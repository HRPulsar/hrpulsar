import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.talent_market import service
from app.modules.talent_market.schemas import (
    CandidateAdd,
    CandidateBreakdown,
    CandidateBulkAdd,
    CandidatePoolList,
    CandidateRead,
    CompetenceLink,
    RequiredCompetenceBulkCreate,
    RequiredCompetenceUpdate,
    RequiredSpecializationCreate,
    RequiredSpecializationUpdate,
    RequirementCreate,
    RequirementRead,
    SearchRequest,
    SpecializationLink,
    TalentCardCreate,
    TalentCardDetail,
    TalentCardRead,
    TalentCardUpdate,
)

router = APIRouter(tags=["talent-market"])


@router.post("/talent-market", response_model=TalentCardRead, status_code=201)
async def create_card(
    data: TalentCardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_card(db, current_user.tenant_id, current_user.id, data)


@router.post("/talent-market/search")
async def search_cards(
    data: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.access_scope import (
        ADMIN_ROLE_CODES,
        get_current_employee,
        get_managed_division_ids,
        is_employee_only,
    )

    is_admin = any(r.code in ADMIN_ROLE_CODES for r in current_user.roles)
    published_only = False
    assignee_employee_id: uuid.UUID | None = None
    # HRP-209: employees see only cards they're a candidate on (and the
    # backend filters Draft to appointed-only inside the service). For
    # managers / admins the original "published + your division" scope
    # still applies.
    candidate_only = False
    # HRP-213: every viewer that carries an Employee row gets per-card
    # `reacted_by_me` so the Reacted chip can render on previews even
    # for admins (admins are sometimes employees too).
    viewer_emp = await get_current_employee(db, current_user)
    viewer_employee_id = viewer_emp.id if viewer_emp is not None else None
    if not is_admin:
        managed = (
            await get_managed_division_ids(
                db, current_user.tenant_id, viewer_emp.id
            )
            if viewer_emp
            else []
        )
        published_only = not managed
        if published_only and viewer_emp is not None:
            assignee_employee_id = viewer_emp.id
            if is_employee_only(current_user):
                candidate_only = True
    items, total = await service.search_cards(
        db,
        current_user.tenant_id,
        data,
        published_only=published_only,
        assignee_employee_id=assignee_employee_id,
        candidate_only=candidate_only,
        viewer_employee_id=viewer_employee_id,
    )
    return {"items": items, "total": total}


@router.get("/talent-market/{card_id}", response_model=TalentCardDetail)
async def get_card(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # HRP-149: pass `current_user` so the service can stamp `can_view_profile`
    # on each candidate per viewer role / division scope.
    return await service.get_card_detail(
        db, current_user.tenant_id, card_id, current_user=current_user
    )


@router.put("/talent-market/{card_id}", response_model=TalentCardRead)
async def update_card(
    card_id: uuid.UUID,
    data: TalentCardUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_card(db, current_user.tenant_id, card_id, data)


@router.delete("/talent-market/{card_id}", status_code=204)
async def delete_card(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_card(db, current_user.tenant_id, card_id)


@router.post("/talent-market/{card_id}/publish", response_model=TalentCardRead)
async def publish_card(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.publish_card(db, current_user.tenant_id, card_id)


@router.post("/talent-market/{card_id}/complete", response_model=TalentCardRead)
async def complete_card(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """HRP-150: terminal transition Published → Completed."""
    return await service.complete_card(db, current_user.tenant_id, card_id)


@router.post("/talent-market/{card_id}/cancel", response_model=TalentCardRead)
async def cancel_card(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """HRP-150: terminal transition Draft|Published → Cancelled."""
    return await service.cancel_card(db, current_user.tenant_id, card_id)


@router.post(
    "/talent-market/{card_id}/requirements",
    response_model=RequirementRead,
    status_code=201,
)
async def add_requirement(
    card_id: uuid.UUID,
    data: RequirementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.add_requirement(db, current_user.tenant_id, card_id, data)


# ----------------- HRP-87: Required Specialization block --------------------


@router.post(
    "/talent-market/{card_id}/required-specializations",
    response_model=SpecializationLink,
    status_code=201,
)
async def add_required_specialization(
    card_id: uuid.UUID,
    data: RequiredSpecializationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.add_required_specialization(
        db, current_user.tenant_id, card_id, data
    )


@router.put(
    "/talent-market/{card_id}/required-specializations/{link_id}",
    response_model=SpecializationLink,
)
async def update_required_specialization(
    card_id: uuid.UUID,
    link_id: uuid.UUID,
    data: RequiredSpecializationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_required_specialization(
        db, current_user.tenant_id, card_id, link_id, data
    )


@router.delete(
    "/talent-market/{card_id}/required-specializations/{link_id}",
    status_code=204,
)
async def delete_required_specialization(
    card_id: uuid.UUID,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    await service.delete_required_specialization(
        db, current_user.tenant_id, card_id, link_id
    )


# ----------------- HRP-87: Required Competence block ------------------------


@router.post(
    "/talent-market/{card_id}/required-competences",
    response_model=list[CompetenceLink],
    status_code=201,
)
async def add_required_competences(
    card_id: uuid.UUID,
    data: RequiredCompetenceBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.add_required_competences(
        db, current_user.tenant_id, card_id, data
    )


@router.put(
    "/talent-market/{card_id}/required-competences/{link_id}",
    response_model=CompetenceLink,
)
async def update_required_competence(
    card_id: uuid.UUID,
    link_id: uuid.UUID,
    data: RequiredCompetenceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_required_competence(
        db, current_user.tenant_id, card_id, link_id, data
    )


@router.delete(
    "/talent-market/{card_id}/required-competences/{link_id}",
    status_code=204,
)
async def delete_required_competence(
    card_id: uuid.UUID,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    await service.delete_required_competence(
        db, current_user.tenant_id, card_id, link_id
    )


@router.get(
    "/talent-market/{card_id}/candidate-pool",
    response_model=CandidatePoolList,
)
async def list_candidate_pool(
    card_id: uuid.UUID,
    include_attached: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """HRP-95: feed the Add/Change candidate picker dialog.

    `include_attached=true` keeps already-linked candidates in the result
    so the Change dialog can pre-check them; Add mode (default) keeps the
    legacy "show only un-attached" behaviour.
    """
    items = await service.list_candidate_pool(
        db, current_user.tenant_id, card_id, include_attached=include_attached
    )
    return {"items": items}


@router.get(
    "/talent-market/{card_id}/candidates/{employee_id}/breakdown",
    response_model=CandidateBreakdown,
)
async def get_candidate_breakdown(
    card_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HRP-172: per-competence + per-spec match breakdown for the Sheet
    drawer rendered from the Match cell in the Candidates list and the
    Add / Change picker dialogs.

    HRP-209: Employees can only open the drawer on their own row;
    other employees' breakdowns return 403."""
    from fastapi import HTTPException
    from fastapi import status as _status

    from app.core.access_scope import (
        get_current_employee,
        is_employee_only,
    )

    if is_employee_only(current_user):
        emp = await get_current_employee(db, current_user)
        if emp is None or emp.id != employee_id:
            raise HTTPException(
                _status.HTTP_403_FORBIDDEN, "Insufficient permissions"
            )
    return await service.get_candidate_breakdown(
        db, current_user.tenant_id, card_id, employee_id
    )


@router.post(
    "/talent-market/{card_id}/candidates", response_model=CandidateRead, status_code=201
)
async def add_candidate(
    card_id: uuid.UUID,
    data: CandidateAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.add_candidate(db, current_user.tenant_id, card_id, data)


@router.post(
    "/talent-market/{card_id}/candidates/bulk",
    response_model=list[CandidateRead],
    status_code=201,
)
async def add_candidates_bulk(
    card_id: uuid.UUID,
    data: CandidateBulkAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """HRP-95: attach a batch of employees from the picker dialog in one call."""
    return await service.add_candidates_bulk(db, current_user.tenant_id, card_id, data)


@router.post(
    "/talent-market/{card_id}/candidates/{candidate_id}/appoint",
    response_model=CandidateRead,
)
async def appoint_candidate(
    card_id: uuid.UUID,
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.appoint_candidate(
        db, current_user.tenant_id, card_id, candidate_id
    )


@router.delete(
    "/talent-market/{card_id}/candidates/{employee_id}",
    status_code=204,
)
async def delete_candidate(
    card_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """HRP-95: remove a TalentCandidate row from the card. Called by the
    Change-candidates picker for each employee unchecked on Save."""
    await service.delete_candidate(db, current_user.tenant_id, card_id, employee_id)


@router.post(
    "/talent-market/{card_id}/recompute", response_model=TalentCardRead
)
async def recompute_card(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """HRP-242: rerun the Candidates auto-pool for the card.

    Backs the refresh icon next to the "last match" label in the
    Candidates block header. The service stamps ``last_matched_at`` so
    the UI immediately picks up "today" for the new render.
    """
    return await service.recompute_card_candidates(
        db, current_user.tenant_id, card_id
    )


@router.post(
    "/talent-market/{card_id}/react",
    response_model=CandidateRead,
)
async def react_to_card(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HRP-213: an employee on a Published card sends a reaction.

    Auth is intentionally `get_current_user` rather than role-gated —
    the service rejects callers without a TalentCandidate row, callers
    already in the ``appointed`` bucket, and callers that have already
    reacted. The candidate id is derived from the viewer's Employee
    profile (no per-card-candidate id in the URL).
    """
    return await service.react_to_card(
        db, current_user.tenant_id, card_id, current_user
    )
