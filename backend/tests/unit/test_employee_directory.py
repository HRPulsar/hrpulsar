"""HRP-623: the employee directory — a trimmed card colleagues may open.

HRP-616 closed ``/employees/{id}`` hard, which also closed the only way to
look up a coworker's department or job title. The directory reopens the card
itself in a schema that carries no HR process data, and leaves every
sub-resource behind the original read scope.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from app.config import settings
from app.modules.auth.models import Role
from app.modules.company.models import Tenant
from app.modules.employee.models import Employee
from app.modules.position.models import Position
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

DEMO_EMPLOYEE_COUNT = 40
# HRP-623 REDO: the directory lists active and on-leave people only; the demo
# seed carries one inactive former teammate.
DIRECTORY_COUNT = 39


@pytest.fixture
def enable_demo(monkeypatch, skill_levels):
    """Same configuration knobs as ``test_baseline_role.py``."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "demo_turnstile_secret", "")
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 0)
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 500)
    # The grade-flag test writes the company profile, which is BILLABLE:
    # a zero-credit demo tenant answers 429 credits_demo_quota_exhausted.
    monkeypatch.setattr(settings, "demo_initial_credits", 100)
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
    """Handles for one demo tenant seen through the employee persona."""

    def __init__(self, tenant_id, admin_headers, headers, own_id, other_id):
        self.tenant_id = tenant_id
        self.admin_headers = admin_headers
        self.headers = headers
        self.own_id = own_id
        self.other_id = other_id


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

    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    own_id = await db.scalar(
        select(Employee.id).where(Employee.user_id == me.json()["id"])
    )
    assert own_id is not None, "employee persona has no employee row"

    other_id = await db.scalar(
        select(Employee.id).where(
            Employee.tenant_id == start.json()["tenant_id"],
            Employee.id != own_id,
            Employee.position_id.is_not(None),
        )
    )
    assert other_id is not None
    return DemoPersona(
        start.json()["tenant_id"], admin_headers, headers, own_id, other_id
    )


