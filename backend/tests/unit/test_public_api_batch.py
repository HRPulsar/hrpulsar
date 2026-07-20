import uuid
from datetime import date

import pytest
from app.modules.public_api import service
from app.modules.public_api.schemas import (
    AssessmentBatchCreate,
    DivisionBatchItem,
    EmployeeBatchItem,
    EmployeeBatchUpdateItem,
    ExamBatchAssign,
    GradeBatchItem,
    SpecializationBatchItem,
)
from sqlalchemy.ext.asyncio import AsyncSession


class TestAPIKeyService:
    async def test_create_and_list(self, db: AsyncSession, tenant, user):
        result = await service.create_api_key(db, tenant.id, user.id, "Test Key")
        assert result["name"] == "Test Key"
        assert result["key"].startswith("hrp_")
        assert result["prefix"] == result["key"][:8]

        keys = await service.list_api_keys(db, tenant.id)
        assert len(keys) >= 1
        assert any(k["name"] == "Test Key" for k in keys)

    async def test_authenticate(self, db: AsyncSession, tenant, user):
        result = await service.create_api_key(db, tenant.id, user.id, "Auth Key")
        raw_key = result["key"]

        authenticated = await service.authenticate_api_key(db, raw_key)
        assert authenticated is not None
        assert authenticated.tenant_id == tenant.id

    async def test_authenticate_invalid(self, db: AsyncSession):
        result = await service.authenticate_api_key(db, "hrp_invalid_key")
        assert result is None

    async def test_revoke(self, db: AsyncSession, tenant, user):
        result = await service.create_api_key(db, tenant.id, user.id, "Revoke Key")
        await service.revoke_api_key(db, tenant.id, result["id"])

        authenticated = await service.authenticate_api_key(db, result["key"])
        assert authenticated is None


class TestBatchEmployees:
    async def test_batch_create(self, db: AsyncSession, tenant):
        items = [
            EmployeeBatchItem(
                email=f"emp{i}-{uuid.uuid4().hex[:6]}@test.com",
                first_name=f"First{i}",
                last_name=f"Last{i}",
                position="Engineer",
                hire_date=date(2024, 1, 1),
            )
            for i in range(3)
        ]
        result = await service.batch_create_employees(db, tenant.id, items)
        assert result["total"] == 3
        assert result["created"] == 3
        assert result["errors"] == 0
        assert all(r["success"] for r in result["results"])

    async def test_batch_create_duplicate_email(self, db: AsyncSession, tenant):
        email = f"dup-{uuid.uuid4().hex[:6]}@test.com"
        items = [
            EmployeeBatchItem(
                email=email,
                first_name="A",
                last_name="B",
                position="PM",
                hire_date=date(2024, 1, 1),
            ),
            EmployeeBatchItem(
                email=email,
                first_name="C",
                last_name="D",
                position="PM",
                hire_date=date(2024, 1, 1),
            ),
        ]
        result = await service.batch_create_employees(db, tenant.id, items)
        assert result["created"] == 1
        assert result["errors"] == 1
        assert result["results"][0]["success"] is True
        assert result["results"][1]["success"] is False
        assert "already exists" in result["results"][1]["error"]

    async def test_batch_create_invalid_division(self, db: AsyncSession, tenant):
        items = [
            EmployeeBatchItem(
                email=f"baddiv-{uuid.uuid4().hex[:6]}@test.com",
                first_name="A",
                last_name="B",
                position="PM",
                hire_date=date(2024, 1, 1),
                division_id=uuid.uuid4(),
            ),
        ]
        result = await service.batch_create_employees(db, tenant.id, items)
        assert result["errors"] == 1
        assert "Invalid division_id" in result["results"][0]["error"]

    async def test_batch_update(self, db: AsyncSession, tenant):
        # Create employees first
        items = [
            EmployeeBatchItem(
                email=f"upd-{uuid.uuid4().hex[:6]}@test.com",
                first_name="A",
                last_name="B",
                position="Engineer",
                hire_date=date(2024, 1, 1),
            ),
        ]
        create_result = await service.batch_create_employees(db, tenant.id, items)
        emp_id = create_result["results"][0]["id"]

        updates = [
            EmployeeBatchUpdateItem(id=emp_id, position="Senior Engineer"),
        ]
        result = await service.batch_update_employees(db, tenant.id, updates)
        assert result["created"] == 1  # "created" field is reused for "updated" count
        assert result["results"][0]["success"] is True

    async def test_batch_update_not_found(self, db: AsyncSession, tenant):
        updates = [
            EmployeeBatchUpdateItem(id=uuid.uuid4(), position="Ghost"),
        ]
        result = await service.batch_update_employees(db, tenant.id, updates)
        assert result["errors"] == 1
        assert "not found" in result["results"][0]["error"]


class TestBatchDivisions:
    async def test_batch_create(self, db: AsyncSession, tenant):
        items = [DivisionBatchItem(name=f"Division {i}") for i in range(3)]
        result = await service.batch_create_divisions(db, tenant.id, items)
        assert result["created"] == 3
        assert result["errors"] == 0

    async def test_batch_create_with_parent(self, db: AsyncSession, tenant):
        # Create parent first
        parent_items = [DivisionBatchItem(name="Parent Division")]
        parent_result = await service.batch_create_divisions(
            db, tenant.id, parent_items
        )
        parent_id = parent_result["results"][0]["id"]

        # Create children
        children = [
            DivisionBatchItem(name=f"Child {i}", parent_id=parent_id) for i in range(2)
        ]
        result = await service.batch_create_divisions(db, tenant.id, children)
        assert result["created"] == 2

    async def test_batch_create_invalid_parent(self, db: AsyncSession, tenant):
        items = [DivisionBatchItem(name="Orphan", parent_id=uuid.uuid4())]
        result = await service.batch_create_divisions(db, tenant.id, items)
        assert result["errors"] == 1
        assert "Invalid parent_id" in result["results"][0]["error"]


