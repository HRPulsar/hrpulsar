"""EMP4: EmployeeRead exposes specialization/grade derived from Position."""

import uuid
from datetime import date, datetime, timezone

import pytest_asyncio
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee import service
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from sqlalchemy.ext.asyncio import AsyncSession


async def _mk_user(db: AsyncSession, tenant_id: uuid.UUID) -> User:
    u = User(
        email=f"u-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name="U",
        last_name="X",
        tenant_id=tenant_id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture
async def position_with_spec_grade(db: AsyncSession, tenant):
    spec = DictionaryItem(type="specialization", title="Frontend", tenant_id=tenant.id)
    grade = DictionaryItem(type="grade", title="Senior", tenant_id=tenant.id)
    db.add_all([spec, grade])
    await db.commit()
    await db.refresh(spec)
    await db.refresh(grade)
    pos = Position(
        tenant_id=tenant.id,
        title="FE Senior",
        specialization_id=spec.id,
        grade_id=grade.id,
        source="manual",
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos, spec, grade


class TestEmployeeReadSpecializationGrade:
    async def test_employee_read_exposes_specialization_grade(
        self, db: AsyncSession, tenant, position_with_spec_grade
    ):
        pos, spec, grade = position_with_spec_grade
        u = await _mk_user(db, tenant.id)
        emp = Employee(
            tenant_id=tenant.id,
            user_id=u.id,
            position_id=pos.id,
            position_title=pos.title,
            hire_date=date(2024, 1, 1),
        )
        db.add(emp)
        await db.commit()
        await db.refresh(emp)

        result = await service.get_employee(db, tenant.id, emp.id)
        assert result["specialization_id"] == spec.id
        assert result["specialization_title"] == "Frontend"
        assert result["grade_id"] == grade.id
        assert result["grade_title"] == "Senior"

    async def test_employee_without_position_null_fields(
        self, db: AsyncSession, tenant
    ):
        u = await _mk_user(db, tenant.id)
        emp = Employee(
            tenant_id=tenant.id,
            user_id=u.id,
            position_id=None,
            position_title=None,
            hire_date=date(2024, 1, 1),
        )
        db.add(emp)
        await db.commit()
        await db.refresh(emp)

        result = await service.get_employee(db, tenant.id, emp.id)
        assert result["specialization_id"] is None
        assert result["specialization_title"] is None
        assert result["grade_id"] is None
        assert result["grade_title"] is None
