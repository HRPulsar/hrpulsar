"""HRP-616: reads under /employees/{id} respect the caller's scope.

Every GET on a colleague's card used to be gated by bare authentication:
a rank-and-file employee could pull anyone's competences, events,
education and employment history by URL alone. The router now runs the
same scope assert the write paths have always had.

HRP-623 reopened the card *itself* to the whole tenant in the trimmed
directory schema; the sub-resources below stay behind the assert, which is
what this file pins.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest_asyncio
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import Role, User, user_roles
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# Sub-resources that must never leak across the scope boundary.
SUB_SUFFIXES = (
    "/events",
    "/competences",
    "/competence-overview",
    "/work-experience",
    "/previous-employment",
    "/education",
    "/courses",
)

# The card itself plus everything under it — used where the caller is
# inside the read scope and the whole set must answer 200.
CARD_SUFFIXES = ("", *SUB_SUFFIXES)


async def _role(db: AsyncSession, code: str) -> Role:
    result = await db.execute(select(Role).where(Role.code == code))
    role = result.scalars().first()
    if role is None:
        role = Role(name=code.title(), code=code, is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


async def _user(db: AsyncSession, tenant, code: str) -> User:
    role = await _role(db, code)
    u = User(
        email=f"{code}-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name=code,
        last_name="X",
        tenant_id=tenant.id,
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


async def _employee(db: AsyncSession, tenant, user, division=None) -> Employee:
    emp = Employee(
        user_id=user.id,
        tenant_id=tenant.id,
        hire_date=date(2024, 1, 1),
        division_id=division.id if division else None,
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


def _headers(u: User) -> dict[str, str]:
    token = create_access_token(str(u.id), str(u.tenant_id))
    return {"Authorization": f"Bearer {token}"}


async def _statuses(
    client: AsyncClient, headers, employee_id, suffixes=CARD_SUFFIXES
) -> dict[str, int]:
    out = {}
    for suffix in suffixes:
        resp = await client.get(
            f"/api/employees/{employee_id}{suffix}", headers=headers
        )
        out[suffix or "/"] = resp.status_code
    return out


@pytest_asyncio.fixture
async def cast(db: AsyncSession, tenant):
    """Two unrelated employees plus a manager over only one of them."""
    worker_user = await _user(db, tenant, "employee")
    stranger_user = await _user(db, tenant, "employee")
    manager_user = await _user(db, tenant, "manager")

    manager_emp = await _employee(db, tenant, manager_user)
    division = Division(
        tenant_id=tenant.id,
        name=f"Eng {uuid.uuid4().hex[:4]}",
        manager_id=manager_emp.id,
    )
    db.add(division)
    await db.commit()
    await db.refresh(division)

    worker_emp = await _employee(db, tenant, worker_user, division)
    stranger_emp = await _employee(db, tenant, stranger_user)
    return {
        "worker_user": worker_user,
        "worker_emp": worker_emp,
        "stranger_emp": stranger_emp,
        "manager_user": manager_user,
        "manager_emp": manager_emp,
    }


class TestEmployeeReadScope:
    async def test_employee_reads_own_card(self, client: AsyncClient, cast):
        statuses = await _statuses(
            client, _headers(cast["worker_user"]), cast["worker_emp"].id
        )
        assert all(code == 200 for code in statuses.values()), statuses

    async def test_employee_gets_a_colleague_card_but_nothing_under_it(
        self, client: AsyncClient, cast
    ):
        """HRP-623: the directory card is open, the HR record is not."""
        card = await client.get(
            f"/api/employees/{cast['stranger_emp'].id}",
            headers=_headers(cast["worker_user"]),
        )
        assert card.status_code == 200, card.text
        assert "hire_date" not in card.json()

        statuses = await _statuses(
            client,
            _headers(cast["worker_user"]),
            cast["stranger_emp"].id,
            SUB_SUFFIXES,
        )
        assert all(code == 403 for code in statuses.values()), statuses

    async def test_manager_reads_own_subtree(self, client: AsyncClient, cast):
        statuses = await _statuses(
            client, _headers(cast["manager_user"]), cast["worker_emp"].id
        )
        assert all(code == 200 for code in statuses.values()), statuses

    async def test_manager_refused_outside_the_subtree(self, client: AsyncClient, cast):
        """A manager outside their subtree is a colleague, nothing more.

        HRP-623 hands them the same trimmed card as anyone else rather than
        the full record their own subtree returns.
        """
        card = await client.get(
            f"/api/employees/{cast['stranger_emp'].id}",
            headers=_headers(cast["manager_user"]),
        )
        assert card.status_code == 200, card.text
        assert "hire_date" not in card.json()

        statuses = await _statuses(
            client,
            _headers(cast["manager_user"]),
            cast["stranger_emp"].id,
            SUB_SUFFIXES,
        )
        assert all(code == 403 for code in statuses.values()), statuses

    async def test_admin_reads_everyone(self, client: AsyncClient, user, cast):
        statuses = await _statuses(client, _headers(user), cast["stranger_emp"].id)
        assert all(code == 200 for code in statuses.values()), statuses

    async def test_manager_reads_own_card(self, client: AsyncClient, cast):
        statuses = await _statuses(
            client, _headers(cast["manager_user"]), cast["manager_emp"].id
        )
        assert all(code == 200 for code in statuses.values()), statuses

    async def test_user_without_an_employee_row_sees_no_hr_record(
        self, db: AsyncSession, client: AsyncClient, tenant, cast
    ):
        """A recruiter invited without a division has no Employee row.

        ``get_visible_employee_ids`` answers with an empty set for them, so
        no HR record opens — they still get the directory card everyone in
        the tenant gets.
        """
        rootless = await _user(db, tenant, "recruiter")
        card = await client.get(
            f"/api/employees/{cast['worker_emp'].id}", headers=_headers(rootless)
        )
        assert card.status_code == 200, card.text
        assert "hire_date" not in card.json()

        statuses = await _statuses(
            client, _headers(rootless), cast["worker_emp"].id, SUB_SUFFIXES
        )
        assert all(code == 403 for code in statuses.values()), statuses

    async def test_unknown_employee_is_a_404(self, client: AsyncClient, cast):
        """Out-of-tenant and non-existent ids answer the same 404.

        Nothing is disclosed by that: every employee of the caller's own
        tenant is in the directory anyway.
        """
        resp = await client.get(
            f"/api/employees/{uuid.uuid4()}", headers=_headers(cast["worker_user"])
        )
        assert resp.status_code == 404
