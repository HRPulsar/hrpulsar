import os
import uuid

# Disable Sentry in tests — must be set before app.main import triggers init_sentry()
os.environ["SENTRY_DSN"] = ""
# Force onprem mode so billing wrappers don't activate (avoids FK issues with mock user IDs)
os.environ["DEPLOYMENT_MODE"] = "onprem"
# HRP-391: DEMO_ENABLED=true is rejected outside SaaS at Settings() time.
# The suite runs onprem (above) regardless of the operator's .env, so pin
# the flag off too — demo tests opt in via monkeypatch on settings.
os.environ["DEMO_ENABLED"] = "false"

import pytest
import pytest_asyncio
from app.config import settings

# app.main:register_core_extensions() subscribes the notification handlers to
# the in-process event bus at import time (this wiring used to live in the app
# lifespan, which ASGITransport never runs, so historically the suite ran with
# these handlers unsubscribed). The handlers open their own
# ``app.database.async_session()`` — the dev database, not hrpulsar_test — so
# leaving them subscribed would let every event published by the suite reach
# the dev DB. Strip exactly those subscriptions; dedicated suites
# (test_recruitment_notifications) re-register handlers against a patched
# session factory themselves. A ValueError here means the import-time
# registration in app.main changed — update this block alongside it.
from app.core import events as _events
from app.core.event_notifications import (
    on_employee_event as _on_employee_event,
)
from app.core.security import create_access_token, hash_password
from app.database import Base, get_db
from app.main import app
from app.modules.recruitment.notifications import (
    HANDLERS as _RECRUITMENT_HANDLERS,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_events._handlers.get("employee.event_created", []).remove(_on_employee_event)
for _event, _handler in _RECRUITMENT_HANDLERS.items():
    _events._handlers.get(_event, []).remove(_handler)

# Use a separate test database to avoid clobbering alembic_version in dev DB
_base = settings.database_url
TEST_DB_URL = _base.rsplit("/", 1)[0] + "/hrpulsar_test"

_tables_created = False


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def db():
    """Provide a fresh DB session for each test."""
    global _tables_created
    _engine = create_async_engine(TEST_DB_URL, echo=False)
    if not _tables_created:
        # Safety: refuse to DROP SCHEMA on the dev database
        from sqlalchemy import text

        async with _engine.begin() as conn:
            row = await conn.execute(text("SELECT current_database()"))
            db_name = row.scalar()
            if db_name != "hrpulsar_test":
                raise RuntimeError(
                    f"Tests must run against hrpulsar_test, got '{db_name}'. "
                    f"Check DATABASE_URL / TEST_DB_URL."
                )
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            # DROP SCHEMA needs an exclusive lock; a connection lingering in a
            # pool from a prior test intermittently deadlocked here in the ee
            # suite (asyncpg DeadlockDetectedError). Fail fast instead of
            # blocking, and evict other backends on this test DB so the drop
            # can take its lock cleanly.
            await conn.execute(text("SET lock_timeout = '15s'"))
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND pid <> pg_backend_pid()"
                )
            )
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
            # HRP-305: mirror prod DELETE guards on tenants/users so tests
            # exercise the same row-level barrier as production.
            await conn.execute(
                text(
                    """
                    CREATE OR REPLACE FUNCTION prevent_non_demo_tenant_delete()
                    RETURNS TRIGGER AS $$
                    BEGIN
                        IF OLD.is_demo IS NOT TRUE THEN
                            RAISE EXCEPTION
                                'refusing to DELETE non-demo tenant %', OLD.id
                                USING ERRCODE = 'P0001';
                        END IF;
                        RETURN OLD;
                    END;
                    $$ LANGUAGE plpgsql;
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE OR REPLACE FUNCTION prevent_non_demo_user_delete()
                    RETURNS TRIGGER AS $$
                    DECLARE
                        tenant_is_demo BOOLEAN;
                    BEGIN
                        IF OLD.tenant_id IS NULL THEN
                            RAISE EXCEPTION
                                'refusing to DELETE user % with NULL tenant_id',
                                OLD.id
                                USING ERRCODE = 'P0001';
                        END IF;
                        SELECT is_demo INTO tenant_is_demo
                          FROM tenants WHERE id = OLD.tenant_id;
                        IF NOT FOUND THEN
                            RETURN OLD;
                        END IF;
                        IF tenant_is_demo IS NOT TRUE THEN
                            RAISE EXCEPTION
                                'refusing to DELETE user % from non-demo tenant %',
                                OLD.id, OLD.tenant_id
                                USING ERRCODE = 'P0001';
                        END IF;
                        RETURN OLD;
                    END;
                    $$ LANGUAGE plpgsql;
                    """
                )
            )
            await conn.execute(
                text(
                    "CREATE TRIGGER prevent_non_demo_tenant_delete_trg "
                    "BEFORE DELETE ON tenants FOR EACH ROW "
                    "EXECUTE FUNCTION prevent_non_demo_tenant_delete();"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE tenants ENABLE ALWAYS TRIGGER "
                    "prevent_non_demo_tenant_delete_trg;"
                )
            )
            await conn.execute(
                text(
                    "CREATE TRIGGER prevent_non_demo_user_delete_trg "
                    "BEFORE DELETE ON users FOR EACH ROW "
                    "EXECUTE FUNCTION prevent_non_demo_user_delete();"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE users ENABLE ALWAYS TRIGGER "
                    "prevent_non_demo_user_delete_trg;"
                )
            )
        _tables_created = True

    _factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    session = _factory()
    yield session
    await session.close()
    await _engine.dispose()


