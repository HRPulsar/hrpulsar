"""HRP-66: a regular employee can manage Education and Courses on their
*own* profile (the rest of /employees/{id}/* stays admin/manager-only).

Spec:
  - POST/PUT/DELETE /employees/{own_id}/education → 200/201 for employee role
  - POST/PUT/DELETE /employees/{other_id}/education → 403
  - POST /employees/{own_id}/work-experience → still 403 (only Education/Courses
    are carved out)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from app.core.security import hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.employee.models import Employee
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


@pytest_asyncio.fixture
async def employee_role(db: AsyncSession):
    result = await db.execute(select(Role).where(Role.code == "employee"))
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(name="Employee", code="employee", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


async def _make_user(db: AsyncSession, tenant_id, role, *, prefix: str) -> User:
    u = User(
        email=f"{prefix}-{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name=prefix.capitalize(),
        last_name="User",
        tenant_id=tenant_id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
    await db.commit()
    db.expunge(u)
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == u.id)
    )
    return result.scalar_one()


async def _make_employee(db: AsyncSession, tenant_id, user_id) -> Employee:
    emp = Employee(
        tenant_id=tenant_id,
        user_id=user_id,
        hire_date=date(2024, 1, 1),
        status="active",
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


class TestEducationSelfService:
    async def test_employee_can_create_own_education(
        self, db: AsyncSession, tenant, employee_role
    ):
        from app.modules.employee import service
        from app.modules.employee.schemas import EducationCreate

        emp_user = await _make_user(db, tenant.id, employee_role, prefix="ed-self")
        emp = await _make_employee(db, tenant.id, emp_user.id)

        result = await service.create_education(
            db,
            tenant.id,
            emp.id,
            EducationCreate(
                degree="BSc",
                institution="University X",
                field_of_study="Computer Science",
                start_date=date(2020, 9, 1),
                end_date=date(2024, 6, 1),
            ),
            emp_user,
        )
        assert result["degree"] == "BSc"
        assert result["employee_id"] == emp.id

    async def test_employee_cannot_create_education_on_someone_else(
        self, db: AsyncSession, tenant, employee_role
    ):
        from app.modules.employee import service
        from app.modules.employee.schemas import EducationCreate

        actor_user = await _make_user(db, tenant.id, employee_role, prefix="ed-actor")
        await _make_employee(db, tenant.id, actor_user.id)

        # Different user / different employee row
        target_user = await _make_user(db, tenant.id, employee_role, prefix="ed-target")
        target_emp = await _make_employee(db, tenant.id, target_user.id)

        with pytest.raises(HTTPException) as exc:
            await service.create_education(
                db,
                tenant.id,
                target_emp.id,
                EducationCreate(
                    degree="MSc",
                    institution="University Y",
                    field_of_study="Robotics",
                    start_date=date(2024, 9, 1),
                ),
                actor_user,
            )
        # 403 — bare employee role cannot write to a peer's profile.
        assert exc.value.status_code == 403


class TestWorkExperienceStaysAdminManagerOnly:
    async def test_employee_cannot_create_work_experience_even_on_self(
        self, db: AsyncSession, tenant, employee_role
    ):
        """HRP-66 carves out only Education + Courses. Work Experience,
        Compensation, Events, and the rest of the profile are still
        admin/manager-only, even on one's own row."""
        from app.modules.company.models import Division
        from app.modules.employee import service
        from app.modules.employee.schemas import WorkExperienceCreate
        from app.modules.position.models import Position

        emp_user = await _make_user(db, tenant.id, employee_role, prefix="we-self")
        emp = await _make_employee(db, tenant.id, emp_user.id)
        div = Division(tenant_id=tenant.id, name="Self-scope")
        pos = Position(tenant_id=tenant.id, title="Self", source="manual")
        db.add_all([div, pos])
        await db.commit()
        await db.refresh(div)
        await db.refresh(pos)

        with pytest.raises(HTTPException) as exc:
            await service.create_work_experience(
                db,
                tenant.id,
                emp.id,
                WorkExperienceCreate(
                    division_id=div.id,
                    position_id=pos.id,
                    start_date=date(2025, 1, 1),
                ),
                emp_user,
            )
        assert exc.value.status_code == 403
