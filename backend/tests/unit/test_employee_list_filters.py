"""EMP4: GET /employees multi-select filters.

Covers:
- Array params for division_id, status, position_id, specialization_id, grade_id.
- Specialization/grade filtering through Position (not SpecializationDivision).
- Manager scope intersected with division filter.
- AND-semantics across multiple filters.
- Pagination preserved.
"""

import uuid
from datetime import date, datetime, timezone

import pytest_asyncio
from app.core.security import hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division
from app.modules.dictionary.models import DictionaryItem
from app.modules.employee import service
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


@pytest_asyncio.fixture
async def manager_role(db: AsyncSession):
    result = await db.execute(
        select(Role).where(Role.code == "manager", Role.is_system.is_(True))
    )
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(name="Manager", code="manager", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


async def _mk_user(db: AsyncSession, tenant_id: uuid.UUID, role: Role | None) -> User:
    u = User(
        email=f"u-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name="U",
        last_name=str(uuid.uuid4().hex[:4]),
        tenant_id=tenant_id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    if role is not None:
        await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
        await db.commit()
    db.expunge(u)
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == u.id)
    )
    return result.scalar_one()


async def _mk_dict(
    db: AsyncSession, tenant_id: uuid.UUID, type_: str, title: str
) -> DictionaryItem:
    item = DictionaryItem(type=type_, title=title, tenant_id=tenant_id)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _mk_position(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    title: str,
    specialization_id: uuid.UUID | None = None,
    grade_id: uuid.UUID | None = None,
) -> Position:
    pos = Position(
        tenant_id=tenant_id,
        title=title,
        specialization_id=specialization_id,
        grade_id=grade_id,
        source="manual",
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


async def _mk_employee(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    division_id: uuid.UUID | None = None,
    position_id: uuid.UUID | None = None,
    position_title: str | None = None,
    status: str = "active",
) -> Employee:
    user = await _mk_user(db, tenant_id, role=None)
    emp = Employee(
        tenant_id=tenant_id,
        user_id=user.id,
        division_id=division_id,
        position_id=position_id,
        position_title=position_title,
        hire_date=date(2024, 1, 1),
        status=status,
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


@pytest_asyncio.fixture
async def filter_dataset(db: AsyncSession, tenant):
    """Build a small dataset for combinatorial filter checks."""
    div_a = Division(name="Engineering", tenant_id=tenant.id)
    div_b = Division(name="Sales", tenant_id=tenant.id)
    div_c = Division(name="Marketing", tenant_id=tenant.id)
    db.add_all([div_a, div_b, div_c])
    await db.commit()
    for d in (div_a, div_b, div_c):
        await db.refresh(d)

    spec_fe = await _mk_dict(db, tenant.id, "specialization", "Frontend")
    spec_be = await _mk_dict(db, tenant.id, "specialization", "Backend")
    grade_jr = await _mk_dict(db, tenant.id, "grade", "Junior")
    grade_sr = await _mk_dict(db, tenant.id, "grade", "Senior")

    pos_fe_jr = await _mk_position(
        db,
        tenant.id,
        title="FE Junior",
        specialization_id=spec_fe.id,
        grade_id=grade_jr.id,
    )
    pos_fe_sr = await _mk_position(
        db,
        tenant.id,
        title="FE Senior",
        specialization_id=spec_fe.id,
        grade_id=grade_sr.id,
    )
    pos_be_sr = await _mk_position(
        db,
        tenant.id,
        title="BE Senior",
        specialization_id=spec_be.id,
        grade_id=grade_sr.id,
    )

    e1 = await _mk_employee(
        db,
        tenant.id,
        division_id=div_a.id,
        position_id=pos_fe_jr.id,
        position_title=pos_fe_jr.title,
        status="active",
    )
    e2 = await _mk_employee(
        db,
        tenant.id,
        division_id=div_a.id,
        position_id=pos_fe_sr.id,
        position_title=pos_fe_sr.title,
        status="active",
    )
    e3 = await _mk_employee(
        db,
        tenant.id,
        division_id=div_b.id,
        position_id=pos_be_sr.id,
        position_title=pos_be_sr.title,
        status="terminated",
    )
    e4 = await _mk_employee(
        db,
        tenant.id,
        division_id=div_c.id,
        position_id=None,
        position_title=None,
        status="inactive",
    )

    return {
        "divisions": {"a": div_a, "b": div_b, "c": div_c},
        "specs": {"fe": spec_fe, "be": spec_be},
        "grades": {"jr": grade_jr, "sr": grade_sr},
        "positions": {"fe_jr": pos_fe_jr, "fe_sr": pos_fe_sr, "be_sr": pos_be_sr},
        "employees": {"e1": e1, "e2": e2, "e3": e3, "e4": e4},
    }


class TestListEmployeesMultiFilters:
    async def test_multi_division_filter(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        ds = filter_dataset
        items, total = await service.list_employees(
            db,
            tenant.id,
            division_id=[ds["divisions"]["a"].id, ds["divisions"]["b"].id],
        )
        ids = {e["id"] for e in items}
        assert ds["employees"]["e1"].id in ids
        assert ds["employees"]["e2"].id in ids
        assert ds["employees"]["e3"].id in ids
        assert ds["employees"]["e4"].id not in ids
        assert total == 3

    async def test_multi_status_filter(self, db: AsyncSession, tenant, filter_dataset):
        items, total = await service.list_employees(
            db, tenant.id, status_filter=["active", "terminated"]
        )
        statuses = {e["status"] for e in items}
        assert statuses == {"active", "terminated"}
        assert total == 3

    async def test_grade_filter_via_position(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        ds = filter_dataset
        items, total = await service.list_employees(
            db, tenant.id, grade_id=[ds["grades"]["sr"].id]
        )
        ids = {e["id"] for e in items}
        assert ids == {ds["employees"]["e2"].id, ds["employees"]["e3"].id}
        assert total == 2

    async def test_specialization_filter_via_position(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        ds = filter_dataset
        items, total = await service.list_employees(
            db, tenant.id, specialization_id=[ds["specs"]["fe"].id]
        )
        ids = {e["id"] for e in items}
        assert ids == {ds["employees"]["e1"].id, ds["employees"]["e2"].id}
        assert total == 2

    async def test_combined_and_semantics(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        ds = filter_dataset
        items, total = await service.list_employees(
            db,
            tenant.id,
            status_filter=["active"],
            grade_id=[ds["grades"]["sr"].id],
            division_id=[ds["divisions"]["a"].id],
        )
        ids = {e["id"] for e in items}
        assert ids == {ds["employees"]["e2"].id}
        assert total == 1

    async def test_manager_scope_intersection_empty(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        ds = filter_dataset
        # Manager who only sees employee e1 (division A) tries to filter by division B.
        items, total = await service.list_employees(
            db,
            tenant.id,
            division_id=[ds["divisions"]["b"].id],
            visible_employee_ids={ds["employees"]["e1"].id},
        )
        assert items == []
        assert total == 0

    async def test_pagination_preserved(self, db: AsyncSession, tenant, filter_dataset):
        items_p1, total = await service.list_employees(
            db,
            tenant.id,
            skip=0,
            limit=2,
            status_filter=["active", "terminated", "inactive"],
        )
        assert total == 4
        assert len(items_p1) == 2
        items_p2, _ = await service.list_employees(
            db,
            tenant.id,
            skip=2,
            limit=2,
            status_filter=["active", "terminated", "inactive"],
        )
        assert len(items_p2) == 2
        ids = {e["id"] for e in items_p1} | {e["id"] for e in items_p2}
        assert len(ids) == 4

    async def test_empty_filter_lists_returns_all(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        items_empty, total_empty = await service.list_employees(
            db, tenant.id, division_id=[], status_filter=[]
        )
        items_none, total_none = await service.list_employees(db, tenant.id)
        assert total_empty == total_none == 4
        assert {e["id"] for e in items_empty} == {e["id"] for e in items_none}

    async def test_scalar_backward_compat(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        """Service still accepts a single UUID/str (helps internal callers)."""
        ds = filter_dataset
        items, total = await service.list_employees(
            db,
            tenant.id,
            division_id=ds["divisions"]["a"].id,
            status_filter="active",
        )
        ids = {e["id"] for e in items}
        assert ids == {ds["employees"]["e1"].id, ds["employees"]["e2"].id}
        assert total == 2


class TestListEmployeesSearch:
    """HRP-120: server-side `q` search must find employees across all pages."""

    async def test_q_matches_first_name(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        ds = filter_dataset
        target = ds["employees"]["e1"]
        # Refresh to load relationships consistently
        await db.refresh(target, ["user"])
        needle = target.user.first_name
        items, total = await service.list_employees(db, tenant.id, q=needle)
        ids = {e["id"] for e in items}
        assert target.id in ids
        assert total >= 1

    async def test_q_matches_last_name_case_insensitive(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        ds = filter_dataset
        target = ds["employees"]["e2"]
        await db.refresh(target, ["user"])
        items, _ = await service.list_employees(
            db, tenant.id, q=target.user.last_name.upper()
        )
        assert target.id in {e["id"] for e in items}

    async def test_q_matches_full_name(self, db: AsyncSession, tenant, filter_dataset):
        ds = filter_dataset
        target = ds["employees"]["e3"]
        await db.refresh(target, ["user"])
        full = f"{target.user.first_name} {target.user.last_name}"
        items, _ = await service.list_employees(db, tenant.id, q=full)
        assert target.id in {e["id"] for e in items}

    async def test_q_matches_email_fragment(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        ds = filter_dataset
        target = ds["employees"]["e4"]
        await db.refresh(target, ["user"])
        # Take a unique slice from the auto-generated email
        fragment = target.user.email.split("@")[0]
        items, _ = await service.list_employees(db, tenant.id, q=fragment)
        assert target.id in {e["id"] for e in items}

    async def test_q_no_match_returns_empty(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        items, total = await service.list_employees(
            db, tenant.id, q="definitely-not-a-real-name-zzz"
        )
        assert items == []
        assert total == 0

    async def test_q_works_across_pages(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        """The bug fix: a match on page 2 must be returned even when limit=1."""
        ds = filter_dataset
        target = ds["employees"]["e3"]
        await db.refresh(target, ["user"])
        items, total = await service.list_employees(
            db,
            tenant.id,
            skip=0,
            limit=1,
            q=target.user.last_name,
        )
        assert total == 1
        assert items[0]["id"] == target.id

    async def test_q_combines_with_other_filters(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        """q AND status — search restricted by status filter."""
        ds = filter_dataset
        target = ds["employees"]["e2"]  # active
        await db.refresh(target, ["user"])
        items, _ = await service.list_employees(
            db,
            tenant.id,
            q=target.user.first_name,
            status_filter=["terminated"],
        )
        # e2 is active, so the terminated filter must exclude it.
        assert target.id not in {e["id"] for e in items}

    async def test_q_empty_string_returns_all(
        self, db: AsyncSession, tenant, filter_dataset
    ):
        items_empty, total_empty = await service.list_employees(db, tenant.id, q="")
        items_ws, _ = await service.list_employees(db, tenant.id, q="   ")
        items_none, total_none = await service.list_employees(db, tenant.id)
        assert total_empty == total_none == 4
        assert {e["id"] for e in items_empty} == {e["id"] for e in items_none}
        assert {e["id"] for e in items_ws} == {e["id"] for e in items_none}
