import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import (
    assert_employee_read_scope,
    get_current_employee,
    is_employee_in_read_scope,
    is_employee_only,
)
from app.core.errors import AppError
from app.database import get_db
from app.modules.auth.dependencies import (
    get_current_user,
    require_admin,
    require_role,
)
from app.modules.auth.models import User
from app.modules.employee import service
from app.modules.employee.issues import IssueCode
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
    EmployeeDirectoryList,
    EmployeeDirectoryRead,
    EmployeeEventCreate,
    EmployeeEventRead,
    EmployeeList,
    EmployeeRead,
    EmployeeRoleUpdate,
    EmployeeUpdate,
    PreviousEmploymentCreate,
    PreviousEmploymentRead,
    PreviousEmploymentUpdate,
    WorkExperienceCreate,
    WorkExperienceRead,
    WorkExperienceUpdate,
)

router = APIRouter(tags=["employees"])


async def read_scope_user(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """``get_current_user`` plus "may you read this card at all" (HRP-616).

    Reads under ``/employees/{employee_id}`` used to be gated by bare
    authentication, so any colleague could pull a full card — competences,
    events, education, employment history — by guessing nothing more than
    the URL.
    """
    await assert_employee_read_scope(db, current_user, employee_id)
    return current_user


@router.post("/employees", response_model=EmployeeRead, status_code=201)
async def create_employee(
    data: EmployeeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_employee(db, current_user.tenant_id, data)


@router.get("/employees", response_model=EmployeeList | EmployeeDirectoryList)
async def list_employees(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    q: str | None = Query(default=None, max_length=255),
    division_id: list[uuid.UUID] | None = Query(default=None),
    # HRP-58: widen `division_id` to the division subtree (nested
    # departments included). Off by default — existing callers keep the
    # exact-division semantics they were written against.
    include_sub_divisions: bool = Query(default=False),
    status: list[str] | None = Query(default=None),
    specialization_id: list[uuid.UUID] | None = Query(default=None),
    position_id: list[uuid.UUID] | None = Query(default=None),
    grade_id: list[uuid.UUID] | None = Query(default=None),
    # HRP-621: filter by the role code(s) of the underlying user.
    role: list[str] | None = Query(default=None),
    unassigned_only: bool = Query(default=False),
    with_alerts: bool = Query(default=False),
    # HRP-638: the dashboard links here with the cohort it just counted.
    issue: list[IssueCode] | None = Query(default=None),
    # HRP-729: severity ordering. Default when ``issue`` is set, so the list a
    # dashboard chip opens leads with the same person the chip named.
    sort: Literal["severity", "created"] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.access_scope import get_visible_employee_ids

    # HRP-623: rank-and-file get the whole company in the directory schema —
    # the point of a directory is finding a colleague, so the read scope that
    # HRP-616 put on the card does not apply to the list. Admin / HR /
    # manager keep the full rows their own scope allows.
    directory = is_employee_only(current_user)
    visible_ids = (
        None if directory else await get_visible_employee_ids(db, current_user)
    )
    if directory:
        # Trimming the columns is not enough: a predicate on a field the
        # directory hides answers the same question the field would.
        # ``?status=terminated`` or ``?role=admin`` over the whole tenant
        # hands back exactly the roster the schema is meant to withhold,
        # and ``?grade_id=`` walks around ``directory_show_grades``. Only
        # the filters over fields the directory actually shows survive.
        status = None
        role = None
        specialization_id = None
        grade_id = None
        unassigned_only = False
        with_alerts = False
        # Development-loop problems are HR data about a colleague, and the
        # filter answers the same question the badge would.
        issue = None
        sort = None
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
        role=role,
        unassigned_only=unassigned_only,
        with_alerts=with_alerts,
        q=q,
        include_sub_divisions=include_sub_divisions,
        issue=issue,
        sort=sort,
    )
    if directory:
        items = await service.directory_rows(db, current_user.tenant_id, items)
    return {"items": items, "total": total}


@router.get("/employees/available-users", response_model=list[AvailableUser])
async def list_available_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.list_available_users(db, current_user.tenant_id)


# Registered before ``/employees/{employee_id}``: the other order makes
# FastAPI try to parse "me" as a UUID and answer 422.
@router.get("/employees/me", response_model=EmployeeRead)
async def get_own_employee(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HRP-624: own card without the UI having to learn its employee id.

    A workspace owner who was never given an ``Employee`` row is an ordinary
    case, not a crash: the 404 carries ``employee_profile_not_found`` so the
    UI can say so instead of rendering a broken card.
    """
    emp = await get_current_employee(db, current_user)
    if emp is None:
        raise AppError("employee_profile_not_found", 404)
    # HRP-660: the only caller resolves the id and redirects to
    # ``/employees/{id}``, which computes the issues itself. Scanning the
    # alerts here just to throw the result away costs a query per click.
    return await service.get_employee(
        db, current_user.tenant_id, emp.id, with_issues=False
    )


@router.get(
    "/employees/{employee_id}", response_model=EmployeeRead | EmployeeDirectoryRead
)
async def get_employee(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HRP-623: the card itself is open to the whole tenant, the schema is not.

    Callers inside the HRP-616 read scope (own card, admin / HR, a manager's
    subtree) keep the full record; everyone else gets the directory row.
    Sub-resources stay behind ``read_scope_user``.
    """
    # HRP-660: the card names the employee's problems, so the scope check
    # runs first — the directory row hides them anyway, and computing them
    # for a caller who will not see them is pure waste.
    in_scope = await is_employee_in_read_scope(db, current_user, employee_id)
    row = await service.get_employee(
        db, current_user.tenant_id, employee_id, with_issues=in_scope
    )
    if in_scope:
        return row
    return (await service.directory_rows(db, current_user.tenant_id, [row]))[0]


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


@router.put("/employees/{employee_id}/role")
async def set_role(
    employee_id: uuid.UUID,
    data: EmployeeRoleUpdate,
    db: AsyncSession = Depends(get_db),
    # ``require_admin`` rather than ``require_role("admin", ...)``: granting
    # roles is the one surface where the enterprise platform role must come
    # along, and it resolves that through the rbac_hooks seam.
    current_user: User = Depends(require_admin()),
):
    return await service.set_employee_role(
        db, current_user.tenant_id, employee_id, data.role_code, current_user
    )


# --- Events ---


@router.get("/employees/{employee_id}/events", response_model=list[EmployeeEventRead])
async def list_events(
    employee_id: uuid.UUID,
    type: str | None = Query(default=None, alias="type"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(read_scope_user),
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
    current_user: User = Depends(read_scope_user),
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
    current_user: User = Depends(read_scope_user),
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
    current_user: User = Depends(read_scope_user),
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
    current_user: User = Depends(read_scope_user),
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
    current_user: User = Depends(read_scope_user),
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
    current_user: User = Depends(read_scope_user),
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
