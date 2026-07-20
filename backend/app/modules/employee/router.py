import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.employee import service
from app.modules.employee.schemas import (
    AvailableUser,
    CompensationCreate,
    CompensationRead,
    CompensationUpdate,
    CourseCreate,
    CourseRead,
    CourseUpdate,
    EducationCreate,
    EducationRead,
    EducationUpdate,
    EmployeeCompetenceOverview,
    EmployeeCreate,
    EmployeeEventCreate,
    EmployeeEventRead,
    EmployeeList,
    EmployeeRead,
    EmployeeUpdate,
    PreviousEmploymentCreate,
    PreviousEmploymentRead,
    PreviousEmploymentUpdate,
    WorkExperienceCreate,
    WorkExperienceRead,
    WorkExperienceUpdate,
)

router = APIRouter(tags=["employees"])


@router.post("/employees", response_model=EmployeeRead, status_code=201)
async def create_employee(
    data: EmployeeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_employee(db, current_user.tenant_id, data)


@router.get("/employees", response_model=EmployeeList)
async def list_employees(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    q: str | None = Query(default=None, max_length=255),
    division_id: list[uuid.UUID] | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    specialization_id: list[uuid.UUID] | None = Query(default=None),
    position_id: list[uuid.UUID] | None = Query(default=None),
    grade_id: list[uuid.UUID] | None = Query(default=None),
    unassigned_only: bool = Query(default=False),
    with_alerts: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.access_scope import get_visible_employee_ids

    visible_ids = await get_visible_employee_ids(db, current_user)
    items, total = await service.list_employees(
        db,
        current_user.tenant_id,
        skip,
        limit,
        division_id,
        status,
        visible_employee_ids=visible_ids,
        specialization_id=specialization_id,
        position_id=position_id,
        grade_id=grade_id,
        unassigned_only=unassigned_only,
        with_alerts=with_alerts,
        q=q,
    )
    return {"items": items, "total": total}


@router.get("/employees/available-users", response_model=list[AvailableUser])
async def list_available_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.list_available_users(db, current_user.tenant_id)


@router.get("/employees/{employee_id}", response_model=EmployeeRead)
async def get_employee(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_employee(db, current_user.tenant_id, employee_id)


@router.put("/employees/{employee_id}", response_model=EmployeeRead)
async def update_employee(
    employee_id: uuid.UUID,
    data: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_employee(
        db, current_user.tenant_id, employee_id, data, current_user
    )


@router.delete("/employees/{employee_id}", response_model=EmployeeRead)
async def delete_employee(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.delete_employee(
        db, current_user.tenant_id, employee_id, current_user
    )


@router.post("/employees/{employee_id}/downgrade-role")
async def downgrade_role(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "hr", "platform_admin")),
):
    return await service.downgrade_employee_role(
        db, current_user.tenant_id, employee_id
    )


# --- Events ---


@router.get("/employees/{employee_id}/events", response_model=list[EmployeeEventRead])
async def list_events(
    employee_id: uuid.UUID,
    type: str | None = Query(default=None, alias="type"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_events(db, current_user.tenant_id, employee_id, type)


@router.post(
    "/employees/{employee_id}/events",
    response_model=EmployeeEventRead,
    status_code=201,
)
async def create_event(
    employee_id: uuid.UUID,
    data: EmployeeEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_event(
        db, current_user.tenant_id, employee_id, data, current_user
    )


# ---------------------------------------------------------------------------
# HRP-153: Competence overview
# ---------------------------------------------------------------------------


@router.get(
    "/employees/{employee_id}/competences",
    response_model=EmployeeCompetenceOverview,
)
async def get_employee_competences(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_competence_overview(
        db, current_user.tenant_id, employee_id
    )


# Kept for backward compatibility -- the original spec used
# `/competence-overview`; HRP-153 REDO renamed it to the shorter
# `/competences`. Drop the alias once the frontend has shipped on the
# new path for a few releases.
@router.get(
    "/employees/{employee_id}/competence-overview",
    response_model=EmployeeCompetenceOverview,
    include_in_schema=False,
)
async def get_competence_overview(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_competence_overview(
        db, current_user.tenant_id, employee_id
    )


# ---------------------------------------------------------------------------
# GF1: Work Experience
# ---------------------------------------------------------------------------


@router.get(
    "/employees/{employee_id}/work-experience",
    response_model=list[WorkExperienceRead],
)
async def list_work_experiences(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_work_experiences(db, current_user.tenant_id, employee_id)


@router.post(
    "/employees/{employee_id}/work-experience",
    response_model=WorkExperienceRead,
    status_code=201,
)
async def create_work_experience(
    employee_id: uuid.UUID,
    data: WorkExperienceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_work_experience(
        db, current_user.tenant_id, employee_id, data, current_user
    )


@router.put(
    "/employees/{employee_id}/work-experience/{item_id}",
    response_model=WorkExperienceRead,
)
async def update_work_experience(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    data: WorkExperienceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_work_experience(
        db, current_user.tenant_id, item_id, data, current_user
    )


@router.delete(
    "/employees/{employee_id}/work-experience/{item_id}",
    response_model=WorkExperienceRead,
)
async def delete_work_experience(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.delete_work_experience(
        db, current_user.tenant_id, item_id, current_user
    )


# ---------------------------------------------------------------------------
# GF1: Previous Employment
# ---------------------------------------------------------------------------


@router.get(
    "/employees/{employee_id}/previous-employment",
    response_model=list[PreviousEmploymentRead],
)
async def list_previous_employments(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_previous_employments(
        db, current_user.tenant_id, employee_id
    )


@router.post(
    "/employees/{employee_id}/previous-employment",
    response_model=PreviousEmploymentRead,
    status_code=201,
)
async def create_previous_employment(
    employee_id: uuid.UUID,
    data: PreviousEmploymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_previous_employment(
        db, current_user.tenant_id, employee_id, data, current_user
    )


@router.put(
    "/employees/{employee_id}/previous-employment/{item_id}",
    response_model=PreviousEmploymentRead,
)
async def update_previous_employment(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    data: PreviousEmploymentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_previous_employment(
        db, current_user.tenant_id, item_id, data, current_user
    )


@router.delete(
    "/employees/{employee_id}/previous-employment/{item_id}",
    response_model=PreviousEmploymentRead,
)
async def delete_previous_employment(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.delete_previous_employment(
        db, current_user.tenant_id, item_id, current_user
    )


# ---------------------------------------------------------------------------
# GF2: Education
# ---------------------------------------------------------------------------


@router.get(
    "/employees/{employee_id}/education",
    response_model=list[EducationRead],
)
async def list_education(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_education(db, current_user.tenant_id, employee_id)


@router.post(
    "/employees/{employee_id}/education",
    response_model=EducationRead,
    status_code=201,
)
async def create_education(
    employee_id: uuid.UUID,
    data: EducationCreate,
    db: AsyncSession = Depends(get_db),
    # HRP-66: Education is the one section a regular employee may
    # self-manage on their own profile; the service layer enforces
    # ownership, so the router only authenticates here.
    current_user: User = Depends(get_current_user),
):
    return await service.create_education(
        db, current_user.tenant_id, employee_id, data, current_user
    )


@router.put(
    "/employees/{employee_id}/education/{item_id}",
    response_model=EducationRead,
)
async def update_education(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    data: EducationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.update_education(
        db, current_user.tenant_id, item_id, data, current_user
    )


@router.delete(
    "/employees/{employee_id}/education/{item_id}",
    response_model=EducationRead,
)
async def delete_education(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.delete_education(
        db, current_user.tenant_id, item_id, current_user
    )


# ---------------------------------------------------------------------------
# GF2: Courses & Certifications
# ---------------------------------------------------------------------------


@router.get(
    "/employees/{employee_id}/courses",
    response_model=list[CourseRead],
)
async def list_courses(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_courses(db, current_user.tenant_id, employee_id)


@router.post(
    "/employees/{employee_id}/courses",
    response_model=CourseRead,
    status_code=201,
)
async def create_course(
    employee_id: uuid.UUID,
    data: CourseCreate,
    db: AsyncSession = Depends(get_db),
    # HRP-66: Courses sit under the Education tab — same self-service
    # carve-out as Education itself.
    current_user: User = Depends(get_current_user),
):
    return await service.create_course(
        db, current_user.tenant_id, employee_id, data, current_user
    )


@router.put(
    "/employees/{employee_id}/courses/{item_id}",
    response_model=CourseRead,
)
async def update_course(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    data: CourseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.update_course(
        db, current_user.tenant_id, item_id, data, current_user
    )


@router.delete(
    "/employees/{employee_id}/courses/{item_id}",
    response_model=CourseRead,
)
async def delete_course(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.delete_course(
        db, current_user.tenant_id, item_id, current_user
    )


# ---------------------------------------------------------------------------
# GF5: Compensation (admin only)
# ---------------------------------------------------------------------------


# HRP-221 (REDO): division managers see and edit Compensation on the
# same employees they can edit elsewhere (own + child-division
# subtree). The service layer still calls ``assert_employee_write_scope``
# to enforce the scope; the router guard just opens the door to the
# manager role.
@router.get(
    "/employees/{employee_id}/compensation",
    response_model=list[CompensationRead],
)
async def list_compensations(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.list_compensations(
        db, current_user.tenant_id, employee_id, current_user
    )


@router.post(
    "/employees/{employee_id}/compensation",
    response_model=CompensationRead,
    status_code=201,
)
async def create_compensation(
    employee_id: uuid.UUID,
    data: CompensationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_compensation(
        db, current_user.tenant_id, employee_id, data, current_user
    )


@router.put(
    "/employees/{employee_id}/compensation/{item_id}",
    response_model=CompensationRead,
)
async def update_compensation(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    data: CompensationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_compensation(
        db, current_user.tenant_id, item_id, data, current_user
    )


@router.delete(
    "/employees/{employee_id}/compensation/{item_id}",
    response_model=CompensationRead,
)
async def delete_compensation(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.delete_compensation(
        db, current_user.tenant_id, item_id, current_user
    )