class TestBatchSpecializations:
    async def test_batch_create(self, db: AsyncSession, tenant):
        items = [
            SpecializationBatchItem(title=f"Spec {uuid.uuid4().hex[:6]}")
            for _ in range(3)
        ]
        result = await service.batch_create_specializations(db, tenant.id, items)
        assert result["created"] == 3
        assert result["errors"] == 0


class TestBatchGrades:
    async def test_batch_create(self, db: AsyncSession, tenant):
        items = [
            GradeBatchItem(title=f"Grade {uuid.uuid4().hex[:6]}", sort_index=i)
            for i in range(3)
        ]
        result = await service.batch_create_grades(db, tenant.id, items)
        assert result["created"] == 3
        assert result["errors"] == 0


class TestBatchAssessments:
    async def test_batch_create(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_types,
        assessment_statuses,
    ):
        data = AssessmentBatchCreate(
            employee_ids=[employee.id],
            type_code="360",
            title="Batch Assessment",
        )
        result = await service.batch_create_assessments(db, tenant.id, user.id, data)
        assert result["created"] == 1
        assert result["errors"] == 0
        assert result["results"][0]["success"] is True

    async def test_batch_create_invalid_type(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_types,
        assessment_statuses,
    ):
        data = AssessmentBatchCreate(
            employee_ids=[employee.id],
            type_code="invalid_type",
        )
        result = await service.batch_create_assessments(db, tenant.id, user.id, data)
        assert result["errors"] == 1
        assert "Invalid type_code" in result["results"][0]["error"]

    async def test_batch_create_invalid_employee(
        self,
        db: AsyncSession,
        tenant,
        user,
        assessment_types,
        assessment_statuses,
    ):
        data = AssessmentBatchCreate(
            employee_ids=[uuid.uuid4()],
            type_code="360",
        )
        result = await service.batch_create_assessments(db, tenant.id, user.id, data)
        assert result["errors"] == 1
        assert "not found" in result["results"][0]["error"]


class TestBatchExamAssignment:
    async def test_batch_assign_by_employee_ids(
        self, db: AsyncSession, tenant, user, employee
    ):
        from app.modules.exam.models import MassExam

        me = MassExam(
            tenant_id=tenant.id,
            title="Batch Exam",
            initiator_id=user.id,
        )
        db.add(me)
        await db.commit()
        await db.refresh(me)

        data = ExamBatchAssign(
            mass_exam_id=me.id,
            employee_ids=[employee.id],
        )
        result = await service.batch_assign_exams(db, tenant.id, data)
        assert result["created"] == 1

    async def test_batch_assign_already_assigned(
        self, db: AsyncSession, tenant, user, employee
    ):
        from app.modules.exam.models import MassExam

        me = MassExam(
            tenant_id=tenant.id,
            title="Dup Exam",
            initiator_id=user.id,
        )
        db.add(me)
        await db.commit()
        await db.refresh(me)

        data = ExamBatchAssign(mass_exam_id=me.id, employee_ids=[employee.id])
        await service.batch_assign_exams(db, tenant.id, data)

        # Assign again
        result = await service.batch_assign_exams(db, tenant.id, data)
        assert result["errors"] == 1
        assert "Already assigned" in result["results"][0]["error"]

    async def test_batch_assign_by_division(self, db: AsyncSession, tenant, user):
        from datetime import date

        from app.modules.auth.models import User as AuthUser
        from app.modules.company.models import Division
        from app.modules.employee.models import Employee
        from app.modules.exam.models import MassExam

        # Create division
        div = Division(tenant_id=tenant.id, name="Test Div")
        db.add(div)
        await db.flush()

        # Create employees in that division
        emp_ids = []
        for i in range(2):
            u = AuthUser(
                email=f"divexam{i}-{uuid.uuid4().hex[:6]}@test.com",
                password_hash="x",
                first_name=f"E{i}",
                last_name="T",
                tenant_id=tenant.id,
            )
            db.add(u)
            await db.flush()
            emp = Employee(
                tenant_id=tenant.id,
                user_id=u.id,
                position_title="Tester",
                hire_date=date(2024, 1, 1),
                division_id=div.id,
            )
            db.add(emp)
            await db.flush()
            emp_ids.append(emp.id)

        me = MassExam(
            tenant_id=tenant.id,
            title="Div Exam",
            initiator_id=user.id,
        )
        db.add(me)
        await db.commit()
        await db.refresh(me)

        data = ExamBatchAssign(mass_exam_id=me.id, division_ids=[div.id])
        result = await service.batch_assign_exams(db, tenant.id, data)
        assert result["created"] == 2

    async def test_batch_assign_not_found_exam(self, db: AsyncSession, tenant):
        from fastapi import HTTPException

        data = ExamBatchAssign(mass_exam_id=uuid.uuid4(), employee_ids=[uuid.uuid4()])
        with pytest.raises(HTTPException) as exc:
            await service.batch_assign_exams(db, tenant.id, data)
        assert exc.value.status_code == 404
