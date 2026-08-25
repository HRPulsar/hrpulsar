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
    assert body["total"] == DEMO_EMPLOYEE_COUNT
    assert len(body["items"]) == DEMO_EMPLOYEE_COUNT
    for row in body["items"]:
        for leaked in ("hire_date", "status", "roles", "alert", "user_first_login_at"):
            assert leaked not in row, f"{leaked} leaked into the directory row"
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
    assert "status" not in other.json()
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
        "status=terminated",
        "status=active",
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
    assert resp.json()["total"] == DEMO_EMPLOYEE_COUNT


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
    assert resp.json()["total"] == DEMO_EMPLOYEE_COUNT

    # Admin keeps the filter — it is the directory that drops it, not the API.
    as_admin = await client.get(
        f"/api/employees?limit=100&grade_id={grade_id}", headers=persona.admin_headers
    )
    assert as_admin.status_code == 200, as_admin.text
    assert 0 < as_admin.json()["total"] < DEMO_EMPLOYEE_COUNT