@pytest.mark.asyncio
async def test_directory_lists_the_whole_company_without_hr_fields(
    client: AsyncClient, persona: DemoPersona
):
    resp = await client.get("/api/employees?limit=100", headers=persona.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == DIRECTORY_COUNT
    assert len(body["items"]) == DIRECTORY_COUNT
    for row in body["items"]:
        for leaked in ("hire_date", "roles", "alert", "user_first_login_at"):
            assert leaked not in row, f"{leaked} leaked into the directory row"
        assert row["status"] in ("active", "on_leave")
    assert {row["status"] for row in body["items"]} == {"active", "on_leave"}
    assert any(row["specialization_title"] for row in body["items"])
    # Own row is part of the same list, in the same trimmed shape.
    assert str(persona.own_id) in {row["id"] for row in body["items"]}


@pytest.mark.asyncio
async def test_own_card_stays_full_and_a_colleague_card_is_trimmed(
    client: AsyncClient, persona: DemoPersona
):
    own = await client.get(f"/api/employees/{persona.own_id}", headers=persona.headers)
    assert own.status_code == 200, own.text
    assert "hire_date" in own.json()
    assert "status" in own.json()

    other = await client.get(
        f"/api/employees/{persona.other_id}", headers=persona.headers
    )
    assert other.status_code == 200, other.text
    assert "hire_date" not in other.json()
    assert "roles" not in other.json()
    assert other.json()["specialization_title"] is not None
    assert other.json()["id"] == str(persona.other_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sub_resource",
    [
        "competences",
        "events",
        "work-experience",
        "education",
        "previous-employment",
        "courses",
        "compensation",
    ],
)
async def test_sub_resources_stay_closed(
    client: AsyncClient, persona: DemoPersona, sub_resource: str
):
    resp = await client.get(
        f"/api/employees/{persona.other_id}/{sub_resource}", headers=persona.headers
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_grade_is_hidden_until_the_tenant_opts_in(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona
):
    other = await client.get(
        f"/api/employees/{persona.other_id}", headers=persona.headers
    )
    assert other.status_code == 200
    assert other.json()["grade_title"] is None

    own = await client.get(f"/api/employees/{persona.own_id}", headers=persona.headers)
    assert own.json()["grade_title"] is not None, "own card lost its grade"

    tenant = await db.get(Tenant, persona.tenant_id)
    tenant.directory_show_grades = True
    await db.commit()

    other = await client.get(
        f"/api/employees/{persona.other_id}", headers=persona.headers
    )
    assert other.json()["grade_title"] is not None


@pytest.mark.asyncio
async def test_only_an_admin_flips_the_grade_flag(
    client: AsyncClient, persona: DemoPersona
):
    denied = await client.put(
        "/api/settings/company-profile",
        json={"directory_show_grades": True},
        headers=persona.headers,
    )
    assert denied.status_code == 403, denied.text

    allowed = await client.put(
        "/api/settings/company-profile",
        json={"directory_show_grades": True},
        headers=persona.admin_headers,
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["directory_show_grades"] is True


@pytest.mark.asyncio
async def test_own_card_by_the_me_alias(client: AsyncClient, persona: DemoPersona):
    """HRP-624: ``/employees/me`` is the same full card, id not required."""
    resp = await client.get("/api/employees/me", headers=persona.headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(persona.own_id)
    assert "hire_date" in resp.json()


@pytest.mark.asyncio
async def test_me_is_a_404_without_an_employee_row(
    client: AsyncClient, db: AsyncSession, tenant, user
):
    """A workspace owner with no ``Employee`` row is an ordinary case."""
    from app.core.security import create_access_token

    token = create_access_token(str(user.id), str(user.tenant_id))
    resp = await client.get(
        "/api/employees/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "employee_profile_not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "role=admin",
        "unassigned_only=true",
        "with_alerts=true",
    ],
)
async def test_hr_filters_do_not_narrow_the_directory(
    client: AsyncClient, persona: DemoPersona, query: str
):
    """HRP-623: a predicate over a hidden field answers what the field would.

    ``?status=terminated`` or ``?role=admin`` over the whole tenant hands
    back exactly the roster the trimmed schema exists to withhold, so the
    directory ignores those filters instead of trimming the columns after
    the fact.
    """
    resp = await client.get(
        f"/api/employees?limit=100&{query}", headers=persona.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == DIRECTORY_COUNT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("status=active", DIRECTORY_COUNT - 1),
        ("status=on_leave", 1),
        ("status=active&status=on_leave", DIRECTORY_COUNT),
        # Never a way around the active / on-leave limit.
        ("status=inactive", 0),
        ("status=terminated", 0),
    ],
)
async def test_directory_status_filter_stays_inside_active_and_on_leave(
    client: AsyncClient, persona: DemoPersona, query: str, expected: int
):
    """HRP-623 REDO: the directory filters by the status it shows."""
    resp = await client.get(
        f"/api/employees?limit=100&{query}", headers=persona.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == expected


@pytest.mark.asyncio
async def test_grade_filter_does_not_walk_around_the_flag(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona
):
    """Filtering by grade would leak the grade the tenant chose to hide."""
    grade_id = await db.scalar(
        select(Position.grade_id).where(
            Position.tenant_id == persona.tenant_id, Position.grade_id.is_not(None)
        )
    )
    assert grade_id is not None

    resp = await client.get(
        f"/api/employees?limit=100&grade_id={grade_id}", headers=persona.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == DIRECTORY_COUNT

    # Admin keeps the filter — it is the directory that drops it, not the API.
    as_admin = await client.get(
        f"/api/employees?limit=100&grade_id={grade_id}", headers=persona.admin_headers
    )
    assert as_admin.status_code == 200, as_admin.text
    assert 0 < as_admin.json()["total"] < DEMO_EMPLOYEE_COUNT


async def _manager_headers(db: AsyncSession, persona: DemoPersona):
    """A seeded division head holding ``manager`` and no admin-level role,
    plus the ids of the subtree that head may read in full."""
    from app.core.access_scope import ADMIN_ROLE_CODES, get_visible_employee_ids
    from app.core.security import create_access_token
    from app.modules.auth.models import User, user_roles
    from app.modules.company.models import Division

    divisions = (
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
    for division in divisions:
        head = await db.get(Employee, division.manager_id)
        codes = set(
            (
                await db.execute(
                    select(Role.code)
                    .join(user_roles, user_roles.c.role_id == Role.id)
                    .where(user_roles.c.user_id == head.user_id)
                )
            )
            .scalars()
            .all()
        )
        if "manager" in codes and not (codes & ADMIN_ROLE_CODES):
            token = create_access_token(str(head.user_id), str(persona.tenant_id))
            user = await db.get(User, head.user_id)
            visible = await get_visible_employee_ids(db, user)
            return {"Authorization": f"Bearer {token}"}, visible
    pytest.fail("demo seed has no division head who is only a manager")


@pytest.mark.asyncio
async def test_manager_lists_the_tenant_in_full_only_inside_the_subtree(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona
):
    """HRP-623 REDO (QA, 05.10): a manager sees every colleague, the managed
    subtree in full and everyone else as the directory row."""
    headers, visible = await _manager_headers(db, persona)
    assert visible and len(visible) < DIRECTORY_COUNT

    # Without the opt-in the list stays the subtree: every people picker
    # (assessments, exams, development) reads this route.
    picker = await client.get("/api/employees?limit=100", headers=headers)
    assert picker.status_code == 200, picker.text
    assert {r["id"] for r in picker.json()["items"]} == {str(i) for i in visible}

    resp = await client.get(
        "/api/employees?limit=100&tenant_wide=true", headers=headers
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["items"]
    assert len(rows) == resp.json()["total"]
    ids = {row["id"] for row in rows}
    # The subtree in full, every status; outside it active / on leave only.
    assert {str(i) for i in visible} <= ids
    assert resp.json()["total"] > len(visible)
    for row in rows:
        if row["id"] in {str(i) for i in visible}:
            assert "hire_date" in row and "roles" in row, row
        else:
            assert "hire_date" not in row and "roles" not in row, row
            assert row["status"] in ("active", "on_leave")

    # An out-of-subtree card is the directory one, like the employee's.
    outsider = next(r["id"] for r in rows if "hire_date" not in r)
    card = await client.get(f"/api/employees/{outsider}", headers=headers)
    assert card.status_code == 200, card.text
    assert "hire_date" not in card.json()


@pytest.mark.asyncio
async def test_manager_sees_people_of_a_division_outside_the_subtree(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona
):
    """HRP-1057: the division page lists a foreign division's people for a
    manager, as directory rows - not "No employees in this division"."""
    headers, visible = await _manager_headers(db, persona)
    result = await db.execute(
        select(Employee.id, Employee.division_id)
        .where(
            Employee.tenant_id == persona.tenant_id,
            Employee.division_id.is_not(None),
            Employee.id.not_in(visible),
            Employee.status == "active",
        )
        .limit(1)
    )
    row = result.first()
    assert row is not None, "demo seed has nobody outside the managed subtree"
    outsider, foreign = row

    base = f"/api/employees?division_id={foreign}&include_sub_divisions=true"
    scoped = await client.get(base, headers=headers)
    assert scoped.status_code == 200, scoped.text
    assert str(outsider) not in {r["id"] for r in scoped.json()["items"]}

    resp = await client.get(f"{base}&tenant_wide=true", headers=headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["items"]
    assert str(outsider) in {r["id"] for r in rows}
    for row in rows:
        if row["id"] not in {str(i) for i in visible}:
            assert "hire_date" not in row and "roles" not in row, row


@pytest.mark.asyncio
async def test_manager_search_by_job_title_reaches_outside_the_subtree(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona
):
    """HRP-1067: the global search asks tenant-wide with ``q`` - an active
    colleague outside the subtree is found by job title as a directory row;
    one who left is neither listed nor counted."""
    headers, visible = await _manager_headers(db, persona)
    outsiders = (
        (
            await db.execute(
                select(Employee)
                .where(
                    Employee.tenant_id == persona.tenant_id,
                    Employee.id.not_in(visible),
                    Employee.status == "active",
                )
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    assert len(outsiders) == 2
    found, gone = outsiders
    for emp in outsiders:
        emp.position_title = "Zeppelin Pilot"
    gone.status = "terminated"
    await db.commit()

    resp = await client.get(
        "/api/employees?q=zeppelin&limit=5&tenant_wide=true", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert [r["id"] for r in resp.json()["items"]] == [str(found.id)]
    assert resp.json()["total"] == 1
    row = resp.json()["items"][0]
    assert "hire_date" not in row and row["position_title"] == "Zeppelin Pilot"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query", ["role=employee", "unassigned_only=true", "issue=assessment_stale"]
)
async def test_manager_hidden_field_filters_stay_inside_the_subtree(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona, query: str
):
    """A filter on a field the directory row hides would answer what the row
    withholds, so it keeps the manager's list inside the subtree."""
    headers, visible = await _manager_headers(db, persona)
    resp = await client.get(
        f"/api/employees?limit=100&tenant_wide=true&{query}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert {row["id"] for row in resp.json()["items"]} <= {str(i) for i in visible}


@pytest.mark.asyncio
async def test_manager_alerts_and_severity_sort_do_not_reach_outside_the_subtree(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona
):
    """Security review, 06.10: neither ``with_alerts`` nor ``sort=severity``
    may filter, order or decorate the rows outside the manager's subtree.
    Severity ordering exists only with an ``issue`` filter, which keeps the
    list inside the subtree; ``with_alerts`` badges the page and the
    directory rows drop them."""
    headers, visible = await _manager_headers(db, persona)
    base = "/api/employees?limit=100&tenant_wide=true"
    plain = await client.get(base, headers=headers)
    probed = await client.get(f"{base}&with_alerts=true&sort=severity", headers=headers)
    assert plain.status_code == probed.status_code == 200, probed.text
    assert [r["id"] for r in probed.json()["items"]] == [
        r["id"] for r in plain.json()["items"]
    ]
    assert probed.json()["total"] == plain.json()["total"]
    for row in probed.json()["items"]:
        if row["id"] not in {str(i) for i in visible}:
            assert "alert" not in row and "issues" not in row, row


@pytest.mark.asyncio
async def test_manager_badges_are_computed_for_the_subtree_only(
    client: AsyncClient, db: AsyncSession, persona: DemoPersona, monkeypatch
):
    """Review 06.10: a directory row drops the badges, so the alert scan
    never runs for one."""
    from app.modules.employee import service as employee_service

    headers, visible = await _manager_headers(db, persona)
    scanned: set = set()
    real = employee_service.compute_employee_alerts_bulk_all

    async def spy(db_, tenant_id, employees):
        scanned.update(e.id for e in employees)
        return await real(db_, tenant_id, employees)

    monkeypatch.setattr(employee_service, "compute_employee_alerts_bulk_all", spy)
    resp = await client.get(
        "/api/employees?limit=100&tenant_wide=true&with_alerts=true", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert scanned and scanned <= set(visible)