@pytest.fixture(autouse=True)
def _disable_auth_rate_limit():
    """Neutralise the per-IP auth throttle for the bulk of the suite.

    Many tests hammer /auth/login and /auth/magic-login over the shared
    ``testclient`` peer and would trip the 10/5/3-per-minute limits added in
    the P0-5 fix. The dedicated coverage lives in ``test_auth_rate_limit.py``,
    which re-enables the limiter explicitly.
    """
    from app.modules.auth.router import auth_limiter

    previous = auth_limiter.enabled
    auth_limiter.enabled = False
    auth_limiter.reset()
    yield
    auth_limiter.enabled = previous


@pytest_asyncio.fixture
async def client(db: AsyncSession):
    """Provide an async HTTP client with test DB session injected."""

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ---------- Data factories ----------


@pytest_asyncio.fixture
async def tenant(db: AsyncSession):
    from app.modules.company.models import Tenant

    t = Tenant(
        name=f"Test Corp {uuid.uuid4().hex[:6]}", slug=f"test-{uuid.uuid4().hex[:8]}"
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


@pytest_asyncio.fixture
async def admin_role(db: AsyncSession):
    from app.modules.auth.models import Role
    from sqlalchemy import select

    result = await db.execute(
        select(Role).where(Role.code == "admin", Role.is_system == True)  # noqa: E712
    )
    # ``.first()`` not ``scalar_one_or_none()``: the shared test DB accumulates
    # system roles created by other tests' tenant seeding, so an exact-one
    # query intermittently raised MultipleResultsFound (order-dependent flake,
    # review P0-2). Any matching system role serves the fixture's purpose.
    role = result.scalars().first()
    if not role:
        role = Role(name="Admin", code="admin", is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    return role


@pytest_asyncio.fixture
async def user(db: AsyncSession, tenant, admin_role):
    from datetime import datetime, timezone

    from app.modules.auth.models import User, user_roles

    u = User(
        email=f"test-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Test",
        last_name="User",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    await db.execute(user_roles.insert().values(user_id=u.id, role_id=admin_role.id))
    await db.commit()
    # Re-fetch with eager-loaded roles so callers iterating `user.roles` get the
    # same shape as production `get_current_user` (selectinload on User.roles).
    db.expunge(u)
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == u.id)
    )
    return result.scalar_one()


@pytest_asyncio.fixture
def access_token(user, tenant) -> str:
    return create_access_token(str(user.id), str(tenant.id))


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient, access_token: str):
    client.headers["Authorization"] = f"Bearer {access_token}"
    return client


