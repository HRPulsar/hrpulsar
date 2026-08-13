"""HRP-58 (REDO): division reporting has to see nested departments.

QA hit this on a three-level org (Engineering -> QA -> QA-2): the
Specializations block on the third-level division rendered "(0)" even
though the division had staff. The frontend counted only employees whose
``division_id`` matched the page exactly, so any org that keeps people in
child departments reported zero for the parent.

These tests pin the read-side widening the fix relies on:
``get_division_subtree_ids`` and the ``include_sub_divisions`` flag on
``GET /api/employees``. Depth is deliberately >= 3 levels — two levels
passed before the fix, which is exactly why the bug shipped.
"""

from __future__ import annotations

import uuid
from datetime import date

from app.modules.company import service as company_service
from app.modules.company.models import Division
from app.modules.company.schemas import DivisionCreate
from app.modules.employee import service as employee_service
from app.modules.employee.models import Employee
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_division(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    name: str,
    parent_id: uuid.UUID | None = None,
) -> uuid.UUID:
    div = await company_service.create_division(
        db, tenant_id, DivisionCreate(name=name, parent_id=parent_id)
    )
    return div["id"]


async def _make_employee(
    db: AsyncSession, tenant_id: uuid.UUID, division_id: uuid.UUID
) -> Employee:
    """An employee needs a user; the user only needs to be unique here."""
    from app.core.security import hash_password
    from app.modules.auth.models import User

    u = User(
        email=f"sub-{uuid.uuid4().hex[:10]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Sub",
        last_name="Tree",
        tenant_id=tenant_id,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)

    emp = Employee(
        tenant_id=tenant_id,
        user_id=u.id,
        division_id=division_id,
        hire_date=date(2026, 1, 1),
        status="active",
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


class TestDivisionSubtreeIds:
    async def test_three_levels_are_collected_from_the_root(
        self, db: AsyncSession, tenant
    ):
        l1 = await _make_division(db, tenant.id, "Engineering")
        l2 = await _make_division(db, tenant.id, "QA", parent_id=l1)
        l3 = await _make_division(db, tenant.id, "QA-2", parent_id=l2)
        l4 = await _make_division(db, tenant.id, "QA-2 Automation", parent_id=l3)

        ids = await company_service.get_division_subtree_ids(db, tenant.id, [l1])

        assert set(ids) == {l1, l2, l3, l4}
        # The root stays first — callers may treat it as the primary scope.
        assert ids[0] == l1

    async def test_mid_level_collects_only_its_own_branch(
        self, db: AsyncSession, tenant
    ):
        l1 = await _make_division(db, tenant.id, "Engineering")
        l2 = await _make_division(db, tenant.id, "QA", parent_id=l1)
        l3 = await _make_division(db, tenant.id, "QA-2", parent_id=l2)
        sibling = await _make_division(db, tenant.id, "Backend", parent_id=l1)

        ids = await company_service.get_division_subtree_ids(db, tenant.id, [l2])

        assert set(ids) == {l2, l3}
        assert sibling not in ids
        assert l1 not in ids

    async def test_leaf_returns_itself(self, db: AsyncSession, tenant):
        l1 = await _make_division(db, tenant.id, "Engineering")
        l2 = await _make_division(db, tenant.id, "QA", parent_id=l1)
        l3 = await _make_division(db, tenant.id, "QA-2", parent_id=l2)

        assert await company_service.get_division_subtree_ids(db, tenant.id, [l3]) == [
            l3
        ]

    async def test_foreign_tenant_division_is_dropped(self, db: AsyncSession, tenant):
        from app.modules.company.models import Tenant

        other = Tenant(
            name="Other Corp", slug=f"other-{uuid.uuid4().hex[:8]}"
        )
        db.add(other)
        await db.commit()
        await db.refresh(other)

        mine = await _make_division(db, tenant.id, "Engineering")
        theirs = await _make_division(db, other.id, "Their Engineering")

        ids = await company_service.get_division_subtree_ids(
            db, tenant.id, [mine, theirs]
        )

        assert ids == [mine]

    async def test_empty_input_returns_empty(self, db: AsyncSession, tenant):
        assert await company_service.get_division_subtree_ids(db, tenant.id, []) == []

    async def test_parent_cycle_terminates(self, db: AsyncSession, tenant):
        """A corrupted parent chain must not hang the request."""
        a = await _make_division(db, tenant.id, "A")
        b = await _make_division(db, tenant.id, "B", parent_id=a)
        # Close the loop directly in the DB — the API layer forbids this.
        div_a = await db.get(Division, a)
        assert div_a is not None
        div_a.parent_id = b
        await db.commit()

        ids = await company_service.get_division_subtree_ids(db, tenant.id, [a])

        assert set(ids) == {a, b}


class TestListEmployeesIncludeSubDivisions:
    async def test_parent_counts_nested_employees(self, db: AsyncSession, tenant):
        l1 = await _make_division(db, tenant.id, "Engineering")
        l2 = await _make_division(db, tenant.id, "QA", parent_id=l1)
        l3 = await _make_division(db, tenant.id, "QA-2", parent_id=l2)
        await _make_employee(db, tenant.id, l1)
        await _make_employee(db, tenant.id, l2)
        await _make_employee(db, tenant.id, l3)
        await _make_employee(db, tenant.id, l3)

        items, total = await employee_service.list_employees(
            db, tenant.id, division_id=[l1], include_sub_divisions=True
        )
        assert total == 4
        assert len(items) == 4

        # Third level: the case QA reported — one branch, its own people.
        items, total = await employee_service.list_employees(
            db, tenant.id, division_id=[l3], include_sub_divisions=True
        )
        assert total == 2

        # Middle level sees itself plus the level below, never the parent.
        _, total = await employee_service.list_employees(
            db, tenant.id, division_id=[l2], include_sub_divisions=True
        )
        assert total == 3

    async def test_flag_off_keeps_exact_division_semantics(
        self, db: AsyncSession, tenant
    ):
        l1 = await _make_division(db, tenant.id, "Engineering")
        l2 = await _make_division(db, tenant.id, "QA", parent_id=l1)
        await _make_employee(db, tenant.id, l1)
        await _make_employee(db, tenant.id, l2)

        _, total = await employee_service.list_employees(
            db, tenant.id, division_id=[l1]
        )
        assert total == 1

    async def test_unknown_division_yields_nothing(self, db: AsyncSession, tenant):
        _, total = await employee_service.list_employees(
            db, tenant.id, division_id=[uuid.uuid4()], include_sub_divisions=True
        )
        assert total == 0

    async def test_api_accepts_the_flag(self, auth_client, db: AsyncSession, tenant):
        l1 = await _make_division(db, tenant.id, "Engineering API")
        l2 = await _make_division(db, tenant.id, "QA API", parent_id=l1)
        l3 = await _make_division(db, tenant.id, "QA-2 API", parent_id=l2)
        await _make_employee(db, tenant.id, l3)

        # The exact shape the division detail page sends.
        response = await auth_client.get(
            f"/api/employees?division_id={l1}&include_sub_divisions=true&limit=500"
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1

        response = await auth_client.get(
            f"/api/employees?division_id={l1}&limit=500"
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 0
