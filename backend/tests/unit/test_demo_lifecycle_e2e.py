"""HRP-255 (D7) — full demo-tenant lifecycle prowl.

End-to-end exercise of the public demo loop, gluing the D1 cleanup task
to the D3 ``POST /api/demo/start`` bootstrap. The existing
``test_demo_lifecycle.py`` only pokes the cleanup task in isolation
with hand-built tenants; here we drive the real entry point, accrue
real seed-loaded children, then expire the tenant and prove cascade
deletes touched everything.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.config import settings
from app.modules.assessment.models import Assessment
from app.modules.auth.models import User
from app.modules.company.models import Tenant
from app.modules.employee.models import Employee
from app.modules.recruitment.models import (
    Candidate,
    CandidateVacancy,
    Interview,
    InterviewAnalysisCache,
    Vacancy,
)
from httpx import AsyncClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def enable_demo(monkeypatch, skill_levels):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "demo_turnstile_secret", "")
    monkeypatch.setattr(settings, "demo_rate_limit_per_ip_per_hour", 0)
    monkeypatch.setattr(settings, "demo_max_concurrent_sessions", 50)
    monkeypatch.setattr(settings, "demo_initial_credits", 0)


@pytest.fixture
def sync_test_engine(db: AsyncSession):
    """Sync engine pointed at the same Postgres ``hrpulsar_test`` DB the
    async fixture writes to. ``purge_expired_demo_tenants`` runs inside
    a Celery worker (no event loop), so the sync engine is the only way
    to hit the same rows from the task."""
    from tests.conftest import TEST_DB_URL

    sync_url = TEST_DB_URL.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    yield engine
    engine.dispose()


@pytest.mark.asyncio
async def test_full_lifecycle_start_activity_purge_cascade(
    client: AsyncClient,
    admin_role,
    enable_demo,
    db: AsyncSession,
    sync_test_engine,
    skill_levels,
    monkeypatch,
):
    """Start → authenticated activity → expire → purge → cascade."""
    import app.modules.demo.tasks as tasks
    from app.modules.demo import activity

    # The activity hook is debounced by Redis (``demo:active:{id}``); the
    # test asserts the SQL UPDATE actually fires, so skip the debounce.
    monkeypatch.setattr(activity, "_redis_client", lambda: None)

    # HRP-276 / H1: touch_demo_tenant_activity now writes through its
    # own dedicated session bound to ``app.database.async_session`` —
    # which uses ``settings.database_url`` (dev DB), not the test DB.
    # Redirect the factory at the test engine so the UPDATE lands in
    # ``hrpulsar_test`` and this lifecycle assertion can see it.
    from sqlalchemy.ext.asyncio import (
        async_sessionmaker as _async_sessionmaker,
    )
    from sqlalchemy.ext.asyncio import (
        create_async_engine as _create_async_engine,
    )

    from tests.conftest import TEST_DB_URL as _TEST_DB_URL

    _activity_engine = _create_async_engine(_TEST_DB_URL)
    _activity_factory = _async_sessionmaker(
        _activity_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(
        activity, "_session_factory", lambda: _activity_factory
    )

    # 1. ── Bootstrap a real demo session via the public endpoint ─────
    resp = await client.post("/api/demo/start", json={})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    tenant_id = uuid.UUID(body["tenant_id"])
    access_token = body["access_token"]

    # The seed loads the canonical fixture: 3 vacancies, 8 candidates,
    # 2 interviews. We use those numbers below to confirm cascade.
    vac_count = (
        await db.execute(
            select(Vacancy).where(Vacancy.tenant_id == tenant_id)
        )
    ).scalars().all()
    cand_count = (
        await db.execute(
            select(Candidate).where(Candidate.tenant_id == tenant_id)
        )
    ).scalars().all()
    iv_count = (
        await db.execute(
            select(Interview).where(Interview.tenant_id == tenant_id)
        )
    ).scalars().all()
    assert len(vac_count) >= 1
    assert len(cand_count) >= 1
    assert len(iv_count) >= 1

    # 2. ── Authenticated GET stamps ``last_active_at`` ──────────────
    # ``last_active_at`` is set to ``now`` at start; back-date it so we
    # can prove the touch actually wrote a fresh value.
    backdated = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.execute(
        update(Tenant)
        .where(Tenant.id == tenant_id)
        .values(last_active_at=backdated)
    )
    await db.commit()

    me_resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_resp.status_code == 200, me_resp.text

    refreshed = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one()
    # The async session is ``expire_on_commit=False``, so the ORM Tenant
    # cached from demo bootstrap still carries the original
    # ``last_active_at`` (≈ test start, well above the 1-hour backdate)
    # — without an explicit refresh the assertion below would be a
    # tautology that survives even if ``touch_demo_tenant_activity`` is
    # removed from ``get_current_user``. Force a round-trip so we read
    # the value the route handler actually wrote.
    await db.refresh(refreshed, attribute_names=["last_active_at"])
    assert refreshed.last_active_at is not None
    assert refreshed.last_active_at > backdated, (
        "Authenticated request should have bumped last_active_at via "
        "touch_demo_tenant_activity (the get_current_user hook from D1)."
    )

    # 3. ── Backdate ``expires_at`` so the next purge will pick it up ─
    expired = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db.execute(
        update(Tenant)
        .where(Tenant.id == tenant_id)
        .values(expires_at=expired)
    )
    await db.commit()

    # 4. ── Run the Celery beat task against the test DB ─────────────
    monkeypatch.setattr(tasks, "_sync_engine", lambda: sync_test_engine)
    summary = tasks.purge_expired_demo_tenants()
    assert summary["deleted"] >= 1, summary

    # 5. ── Verify cascade — drop the identity map so the next SELECT
    #       round-trips to Postgres rather than handing back cached rows ─
    db.expire_all()

    # Tenant itself is gone.
    surviving = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    assert surviving is None

    # Cascade — every tenant-scoped child should be wiped.
    for model in (
        User,
        Employee,
        Vacancy,
        Candidate,
        CandidateVacancy,
        Interview,
        InterviewAnalysisCache,
        Assessment,
    ):
        remaining = (
            await db.execute(
                select(model).where(model.tenant_id == tenant_id)
            )
        ).scalars().all()
        assert remaining == [], (
            f"{model.__name__} rows survived tenant purge: {remaining}"
        )


@pytest.mark.asyncio
async def test_purge_skips_demo_tenant_with_fresh_activity(
    client: AsyncClient,
    admin_role,
    enable_demo,
    db: AsyncSession,
    sync_test_engine,
    skill_levels,
    monkeypatch,
):
    """A live demo session — one that's still inside both its hard TTL
    and its sliding inactivity window — must survive a purge pass.
    Pairs with the cascade test above so a regression that broadens the
    DELETE predicate gets caught immediately."""
    import app.modules.demo.tasks as tasks

    resp = await client.post("/api/demo/start", json={})
    assert resp.status_code == 201
    tenant_id = uuid.UUID(resp.json()["tenant_id"])

    monkeypatch.setattr(tasks, "_sync_engine", lambda: sync_test_engine)
    tasks.purge_expired_demo_tenants()

    db.expire_all()
    survivor = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    assert survivor is not None
    assert survivor.is_demo is True
