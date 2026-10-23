"""Exams REST.

Two readers share one menu entry. The section access matrix (HRP-823)
answers for the first: ``manage`` on ``exams`` runs the mass exams -
questions, pass marks, assignments, everyone's results. The second is the
employee taking an exam assigned to them; their routes (``/exams...``)
answer to their own employee row and stay outside the matrix
(``core/sections.PERSONAL_PATHS``), so a closed section never strands an
assignment the e-mail already linked to.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, UploadFile
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import (
    assert_authored,
    authored_only,
    get_current_employee,
    get_visible_employee_ids,
)
from app.core.errors import AppError
from app.core.sections import matrix_levels, require_section
from app.core.upload_validation import assert_declared_size_within_limit
from app.database import get_db
from app.modules.assessment.schemas import StatusChange
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.exam import service
from app.modules.exam.models import MassExam
from app.modules.exam.schemas import (
    ExamAnswerSubmit,
    ExamRead,
    ExamResultRead,
    ExamReviewRead,
    ExamTakeRead,
    MassExamCreate,
    MassExamDetail,
    MassExamRead,
    MassExamResultRead,
    MassExamUpdate,
    PassMarkCreate,
    PassMarkRead,
    PassMarkUpdate,
    QuestionCreate,
    QuestionRead,
    QuestionUpdate,
)

router = APIRouter(tags=["exams"])

# HRP-823: running the exams section is ``manage`` on the tenant's section
# access matrix - writing a mass exam and reading one alike, because a mass
# exam carries everyone's results and the section's ``view`` belongs to the
# other reader here, the employee taking their own exam (``/exams`` below,
# outside the matrix). A mass exam has no owning division to narrow reads
# by; the per-employee results it lists are narrowed by the read scope.
# The section gate answers for the writes (HRP-1018); the reads ask here.
_manage = require_section("exams", "manage")


async def mass_exam_scope(
    mass_exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """HRP-640: below the admin level a mass exam is its author's alone -
    to open, change, assign and read the results of (Vladimir, 29.09)."""
    await assert_authored(
        db,
        current_user,
        MassExam.initiator_id,
        (MassExam.id == mass_exam_id) & (MassExam.tenant_id == current_user.tenant_id),
    )


# --- Mass Exam ---


@router.post("/mass-exams", response_model=MassExamRead, status_code=201)
async def create_mass_exam(
    data: MassExamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.create_mass_exam(
        db, current_user.tenant_id, current_user.id, data
    )


@router.get("/mass-exams", response_model=list[MassExamRead])
async def list_mass_exams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    # HRP-640: below the admin level one's own mass exams only.
    return await service.list_mass_exams(
        db, current_user.tenant_id, initiator_id=authored_only(current_user)
    )


# Declared before ``/mass-exams/{mass_exam_id}``, which would take it as an id.
@router.get("/mass-exams/import-template")
async def download_import_template(
    current_user: User = Depends(_manage),
):
    content = service.generate_import_template()
    from io import BytesIO

    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=question_import_template.xlsx"
        },
    )


@router.get("/mass-exams/{mass_exam_id}", response_model=MassExamDetail)
async def get_mass_exam(
    mass_exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
    _scope: None = Depends(mass_exam_scope),
):
    return await service.get_mass_exam_detail(db, current_user.tenant_id, mass_exam_id)


@router.patch("/mass-exams/{mass_exam_id}", response_model=MassExamRead)
async def update_mass_exam(
    mass_exam_id: uuid.UUID,
    data: MassExamUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(mass_exam_scope),
):
    return await service.update_mass_exam(
        db, current_user.tenant_id, mass_exam_id, data
    )


@router.post("/mass-exams/{mass_exam_id}/status", response_model=MassExamRead)
async def change_status(
    mass_exam_id: uuid.UUID,
    data: StatusChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(mass_exam_scope),
):
    return await service.change_mass_exam_status(
        db, current_user.tenant_id, mass_exam_id, data.status_code
    )


# --- Questions ---


@router.post(
    "/mass-exams/{mass_exam_id}/questions", response_model=QuestionRead, status_code=201
)
async def add_question(
    mass_exam_id: uuid.UUID,
    data: QuestionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(mass_exam_scope),
):
    return await service.add_question(db, current_user.tenant_id, mass_exam_id, data)


@router.patch(
    "/mass-exams/{mass_exam_id}/questions/{question_id}",
    response_model=QuestionRead,
)
async def update_question(
    mass_exam_id: uuid.UUID,
    question_id: uuid.UUID,
    data: QuestionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(mass_exam_scope),
):
    return await service.update_question(
        db, current_user.tenant_id, mass_exam_id, question_id, data
    )


@router.delete(
    "/mass-exams/{mass_exam_id}/questions/{question_id}",
    status_code=204,
)
async def delete_question(
    mass_exam_id: uuid.UUID,
    question_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(mass_exam_scope),
):
    await service.delete_question(
        db, current_user.tenant_id, mass_exam_id, question_id
    )
    return None


# --- GF9: Import Questions from Excel ---


@router.post(
    "/mass-exams/{mass_exam_id}/import-questions",
    dependencies=[Depends(assert_declared_size_within_limit)],
)
async def import_questions(
    mass_exam_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(mass_exam_scope),
):
    data = await file.read()
    return await service.import_questions_from_excel(
        db, current_user.tenant_id, mass_exam_id, data
    )


# --- Pass Marks ---


@router.post(
    "/mass-exams/{mass_exam_id}/pass-marks",
    response_model=PassMarkRead,
    status_code=201,
)
async def add_pass_mark(
    mass_exam_id: uuid.UUID,
    data: PassMarkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(mass_exam_scope),
):
    return await service.add_pass_mark(db, current_user.tenant_id, mass_exam_id, data)


@router.patch(
    "/mass-exams/{mass_exam_id}/pass-marks/{pass_mark_id}",
    response_model=PassMarkRead,
)
async def update_pass_mark(
    mass_exam_id: uuid.UUID,
    pass_mark_id: uuid.UUID,
    data: PassMarkUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(mass_exam_scope),
):
    return await service.update_pass_mark(
        db, current_user.tenant_id, mass_exam_id, pass_mark_id, data
    )


@router.delete(
    "/mass-exams/{mass_exam_id}/pass-marks/{pass_mark_id}",
    status_code=204,
)
async def delete_pass_mark(
    mass_exam_id: uuid.UUID,
    pass_mark_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(mass_exam_scope),
):
    await service.delete_pass_mark(
        db, current_user.tenant_id, mass_exam_id, pass_mark_id
    )
    return None


# --- Results ---


@router.get(
    "/mass-exams/{mass_exam_id}/results", response_model=list[MassExamResultRead]
)
async def get_mass_exam_results(
    mass_exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
    _scope: None = Depends(mass_exam_scope),
):
    visible_ids = await get_visible_employee_ids(db, current_user)
    return await service.list_mass_exam_results(
        db, current_user.tenant_id, mass_exam_id, visible_employee_ids=visible_ids
    )


# --- Assign employees ---


@router.post("/mass-exams/{mass_exam_id}/employees", status_code=201)
async def assign_employees(
    mass_exam_id: uuid.UUID,
    employee_ids: list[uuid.UUID],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _scope: None = Depends(mass_exam_scope),
):
    return await service.assign_employees(
        db, current_user.tenant_id, mass_exam_id, employee_ids
    )


# --- Individual Exam ---


async def _personal_scope(
    db: AsyncSession, current_user: User
) -> set[uuid.UUID] | None:
    """Who the personal routes answer for (HRP-823).

    They sit outside the matrix (``PERSONAL_PATHS``) so an exam already
    assigned outlives a section the tenant closed - but only as one's own.
    A caller whose ``exams`` is ``none`` reads their own row and nothing
    else, which is what "closing the section closes its API" has to mean
    on the half that cannot be closed outright. Above ``none`` the section
    is open and the read scope answers as it always did: a division head
    their subtree, admin and HR the workspace.
    """
    if (await matrix_levels(db, current_user))["exams"] != "none":
        return await get_visible_employee_ids(db, current_user)
    own = await get_current_employee(db, current_user)
    return {own.id} if own else set()


# HRP-823 (QA 13.10): the two tabs every level opens on /exams - "My
# exams" (one's own, once the mass exam left Draft) and "To do" (one's own
# still assigned or in progress). Both answer for the caller's own employee
# row whatever their level or read scope, so a division head sees only
# their own there, not their subtree's.
ExamTab = Literal["mine", "todo"]


async def _own_exams(db: AsyncSession, current_user: User, tab: ExamTab) -> list[dict]:
    own = await get_current_employee(db, current_user)
    if own is None:
        return []
    return await service.list_my_exams(
        db, current_user.tenant_id, employee_id=own.id, todo_only=tab == "todo"
    )


@router.get("/exams/todo-count")
async def count_my_exams_to_do(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    """The N of the "To do (N)" tab (HRP-823)."""
    return {"count": len(await _own_exams(db, current_user, "todo"))}


@router.get("/exams", response_model=list[ExamRead])
async def list_my_exams(
    employee_id: uuid.UUID | None = None,
    tab: ExamTab | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if tab is not None:
        return await _own_exams(db, current_user, tab)
    visible_ids = await _personal_scope(db, current_user)
    if (
        employee_id is not None
        and visible_ids is not None
        and employee_id not in visible_ids
    ):
        raise AppError("exam_out_of_scope", http_status.HTTP_403_FORBIDDEN)
    return await service.list_my_exams(
        db,
        current_user.tenant_id,
        employee_id=employee_id,
        visible_employee_ids=visible_ids,
    )


async def _acting_employee_id(
    db: AsyncSession, current_user: User
) -> uuid.UUID:
    """HRP-328: taking an exam requires the caller's own employee row."""
    emp = await get_current_employee(db, current_user)
    if emp is None:
        raise AppError(
            "exam_only_assigned_employee", http_status.HTTP_403_FORBIDDEN
        )
    return emp.id


