"""HRP-633: the position / specialization employee lists are directories too.

Both routes answered the full HR row — hire date, status, grade and the
process alerts — to any authenticated member of the tenant. A rank-and-file
caller could walk ``GET /positions?limit=200`` (a list the employees page
already loads for them) and pull ``?with_alerts=true`` per position to
rebuild exactly the roster ``EmployeeDirectoryRead`` withholds, grade flag
included. A ``manager`` could do the same across the whole company, which
``GET /employees`` has refused them since HRP-616.

The fix trims rows rather than closing routes: the pages that render these
lists stay usable, everyone still finds every colleague, and the boundary is
the one the employee card already uses — ``get_visible_employee_ids``, applied
per row. A caller's own row therefore stays full; a colleague's does not.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from app.config import settings
from app.core.security import create_access_token
from app.modules.auth.models import Role, user_roles
from app.modules.company.models import Division, Tenant
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Fields the directory shape must never carry — the HR process, not the
# company phone book.
HR_FIELDS = ("hire_date", "status", "alert", "specialization_title", "user_id")


def _is_full_row(row: dict) -> bool:
    return "hire_date" in row


@pytest.fixture
def enable_demo(monkeypatch, skill_levels):
    # `skill_levels` is a seed prerequisite, not something this file reads:
    # the demo seed builds competence matrices and fails without it.
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "demo_turnstile_secret", "")
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 0)
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 500)
    monkeypatch.setattr(settings, "demo_trusted_proxies", "127.0.0.0/8")


async def _system_role(db: AsyncSession, code: str, name: str) -> Role:
    result = await db.execute(
        select(Role).where(Role.code == code, Role.is_system.is_(True))
    )
    role = result.scalars().first()
    if not role:
        role = Role(name=name, code=code, is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


@pytest_asyncio.fixture
async def employee_role(db: AsyncSession) -> Role:
    return await _system_role(db, "employee", "Employee")


@pytest_asyncio.fixture
async def manager_role(db: AsyncSession) -> Role:
    return await _system_role(db, "manager", "Manager")


class DemoPersona:
    def __init__(self, tenant_id, admin_headers, headers, own_id, position_id, spec_id):
        self.tenant_id = tenant_id
        self.admin_headers = admin_headers
        self.headers = headers
        self.own_id = own_id
        self.position_id = position_id
        self.spec_id = spec_id


@pytest_asyncio.fixture
async def persona(
    client: AsyncClient,
    db: AsyncSession,
    admin_role,
    employee_role,
    manager_role,
    enable_demo,
) -> DemoPersona:
    start = await client.post("/api/demo/start", json={})
    assert start.status_code == 201, start.text
    admin_headers = {"Authorization": f"Bearer {start.json()['access_token']}"}

    switched = await client.post(
        "/api/demo/switch-view", json={"persona": "employee"}, headers=admin_headers
    )
    assert switched.status_code == 200, switched.text
    headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}

    tenant_id = start.json()["tenant_id"]
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    own_id = await db.scalar(
        select(Employee.id).where(Employee.user_id == me.json()["id"])
    )
    assert own_id is not None, "employee persona has no employee row"

    # The persona's OWN position, so every run exercises both halves of the
    # boundary — their own row full, their colleagues' trimmed. Picking any
    # qualifying position instead would be a coin flip: `Position.id` is a
    # random uuid4, so ordering by it orders nothing, and the persona lands
    # on the pick roughly one run in six.
    own = await db.get(Employee, own_id)
    position = await db.get(Position, own.position_id)
    assert position is not None, "employee persona holds no position"
    assert position.specialization_id and position.grade_id, (
        "the persona's position lost its specialization or grade — the grade "
        "assertions below would be vacuous"
    )
    colleagues = await db.scalar(
        select(func.count(Employee.id)).where(
            Employee.position_id == position.id, Employee.id != own_id
        )
    )
    assert colleagues, "the persona is alone on their position — nothing to trim"
    row = (position.id, position.specialization_id)
    return DemoPersona(tenant_id, admin_headers, headers, own_id, row[0], row[1])


def _routes(persona: DemoPersona) -> dict[str, str]:
    return {
        "position": f"/api/positions/{persona.position_id}/employees",
        "specialization": f"/api/specializations/{persona.spec_id}/employees",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["position", "specialization"])
async def test_colleague_rows_are_trimmed_and_the_own_row_is_not(
    client: AsyncClient, persona: DemoPersona, route: str
):
    resp = await client.get(
        f"{_routes(persona)[route]}?with_alerts=true", headers=persona.headers
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows, f"{route} list came back empty — the assertions below are vacuous"
    trimmed = 0
    for row in rows:
        if row["id"] == str(persona.own_id):
            # Own card in full is the HRP-623 rule, not a leak.
            assert _is_full_row(row)
            continue
        trimmed += 1
        for leaked in HR_FIELDS:
            assert leaked not in row, f"{leaked} leaked into the {route} row"
        # What a directory is for still arrives.
        assert "user_name" in row
        assert "division_name" in row
    assert trimmed, "no colleague row in the list — nothing was actually checked"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["position", "specialization"])
async def test_admin_rows_are_untouched(
    client: AsyncClient, persona: DemoPersona, route: str
):
    resp = await client.get(
        f"{_routes(persona)[route]}?with_alerts=true", headers=persona.admin_headers
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows
    for field in HR_FIELDS:
        assert field in rows[0], (
            f"{field} disappeared from the {route} row for an admin"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["position", "specialization"])
async def test_grade_follows_the_tenant_flag(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona, route: str
):
    """The flag HRP-623 introduced was decorative while these routes were open.

    (It only closes the *directory's* copy of the grade — the positions
    catalogue still publishes a position's grade to everyone. That is a
    wider hole than this ticket: HRP-637.)
    """
    url = _routes(persona)[route]

    def colleagues(payload):
        return [r for r in payload if r["id"] != str(persona.own_id)]

    hidden = await client.get(url, headers=persona.headers)
    assert hidden.status_code == 200, hidden.text
    assert all(row["grade_title"] is None for row in colleagues(hidden.json()))

    tenant = await db.get(Tenant, persona.tenant_id)
    tenant.directory_show_grades = True
    await db.commit()

    shown = await client.get(url, headers=persona.headers)
    assert shown.status_code == 200, shown.text
    assert any(row["grade_title"] is not None for row in colleagues(shown.json()))


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["position", "specialization"])
async def test_hire_date_does_not_survive_as_the_sort_order(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona, route: str
):
    """Ordering by hire date hands the seniority ranking to a trimmed caller.

    The employee directory orders by ``created_at``; these two used to order
    by ``hire_date`` whoever was asking, so the field stayed readable off the
    row order. The seeded dates are moved apart first — with three people on
    a position the two orderings can otherwise coincide by chance and the
    assertion would prove nothing.
    """
    url = _routes(persona)[route]
    admin = await client.get(url, headers=persona.admin_headers)
    assert admin.status_code == 200, admin.text
    rows = admin.json()
    if len(rows) < 2:
        pytest.skip("a single-row list has no order to leak")

    before = [r["id"] for r in (await client.get(url, headers=persona.headers)).json()]

    # Send the first-listed person to the back of the hire-date order without
    # touching anything else the ordering could key on.
    oldest = min(date.fromisoformat(r["hire_date"]) for r in rows)
    emp = await db.get(Employee, uuid.UUID(rows[0]["id"]))
    emp.hire_date = oldest - timedelta(days=1)
    await db.commit()

    moved = await client.get(url, headers=persona.admin_headers)
    assert moved.json()[-1]["id"] == rows[0]["id"], (
        "the admin list is no longer ordered by hire date — rewrite this test"
    )

    after = [r["id"] for r in (await client.get(url, headers=persona.headers)).json()]
    # Comparing the trimmed list against itself, not against the admin's:
    # on a short list the two orderings can agree by chance, but an order
    # that moves when only a hidden field moves is keyed on that field.
    assert after == before, "the trimmed list order still follows hire_date"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["position", "specialization"])
async def test_alerts_are_not_computed_for_rows_that_will_not_carry_them(
    monkeypatch, client: AsyncClient, persona: DemoPersona, route: str
):
    """``with_alerts=true`` must not merely be stripped from the response.

    Dropping the field after the fact still runs the assessment / PDP
    queries the alerts are built from, which is work done purely to throw
    away — and one refactor away from shipping it again.
    """
    import app.modules.employee.alerts as alerts_module

    seen: list[list[uuid.UUID]] = []
    original = alerts_module.compute_employee_alerts_bulk

    async def _spy(db, tenant_id, employees, *args, **kwargs):
        seen.append([e.id for e in employees])
        return await original(db, tenant_id, employees, *args, **kwargs)

    monkeypatch.setattr(alerts_module, "compute_employee_alerts_bulk", _spy)
    monkeypatch.setattr(
        "app.modules.position.service.compute_employee_alerts_bulk", _spy
    )

    resp = await client.get(
        f"{_routes(persona)[route]}?with_alerts=true", headers=persona.headers
    )
    assert resp.status_code == 200, resp.text
    assert seen == [[persona.own_id]], (
        f"alerts must be computed once, for the caller's own row only — got {seen}"
    )


@pytest.mark.asyncio
async def test_a_manager_reads_hr_rows_only_inside_their_subtree(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona
):
    """The leak scenario from the ticket, one role up.

    ``GET /employees`` has narrowed a manager to their own subtree since
    HRP-616; walking every position was the way around it.
    """
    from app.core.access_scope import ADMIN_ROLE_CODES, get_managed_division_ids

    # A head who is *only* a manager. The demo seed hands the People &
    # Talent head the `hr` role on top of `manager`, and `hr` is an admin
    # code — that actor reads everything by design and would invert every
    # assertion below into a pass.
    heads = (
        (
            await db.execute(
                select(Division).where(
                    Division.tenant_id == persona.tenant_id,
                    Division.manager_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    head = None
    for division in heads:
        candidate = await db.get(Employee, division.manager_id)
        if candidate is None or candidate.user_id is None:
            continue
        codes = {
            r.code
            for r in (
                await db.execute(
                    select(Role)
                    .join(user_roles, user_roles.c.role_id == Role.id)
                    .where(user_roles.c.user_id == candidate.user_id)
                )
            )
            .scalars()
            .all()
        }
        if "manager" in codes and not (codes & ADMIN_ROLE_CODES):
            head = candidate
            break
    assert head is not None, "demo seed has no division head who is only a manager"

    managed = await get_managed_division_ids(db, persona.tenant_id, head.id)
    visible = set(
        (
            await db.execute(
                select(Employee.id).where(
                    Employee.tenant_id == persona.tenant_id,
                    Employee.division_id.in_(managed),
                )
            )
        )
        .scalars()
        .all()
    ) | {head.id}

    token = create_access_token(str(head.user_id), str(persona.tenant_id))
    headers = {"Authorization": f"Bearer {token}"}

    full_outside = 0
    trimmed = 0
    for collection in ("positions", "specializations"):
        listing = await client.get(f"/api/{collection}?limit=200", headers=headers)
        assert listing.status_code == 200, listing.text
        body = listing.json()
        ids = [x["id"] for x in (body["items"] if isinstance(body, dict) else body)]
        assert ids, f"no {collection} to walk"
        for entity_id in ids:
            resp = await client.get(
                f"/api/{collection}/{entity_id}/employees?with_alerts=true",
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            for row in resp.json():
                if _is_full_row(row):
                    if uuid.UUID(row["id"]) not in visible:
                        full_outside += 1
                else:
                    trimmed += 1

    assert full_outside == 0, f"{full_outside} HR rows outside the managed subtree"
    assert trimmed, "no row was trimmed — the walk proved nothing"
