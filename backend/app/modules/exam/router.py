import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import get_current_employee, get_visible_employee_ids
from app.database import get_db
from app.modules.assessment.schemas import StatusChange
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.exam import service
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


# --- Mass Exam ---


@router.post("/mass-exams", response_model=MassExamRead, status_code=201)
async def create_mass_exam(
    data: MassExamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_mass_exam(
        db, current_user.tenant_id, current_user.id, data
    )


@router.get("/mass-exams", response_model=list[MassExamRead])
async def list_mass_exams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.list_mass_exams(db, current_user.tenant_id)


@router.get("/mass-exams/{mass_exam_id}", response_model=MassExamDetail)
async def get_mass_exam(
    mass_exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.get_mass_exam_detail(db, current_user.tenant_id, mass_exam_id)


@router.patch("/mass-exams/{mass_exam_id}", response_model=MassExamRead)
async def update_mass_exam(
    mass_exam_id: uuid.UUID,
    data: MassExamUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_mass_exam(
        db, current_user.tenant_id, mass_exam_id, data
    )


@router.post("/mass-exams/{mass_exam_id}/status", response_model=MassExamRead)
async def change_status(
    mass_exam_id: uuid.UUID,
    data: StatusChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
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
    current_user: User = Depends(require_role("admin", "manager")),
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
    current_user: User = Depends(require_role("admin", "manager")),
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
    current_user: User = Depends(require_role("admin", "manager")),
):
    await service.delete_question(
        db, current_user.tenant_id, mass_exam_id, question_id
    )
    return None


# --- GF9: Import Questions from Excel ---


@router.post("/mass-exams/{mass_exam_id}/import-questions")
async def import_questions(
    mass_exam_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    data = await file.read()
    return await service.import_questions_from_excel(
        db, current_user.tenant_id, mass_exam_id, data
    )


@router.get("/mass-exams/import-template")
async def download_import_template(
    current_user: User = Depends(require_role("admin", "manager")),
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
    current_user: User = Depends(require_role("admin", "manager")),
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
    current_user: User = Depends(require_role("admin", "manager")),
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
    current_user: User = Depends(require_role("admin", "manager")),
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
    current_user: User = Depends(require_role("admin", "manager")),
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
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.assign_employees(
        db, current_user.tenant_id, mass_exam_id, employee_ids
    )


# --- Individual Exam ---


@router.get("/exams", response_model=list[ExamRead])
async def list_my_exams(
    employee_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    visible_ids = await get_visible_employee_ids(db, current_user)
    if (
        employee_id is not None
        and visible_ids is not None
        and employee_id not in visible_ids
    ):
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, "Out of scope")
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
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            "Only the assigned employee can take this exam",
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
    owner and anyone whose access scope covers the employee."""
    emp = await get_current_employee(db, current_user)
    visible_ids = await get_visible_employee_ids(db, current_user)
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