@router.get("/exams/{exam_id}/questions", response_model=ExamTakeRead)
async def get_exam_questions(
    exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HRP-328: take-sheet payload — questions without the answer key plus
    the caller's saved answers for resume."""
    emp_id = await _acting_employee_id(db, current_user)
    return await service.get_exam_questions(
        db, current_user.tenant_id, exam_id, acting_employee_id=emp_id
    )


@router.get("/exams/{exam_id}/review", response_model=ExamReviewRead)
async def get_exam_review(
    exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HRP-328: submitted results with the answer key revealed — for the
    owner and, while the section is open to them, anyone whose access
    scope covers the employee (HRP-823)."""
    emp = await get_current_employee(db, current_user)
    visible_ids = await _personal_scope(db, current_user)
    return await service.get_exam_review(
        db,
        current_user.tenant_id,
        exam_id,
        acting_employee_id=emp.id if emp else None,
        visible_employee_ids=visible_ids,
    )


@router.post("/exams/{exam_id}/answer", status_code=201)
async def submit_answer(
    exam_id: uuid.UUID,
    data: ExamAnswerSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp_id = await _acting_employee_id(db, current_user)
    return await service.submit_answer(
        db, current_user.tenant_id, exam_id, data, acting_employee_id=emp_id
    )


@router.post("/exams/{exam_id}/finish", response_model=ExamResultRead)
async def finish_exam(
    exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp_id = await _acting_employee_id(db, current_user)
    return await service.finish_exam(
        db, current_user.tenant_id, exam_id, acting_employee_id=emp_id
    )