@pytest_asyncio.fixture
async def position(db: AsyncSession, tenant):
    from app.modules.position.models import Position

    pos = Position(
        tenant_id=tenant.id,
        title="Software Engineer",
        source="manual",
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


@pytest_asyncio.fixture
async def employee(db: AsyncSession, user, tenant, position):
    from datetime import date

    from app.modules.employee.models import Employee

    emp = Employee(
        user_id=user.id,
        tenant_id=tenant.id,
        position_id=position.id,
        position_title=position.title,
        hire_date=date(2024, 1, 15),
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


@pytest_asyncio.fixture
async def skill_levels(db: AsyncSession):
    """Origin SkillLevels (tenant_id IS NULL): Basic / Intermediate /
    Advanced. Mirrors migration ``aca1005a8e45``; the unit test DB
    starts empty so tests that exercise the demo seed need this fixture
    to satisfy the HRP-299 origin-binding path. Uses ``.first()`` because
    other tests in the suite (test_material_overrides, test_pdp_service,
    test_competence_generation_session, etc.) insert their own
    SkillLevel(tenant_id=None) rows without rolling them back — the
    shared test DB can carry duplicates of the same title and the demo
    seed binds to any one of them."""
    from app.modules.competence.models import SkillLevel
    from sqlalchemy import select

    rows = [("Basic", 0), ("Intermediate", 1), ("Advanced", 2)]
    levels = {}
    for title, sort_index in rows:
        result = await db.execute(
            select(SkillLevel).where(
                SkillLevel.tenant_id.is_(None),
                SkillLevel.title == title,
            )
        )
        lvl = result.scalars().first()
        if not lvl:
            lvl = SkillLevel(
                tenant_id=None, title=title, sort_index=sort_index, is_active=True
            )
            db.add(lvl)
        levels[title] = lvl
    await db.commit()
    return levels


@pytest_asyncio.fixture
async def origin_grades(db: AsyncSession):
    """Origin DictionaryItems for the grade ladder (HRP-302). Mirrors
    migration ``aca1005a8e45``. ``.first()`` for the same reason as
    ``skill_levels`` above."""
    from app.modules.dictionary.models import DictionaryItem
    from sqlalchemy import select

    rows = [
        ("Junior", 0),
        ("Middle", 1),
        ("Senior", 2),
        ("Lead", 3),
        ("Principal", 4),
    ]
    grades = {}
    for title, sort_index in rows:
        result = await db.execute(
            select(DictionaryItem).where(
                DictionaryItem.tenant_id.is_(None),
                DictionaryItem.type == "grade",
                DictionaryItem.title == title,
            )
        )
        item = result.scalars().first()
        if not item:
            item = DictionaryItem(
                tenant_id=None,
                type="grade",
                title=title,
                sort_index=sort_index,
                is_active=True,
            )
            db.add(item)
        grades[title] = item
    await db.commit()
    return grades


@pytest_asyncio.fixture
async def assessment_statuses(db: AsyncSession):
    from app.modules.assessment.models import AssessmentStatus
    from sqlalchemy import select

    statuses_data = [
        ("draft", "Draft", 0),
        ("sent", "Sent", 1),
        ("in_progress", "In progress", 2),
        ("on_review", "On review", 3),
        ("done", "Done", 6),
        ("cancelled", "Cancelled", 99),
    ]
    statuses = {}
    for code, title, seq in statuses_data:
        result = await db.execute(
            select(AssessmentStatus).where(AssessmentStatus.code == code)
        )
        s = result.scalar_one_or_none()
        if not s:
            s = AssessmentStatus(code=code, title=title, sequence=seq)
            db.add(s)
        statuses[code] = s
    await db.commit()
    return statuses


@pytest_asyncio.fixture
async def assessment_types(db: AsyncSession):
    from app.modules.assessment.models import AssessmentType
    from sqlalchemy import select

    types_data = [("self", "Self assessment"), ("180", "180°"), ("360", "360°")]
    types = {}
    for code, title in types_data:
        result = await db.execute(
            select(AssessmentType).where(AssessmentType.code == code)
        )
        t = result.scalar_one_or_none()
        if not t:
            t = AssessmentType(code=code, title=title)
            db.add(t)
        types[code] = t
    await db.commit()
    return types


@pytest_asyncio.fixture
async def default_answer_scale(db: AsyncSession):
    """Origin default 5-point answer scale + options + level bands.

    Mirrors the production migration that ships the default scale used
    by the assessment scoring form. The demo seed needs this so it can
    materialise ``AssessmentAnswer`` rows (without options the seed
    silently skips per-indicator answers).
    """
    from app.modules.assessment.models import (
        AnswerOption,
        AnswerScale,
        AnswerScaleLevel,
    )
    from sqlalchemy import select

    existing = (
        await db.execute(
            select(AnswerScale).where(
                AnswerScale.is_default.is_(True),
                AnswerScale.tenant_id.is_(None),
                AnswerScale.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    scale = AnswerScale(
        title="Default 5-point",
        tenant_id=None,
        is_default=True,
    )
    db.add(scale)
    await db.flush()

    options = [
        ("not_observed", "Not observed", None, 0, True),
        ("never", "Never", 0, 1, False),
        ("rarely", "Rarely", 1, 2, False),
        ("sometimes", "Sometimes", 2, 3, False),
        ("often", "Often", 3, 4, False),
        ("always", "Always", 4, 5, False),
    ]
    for code, title, weight, sort_index, is_neutral in options:
        db.add(
            AnswerOption(
                scale_id=scale.id,
                title=title,
                code=code,
                weight=weight,
                sort_index=sort_index,
                is_neutral=is_neutral,
            )
        )

    levels = [
        ("basic", 0, 39, 0),
        ("intermediate", 40, 69, 1),
        ("advanced", 70, 100, 2),
    ]
    for code, p_from, p_to, sort_index in levels:
        db.add(
            AnswerScaleLevel(
                scale_id=scale.id,
                percent_from=p_from,
                percent_to=p_to,
                system_code=code,
                sort_index=sort_index,
            )
        )
    await db.commit()
    await db.refresh(scale)
    return scale


@pytest_asyncio.fixture
async def notification_templates(db: AsyncSession):
    """Origin notification_templates rows (HRP-281).

    Mirrors the subset of migration ``c3fc300775f8`` codes the demo
    seed references — enough to keep ``_seed_misc`` from silently
    skipping every Notification insert in the unit suite.
    """
    from app.modules.notification.models import NotificationTemplate
    from sqlalchemy import select

    rows = [
        ("assessment.sent", "Assessment assigned"),
        ("assessment.done", "Assessment completed"),
        ("pdp.sent", "Development plan assigned"),
        ("pdp.approved", "Development plan approved"),
        ("pdp.returned", "Development plan returned"),
        ("exam.assigned", "Exam assigned"),
        ("exam.done", "Exam results"),
    ]
    templates = {}
    for code, subject in rows:
        existing = (
            await db.execute(
                select(NotificationTemplate).where(NotificationTemplate.code == code)
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = NotificationTemplate(
                code=code,
                subject_template=subject,
                body_template="Body",
                notification_type="email",
            )
            db.add(existing)
        templates[code] = existing
    await db.commit()
    return templates
