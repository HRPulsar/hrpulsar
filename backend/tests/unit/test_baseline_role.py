"""HRP-619: every account holds at least the baseline ``employee`` role.

Nothing on the creation paths guaranteed it, and the demo seed granted no
roles at all — the demo's own employee persona came back with
``roles == []``, which made every role-gated surface behave as if the
account were broken. The demo seed is the densest user-creation path in
the product, so it doubles as the guard for the invariant.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from app.config import settings
from app.modules.auth.models import Role, User, user_roles
from app.modules.auth.roles import ensure_baseline_employee_role_sync
from app.modules.company.models import Division
from app.modules.employee.models import Employee
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def enable_demo(monkeypatch, skill_levels):
    """Same configuration knobs as ``test_demo_switch_view.py``."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "demo_turnstile_secret", "")
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 0)
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 500)
    monkeypatch.setattr(settings, "demo_initial_credits", 0)
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


@pytest_asyncio.fixture
async def rbac_roles(db: AsyncSession) -> list[Role]:
    """The roles migrations seed on a real install.

    The test schema is built from the model metadata, so nothing seeds
    them here — and ``grant_role`` is a deliberate no-op for a role the
    installation does not have.
    """
    return [
        await _system_role(db, "hr", "HR"),
        await _system_role(db, "recruiter", "Recruiter"),
        await _system_role(db, "hiring_manager", "Hiring Manager"),
    ]


async def _role_codes_by_user(db: AsyncSession, tenant_id) -> dict[str, set[str]]:
    rows = await db.execute(
        select(User.id, Role.code)
        .select_from(User)
        .outerjoin(user_roles, user_roles.c.user_id == User.id)
        .outerjoin(Role, Role.id == user_roles.c.role_id)
        .where(User.tenant_id == tenant_id)
    )
    codes: dict[str, set[str]] = {}
    for user_id, code in rows.all():
        codes.setdefault(str(user_id), set())
        if code:
            codes[str(user_id)].add(code)
    return codes


@pytest.mark.asyncio
async def test_demo_seed_leaves_no_user_without_a_role(
    client: AsyncClient,
    db: AsyncSession,
    admin_role,
    employee_role,
    manager_role,
    enable_demo,
):
    start = await client.post("/api/demo/start", json={})
    assert start.status_code == 201, start.text
    tenant_id = start.json()["tenant_id"]

    codes = await _role_codes_by_user(db, tenant_id)
    assert codes, "demo tenant has no users"
    assert all(codes.values()), f"users without any role: {
        [uid for uid, c in codes.items() if not c]
    }"


@pytest.mark.asyncio
async def test_demo_division_heads_hold_the_manager_role(
    client: AsyncClient,
    db: AsyncSession,
    admin_role,
    employee_role,
    manager_role,
    enable_demo,
):
    start = await client.post("/api/demo/start", json={})
    assert start.status_code == 201, start.text
    tenant_id = start.json()["tenant_id"]

    head_user_ids = (
        (
            await db.execute(
                select(Employee.user_id)
                .join(Division, Division.manager_id == Employee.id)
                .where(Division.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert head_user_ids, "demo tenant has no division heads"

    codes = await _role_codes_by_user(db, tenant_id)
    for user_id in head_user_ids:
        assert (
            "manager" in codes[str(user_id)]
        ), f"division head {user_id} is not a manager"


@pytest.mark.asyncio
async def test_employee_persona_reports_the_employee_role(
    client: AsyncClient,
    db: AsyncSession,
    admin_role,
    employee_role,
    manager_role,
    enable_demo,
):
    start = await client.post("/api/demo/start", json={})
    assert start.status_code == 201, start.text
    switched = await client.post(
        "/api/demo/switch-view",
        json={"persona": "employee"},
        headers={"Authorization": f"Bearer {start.json()['access_token']}"},
    )
    assert switched.status_code == 200, switched.text

    me = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {switched.json()['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["roles"] == ["employee"]


@pytest.mark.asyncio
async def test_demo_seed_covers_the_whole_role_model(
    client: AsyncClient,
    db: AsyncSession,
    admin_role,
    employee_role,
    manager_role,
    rbac_roles,
    enable_demo,
):
    """The demo used to show two roles, so the Role column read as noise.

    People partners are HR, the recruiters are recruiters, and the backend
    engineering manager owns the seeded vacancies — the seed hands out the
    role model the product ships with.
    """
    start = await client.post("/api/demo/start", json={})
    assert start.status_code == 201, start.text
    tenant_id = start.json()["tenant_id"]

    codes = await _role_codes_by_user(db, tenant_id)
    seen = set().union(*codes.values())
    for expected in ("employee", "manager", "hr", "recruiter", "hiring_manager"):
        assert expected in seen, f"no demo user holds {expected}: {sorted(seen)}"


@pytest.mark.asyncio
async def test_employee_import_grants_the_baseline_role(
    db: AsyncSession, tenant, employee_role
):
    """The bulk import is where the role-less accounts on live tenants came
    from — it created a User row and never touched ``user_roles``. The live
    import runs in a Celery task on a plain sync session, so the guard sits
    on the sync helper that task calls."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from tests.conftest import TEST_DB_URL

    email = f"imported-{uuid.uuid4().hex[:6]}@test.com"
    engine = create_engine(TEST_DB_URL.replace("+asyncpg", "+psycopg2"))
    try:
        with Session(engine) as sync_db:
            user = User(
                email=email,
                password_hash="x",
                first_name="Imported",
                last_name="User",
                tenant_id=tenant.id,
            )
            sync_db.add(user)
            sync_db.flush()
            assert ensure_baseline_employee_role_sync(sync_db, user.id) is True
            # Idempotent: a re-import of the same row must not duplicate.
            assert ensure_baseline_employee_role_sync(sync_db, user.id) is False
            sync_db.commit()
            user_id = user.id
    finally:
        engine.dispose()

    codes = await _role_codes_by_user(db, tenant.id)
    assert codes[str(user_id)] == {"employee"}
