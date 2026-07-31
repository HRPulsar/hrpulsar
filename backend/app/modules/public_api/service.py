import secrets
import uuid
from datetime import datetime, timezone

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import hash_password, verify_password
from app.modules.public_api.models import APIKey

# --- API Key Management ---


def generate_api_key() -> tuple[str, str, str]:
    """Generate API key. Returns (full_key, key_hash, prefix)."""
    raw_key = f"hrp_{secrets.token_urlsafe(32)}"
    prefix = raw_key[:8]
    key_hash = hash_password(raw_key)
    return raw_key, key_hash, prefix


async def create_api_key(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, name: str
) -> dict:
    raw_key, key_hash, prefix = generate_api_key()

    api_key = APIKey(
        tenant_id=tenant_id,
        name=name,
        key_hash=key_hash,
        prefix=prefix,
        created_by=user_id,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return {
        "id": api_key.id,
        "name": api_key.name,
        "prefix": api_key.prefix,
        "key": raw_key,  # Only returned once on creation
        "created_at": api_key.created_at,
    }


async def list_api_keys(db: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    result = await db.execute(
        select(APIKey)
        .where(APIKey.tenant_id == tenant_id)
        .order_by(APIKey.created_at.desc())
    )
    return [
        {
            "id": k.id,
            "name": k.name,
            "prefix": k.prefix,
            "is_active": k.is_active,
            "last_used_at": k.last_used_at,
            "created_at": k.created_at,
        }
        for k in result.scalars().all()
    ]


async def revoke_api_key(
    db: AsyncSession, tenant_id: uuid.UUID, key_id: uuid.UUID
) -> None:
    key = await db.get(APIKey, key_id)
    if not key or key.tenant_id != tenant_id:
        raise AppError("api_key_not_found", status.HTTP_404_NOT_FOUND)
    key.is_active = False
    await db.commit()


async def authenticate_api_key(db: AsyncSession, raw_key: str) -> APIKey | None:
    """Authenticate an API key and return the key record."""
    prefix = raw_key[:8]
    result = await db.execute(
        select(APIKey).where(
            APIKey.prefix == prefix, APIKey.is_active == True  # noqa: E712
        )
    )
    for key in result.scalars().all():
        if verify_password(raw_key, key.key_hash):
            key.last_used_at = datetime.now(timezone.utc)
            await db.commit()
            return key
    return None


# --- Batch Employees ---


async def batch_create_employees(
    db: AsyncSession, tenant_id: uuid.UUID, items: list
) -> dict:
    from app.modules.auth.models import Role, User, user_roles
    from app.modules.company.models import Division
    from app.modules.employee.models import Employee

    results = []
    created = 0

    # Get employee role
    role_result = await db.execute(
        select(Role).where(
            Role.code == "employee", Role.is_system == True  # noqa: E712
        )
    )
    employee_role = role_result.scalar_one_or_none()

    for idx, item in enumerate(items):
        try:
            # Check email uniqueness within tenant
            existing = await db.execute(
                select(User).where(
                    User.email == item.email, User.tenant_id == tenant_id
                )
            )
            if existing.scalar_one_or_none():
                results.append(
                    {
                        "index": idx,
                        "success": False,
                        "id": None,
                        "error": f"Email {item.email} already exists",
                    }
                )
                continue

            # Validate division
            if item.division_id:
                div = await db.get(Division, item.division_id)
                if not div or div.tenant_id != tenant_id:
                    results.append(
                        {
                            "index": idx,
                            "success": False,
                            "id": None,
                            "error": "Invalid division_id",
                        }
                    )
                    continue

            # Create user with random password (can be reset via invitation)
            temp_password = secrets.token_urlsafe(16)
            user = User(
                email=item.email,
                password_hash=hash_password(temp_password),
                first_name=item.first_name,
                last_name=item.last_name,
                tenant_id=tenant_id,
            )
            db.add(user)
            await db.flush()

            # Assign employee role
            if employee_role:
                await db.execute(
                    user_roles.insert().values(
                        user_id=user.id, role_id=employee_role.id
                    )
                )

            # Resolve position_id from text or direct ID
            pos_id = item.position_id
            pos_title = item.position
            if not pos_id and item.position:
                from app.modules.position.models import Position as PositionModel

                pos_result = await db.execute(
                    select(PositionModel).where(
                        PositionModel.tenant_id == tenant_id,
                        PositionModel.title == item.position,
                    )
                )
                pos = pos_result.scalar_one_or_none()
                if not pos:
                    pos = PositionModel(
                        tenant_id=tenant_id,
                        title=item.position,
                        source="manual",
                    )
                    db.add(pos)
                    await db.flush()
                pos_id = pos.id
                pos_title = pos.title
            elif pos_id:
                from app.modules.position.models import Position as PositionModel

                pos = await db.get(PositionModel, pos_id)
                pos_title = pos.title if pos else item.position

            # Create employee
            emp = Employee(
                tenant_id=tenant_id,
                user_id=user.id,
                position_id=pos_id,
                position_title=pos_title,
                hire_date=item.hire_date,
                division_id=item.division_id,
            )
            db.add(emp)
            await db.flush()

            results.append(
                {"index": idx, "success": True, "id": str(emp.id), "error": None}
            )
            created += 1
        except Exception as e:  # noqa: BLE001 - per-item bulk isolation, recorded
            results.append(
                {"index": idx, "success": False, "id": None, "error": str(e)}
            )

    await db.commit()

    return {
        "total": len(items),
        "created": created,
        "errors": len(items) - created,
        "results": results,
    }


async def batch_update_employees(
    db: AsyncSession, tenant_id: uuid.UUID, items: list
) -> dict:
    from app.modules.employee.models import Employee

    results = []
    updated = 0

    for idx, item in enumerate(items):
        try:
            emp = await db.get(Employee, item.id)
            if not emp or emp.tenant_id != tenant_id:
                results.append(
                    {
                        "index": idx,
                        "success": False,
                        "id": str(item.id),
                        "error": "Employee not found",
                    }
                )
                continue

            # Handle position update
            if item.position_id is not None:
                from app.modules.position.models import Position as PositionModel

                pos = await db.get(PositionModel, item.position_id)
                if pos and pos.tenant_id == tenant_id:
                    emp.position_id = pos.id
                    emp.position_title = pos.title
            elif item.position is not None:
                from app.modules.position.models import Position as PositionModel

                pos_result = await db.execute(
                    select(PositionModel).where(
                        PositionModel.tenant_id == tenant_id,
                        PositionModel.title == item.position,
                    )
                )
                pos = pos_result.scalar_one_or_none()
                if not pos:
                    pos = PositionModel(
                        tenant_id=tenant_id,
                        title=item.position,
                        source="manual",
                    )
                    db.add(pos)
                    await db.flush()
                emp.position_id = pos.id
                emp.position_title = pos.title

            for field in ("division_id", "status"):
                value = getattr(item, field, None)
                if value is not None:
                    setattr(emp, field, value)

            results.append(
                {"index": idx, "success": True, "id": str(emp.id), "error": None}
            )
            updated += 1
        except Exception as e:  # noqa: BLE001 - per-item bulk isolation, recorded
            results.append(
                {"index": idx, "success": False, "id": str(item.id), "error": str(e)}
            )

    await db.commit()

    return {
        "total": len(items),
        "created": updated,
        "errors": len(items) - updated,
        "results": results,
    }


# --- Batch Divisions ---


async def batch_create_divisions(
    db: AsyncSession, tenant_id: uuid.UUID, items: list
) -> dict:
    from app.modules.company.models import Division

    results = []
    created = 0

    for idx, item in enumerate(items):
        try:
            # Validate parent
            if item.parent_id:
                parent = await db.get(Division, item.parent_id)
                if not parent or parent.tenant_id != tenant_id:
                    results.append(
                        {
                            "index": idx,
                            "success": False,
                            "id": None,
                            "error": "Invalid parent_id",
                        }
                    )
                    continue

            div = Division(
                tenant_id=tenant_id,
                name=item.name,
                description=item.description,
                parent_id=item.parent_id,
            )
            db.add(div)
            await db.flush()

            results.append(
                {"index": idx, "success": True, "id": str(div.id), "error": None}
            )
            created += 1
        except Exception as e:  # noqa: BLE001 - per-item bulk isolation, recorded
            results.append(
                {"index": idx, "success": False, "id": None, "error": str(e)}
            )

    await db.commit()

    return {
        "total": len(items),
        "created": created,
        "errors": len(items) - created,
        "results": results,
    }


# --- Batch Specializations ---


async def batch_create_specializations(
    db: AsyncSession, tenant_id: uuid.UUID, items: list
) -> dict:
    from app.modules.dictionary.models import DictionaryItem

    results = []
    created = 0

    for idx, item in enumerate(items):
        try:
            di = DictionaryItem(
                tenant_id=tenant_id,
                type="specialization",
                title=item.title,
                description=item.description,
                is_active=True,
            )
            db.add(di)
            await db.flush()

            results.append({"index": idx, "success": True, "id": di.id, "error": None})
            created += 1
        except Exception as e:  # noqa: BLE001 - per-item bulk isolation, recorded
            results.append(
                {"index": idx, "success": False, "id": None, "error": str(e)}
            )

    await db.commit()

    return {
        "total": len(items),
        "created": created,
        "errors": len(items) - created,
        "results": results,
    }


# --- Batch Grades ---


async def batch_create_grades(
    db: AsyncSession, tenant_id: uuid.UUID, items: list
) -> dict:
    from app.modules.dictionary.models import DictionaryItem

    results = []
    created = 0

    for idx, item in enumerate(items):
        try:
            di = DictionaryItem(
                tenant_id=tenant_id,
                type="grade",
                title=item.title,
                description=item.description,
                sort_index=item.sort_index,
                is_active=True,
            )
            db.add(di)
            await db.flush()

            results.append({"index": idx, "success": True, "id": di.id, "error": None})
            created += 1
        except Exception as e:  # noqa: BLE001 - per-item bulk isolation, recorded
            results.append(
                {"index": idx, "success": False, "id": None, "error": str(e)}
            )

    await db.commit()

    return {
        "total": len(items),
        "created": created,
        "errors": len(items) - created,
        "results": results,
    }


# --- Batch Assessments ---


async def batch_create_assessments(
    db: AsyncSession, tenant_id: uuid.UUID, initiator_id: uuid.UUID, data
) -> dict:
    from app.modules.assessment.models import (
        Assessment,
        AssessmentStatus,
        AssessmentType,
    )
    from app.modules.employee.models import Employee

    results = []
    created = 0

    # Get type and draft status
    type_result = await db.execute(
        select(AssessmentType).where(AssessmentType.code == data.type_code)
    )
    atype = type_result.scalar_one_or_none()
    if not atype:
        return {
            "total": len(data.employee_ids),
            "created": 0,
            "errors": len(data.employee_ids),
            "results": [
                {
                    "index": i,
                    "success": False,
                    "id": None,
                    "error": f"Invalid type_code: {data.type_code}",
                }
                for i in range(len(data.employee_ids))
            ],
        }

    status_result = await db.execute(
        select(AssessmentStatus).where(AssessmentStatus.code == "draft")
    )
    draft = status_result.scalar_one_or_none()
    if not draft:
        return {
            "total": len(data.employee_ids),
            "created": 0,
            "errors": len(data.employee_ids),
            "results": [
                {
                    "index": i,
                    "success": False,
                    "id": None,
                    "error": "Draft status not found",
                }
                for i in range(len(data.employee_ids))
            ],
        }

    for idx, emp_id in enumerate(data.employee_ids):
        try:
            # Validate employee
            emp = await db.get(Employee, emp_id)
            if not emp or emp.tenant_id != tenant_id:
                results.append(
                    {
                        "index": idx,
                        "success": False,
                        "id": None,
                        "error": "Employee not found",
                    }
                )
                continue

            a = Assessment(
                tenant_id=tenant_id,
                title=data.title,
                employee_id=emp_id,
                type_id=atype.id,
                status_id=draft.id,
                specialization_id=data.specialization_id,
                grade_id=data.grade_id,
                scale_id=data.scale_id,
                initiator_id=initiator_id,
                ended_at=data.ended_at,
            )
            db.add(a)
            await db.flush()

            results.append(
                {"index": idx, "success": True, "id": str(a.id), "error": None}
            )
            created += 1
        except Exception as e:  # noqa: BLE001 - per-item bulk isolation, recorded
            results.append(
                {"index": idx, "success": False, "id": None, "error": str(e)}
            )

    await db.commit()

    return {
        "total": len(data.employee_ids),
        "created": created,
        "errors": len(data.employee_ids) - created,
        "results": results,
    }


# --- Batch Exam Assignment ---


async def batch_assign_exams(db: AsyncSession, tenant_id: uuid.UUID, data) -> dict:
    from app.modules.company.models import SpecializationDivision
    from app.modules.employee.models import Employee
    from app.modules.exam.models import Exam, ExamQuestion, MassExam

    # Validate mass exam
    me = await db.get(MassExam, data.mass_exam_id)
    if not me or me.tenant_id != tenant_id:
        raise AppError("exam_mass_exam_not_found", status.HTTP_404_NOT_FOUND)

    # Resolve employee IDs from filters
    employee_ids: set[uuid.UUID] = set()

    if data.employee_ids:
        employee_ids.update(data.employee_ids)

    if data.division_ids:
        result = await db.execute(
            select(Employee.id).where(
                Employee.tenant_id == tenant_id,
                Employee.division_id.in_(data.division_ids),
                Employee.status == "active",
            )
        )
        employee_ids.update(row[0] for row in result.all())

    if data.specialization_ids:
        # Find divisions linked to these specializations
        div_result = await db.execute(
            select(SpecializationDivision.division_id).where(
                SpecializationDivision.tenant_id == tenant_id,
                SpecializationDivision.specialization_id.in_(data.specialization_ids),
            )
        )
        div_ids = [row[0] for row in div_result.all()]
        if div_ids:
            emp_result = await db.execute(
                select(Employee.id).where(
                    Employee.tenant_id == tenant_id,
                    Employee.division_id.in_(div_ids),
                    Employee.status == "active",
                )
            )
            employee_ids.update(row[0] for row in emp_result.all())

    if not employee_ids:
        return {"total": 0, "created": 0, "errors": 0, "results": []}

    # Calculate max score
    q_result = await db.execute(
        select(ExamQuestion).where(
            ExamQuestion.mass_exam_id == data.mass_exam_id,
            ExamQuestion.is_active == True,  # noqa: E712
        )
    )
    max_score = sum(q.weight for q in q_result.scalars().all())

    # Check already assigned
    existing_result = await db.execute(
        select(Exam.employee_id).where(
            Exam.mass_exam_id == data.mass_exam_id,
            Exam.employee_id.in_(employee_ids),
        )
    )
    already_assigned = {row[0] for row in existing_result.all()}

    results = []
    created = 0
    sorted_ids = sorted(employee_ids)

    for idx, emp_id in enumerate(sorted_ids):
        if emp_id in already_assigned:
            results.append(
                {
                    "index": idx,
                    "success": False,
                    "id": None,
                    "error": "Already assigned",
                }
            )
            continue

        try:
            exam = Exam(
                tenant_id=tenant_id,
                mass_exam_id=data.mass_exam_id,
                employee_id=emp_id,
                max_score=max_score,
            )
            db.add(exam)
            await db.flush()

            results.append(
                {"index": idx, "success": True, "id": str(exam.id), "error": None}
            )
            created += 1
        except Exception as e:  # noqa: BLE001 - per-item bulk isolation, recorded
            results.append(
                {"index": idx, "success": False, "id": None, "error": str(e)}
            )

    await db.commit()

    return {
        "total": len(sorted_ids),
        "created": created,
        "errors": len(sorted_ids) - created,
        "results": results,
    }
