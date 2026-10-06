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

import pytest
from app.modules.company import service as company_service
from app.modules.company.models import Division
from app.modules.company.schemas import DivisionCreate, DivisionUpdate
from app.modules.employee import service as employee_service
from app.modules.employee.models import Employee
from fastapi import HTTPException
from sqlalchemy import text
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

        # HRP-572: a regression fails here instead of hanging the run.
        await db.execute(text("SET LOCAL statement_timeout = '5s'"))
        ids = await company_service.get_division_subtree_ids(db, tenant.id, [a])

        assert set(ids) == {a, b}


class TestDivisionSubtreeRecursiveQuery:
    """HRP-572: the walk runs as one recursive query; the contract of HRP-58
    holds - the same ids, the roots first, strangers dropped."""

    async def test_a_deep_chain_is_collected_whole(self, db: AsyncSession, tenant):
        chain = [await _make_division(db, tenant.id, "L0")]
        for depth in range(1, 25):
            chain.append(
                await _make_division(db, tenant.id, f"L{depth}", parent_id=chain[-1])
            )

        ids = await company_service.get_division_subtree_ids(db, tenant.id, chain[:1])

        assert sorted(ids) == sorted(chain)
        assert len(ids) == len(chain)
        assert ids[0] == chain[0]

    async def test_several_roots_come_first_in_the_order_given(
        self, db: AsyncSession, tenant
    ):
        a = await _make_division(db, tenant.id, "A")
        a1 = await _make_division(db, tenant.id, "A1", parent_id=a)
        b = await _make_division(db, tenant.id, "B")
        b1 = await _make_division(db, tenant.id, "B1", parent_id=b)
        b11 = await _make_division(db, tenant.id, "B11", parent_id=b1)
        await _make_division(db, tenant.id, "C")  # not asked for

        ids = await company_service.get_division_subtree_ids(db, tenant.id, [b, a])

        assert ids[:2] == [b, a]
        assert sorted(ids) == sorted([a, a1, b, b1, b11])

    async def test_duplicates_and_a_root_inside_another_count_once(
        self, db: AsyncSession, tenant
    ):
        top = await _make_division(db, tenant.id, "Top")
        mid = await _make_division(db, tenant.id, "Mid", parent_id=top)
        leaf = await _make_division(db, tenant.id, "Leaf", parent_id=mid)

        ids = await company_service.get_division_subtree_ids(
            db, tenant.id, [top, mid, top, leaf, mid]
        )

        assert ids[:3] == [top, mid, leaf]
        assert len(ids) == 3

    async def test_a_foreign_root_and_a_foreign_child_are_dropped(
        self, db: AsyncSession, tenant
    ):
        from app.modules.company.models import Tenant

        other = Tenant(name="Other Corp", slug=f"other-{uuid.uuid4().hex[:8]}")
        db.add(other)
        await db.commit()
        mine = await _make_division(db, tenant.id, "Mine")
        theirs = await _make_division(db, other.id, "Theirs")
        # A child of another tenant under my division: corrupted data, never
        # something the API writes - it still must not leak into my answer.
        stray = await _make_division(db, other.id, "Stray")
        div = await db.get(Division, stray)
        assert div is not None
        div.parent_id = mine
        await db.commit()

        assert await company_service.get_division_subtree_ids(
            db, tenant.id, [theirs, mine]
        ) == [mine]
        assert (
            await company_service.get_division_subtree_ids(db, tenant.id, [theirs])
            == []
        )

    async def test_a_cycle_with_a_branch_ends(self, db: AsyncSession, tenant):
        """``UNION`` is what ends the walk on a loop. The timeout turns a
        regression to ``UNION ALL`` into a failure instead of a hung run."""
        a = await _make_division(db, tenant.id, "A")
        b = await _make_division(db, tenant.id, "B", parent_id=a)
        c = await _make_division(db, tenant.id, "C", parent_id=b)
        side = await _make_division(db, tenant.id, "Side", parent_id=c)
        div_a = await db.get(Division, a)
        assert div_a is not None
        div_a.parent_id = c  # a -> b -> c -> a
        await db.commit()

        await db.execute(text("SET LOCAL statement_timeout = '5s'"))
        ids = await company_service.get_division_subtree_ids(db, tenant.id, [b])

        assert ids[0] == b
        assert sorted(ids) == sorted([a, b, c, side])

    async def test_moving_a_division_under_its_own_descendant_is_refused(
        self, db: AsyncSession, tenant
    ):
        """The other caller: the parent check walks the same subtree."""
        top = await _make_division(db, tenant.id, "Top")
        mid = await _make_division(db, tenant.id, "Mid", parent_id=top)
        leaf = await _make_division(db, tenant.id, "Leaf", parent_id=mid)
        other = await _make_division(db, tenant.id, "Other")

        with pytest.raises(HTTPException) as exc:
            await company_service.update_division(
                db, tenant.id, top, DivisionUpdate(parent_id=leaf)
            )
        assert exc.value.code == "division_parent_cycle"
        moved = await company_service.update_division(
            db, tenant.id, top, DivisionUpdate(parent_id=other)
        )
        assert moved["parent_id"] == other


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
