"""HRP-249 (D1) — tenant lifecycle for the public demo sandbox.

Covers the ``purge_expired_demo_tenants`` Celery beat task and the
``touch_demo_tenant_activity`` per-request helper. Non-demo tenants
must remain untouched; demo tenants with an expired hard TTL or a
sliding inactivity window past the threshold must be deleted, taking
their cascade-linked children with them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.config import settings
from app.modules.company.models import Division, Tenant
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def sync_test_engine(db: AsyncSession):
    """Sync engine pointed at the same test DB used by the async fixture."""
    from tests.conftest import TEST_DB_URL

    sync_url = TEST_DB_URL.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    yield engine
    engine.dispose()


async def _make_tenant(
    db: AsyncSession,
    *,
    is_demo: bool,
    expires_at: datetime | None = None,
    last_active_at: datetime | None = None,
    name: str | None = None,
) -> Tenant:
    tenant = Tenant(
        id=uuid.uuid4(),
        name=name or f"t-{uuid.uuid4().hex[:6]}",
        slug=f"slug-{uuid.uuid4().hex[:8]}",
        is_demo=is_demo,
        expires_at=expires_at,
        last_active_at=last_active_at,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant


@pytest.mark.asyncio
async def test_purge_deletes_demo_tenant_past_hard_ttl(
    db: AsyncSession, sync_test_engine, monkeypatch
):
    import app.modules.demo.tasks as tasks

    now = datetime.now(timezone.utc)
    expired = await _make_tenant(
        db,
        is_demo=True,
        expires_at=now - timedelta(minutes=5),
        last_active_at=now,
    )

    monkeypatch.setattr(tasks, "_sync_engine", lambda: sync_test_engine)

    summary = tasks.purge_expired_demo_tenants()

    assert summary["deleted"] >= 1
    remaining = await db.execute(select(Tenant).where(Tenant.id == expired.id))
    assert remaining.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_purge_deletes_demo_tenant_past_inactivity_window(
    db: AsyncSession, sync_test_engine, monkeypatch
):
    import app.modules.demo.tasks as tasks

    now = datetime.now(timezone.utc)
    stale = await _make_tenant(
        db,
        is_demo=True,
        expires_at=now + timedelta(hours=2),
        last_active_at=now
        - timedelta(seconds=settings.demo_inactivity_ttl_seconds + 60),
    )

    monkeypatch.setattr(tasks, "_sync_engine", lambda: sync_test_engine)

    tasks.purge_expired_demo_tenants()

    remaining = await db.execute(select(Tenant).where(Tenant.id == stale.id))
    assert remaining.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_purge_keeps_fresh_demo_tenant(
    db: AsyncSession, sync_test_engine, monkeypatch
):
    import app.modules.demo.tasks as tasks

    now = datetime.now(timezone.utc)
    fresh = await _make_tenant(
        db,
        is_demo=True,
        expires_at=now + timedelta(hours=2),
        last_active_at=now,
    )

    monkeypatch.setattr(tasks, "_sync_engine", lambda: sync_test_engine)

    tasks.purge_expired_demo_tenants()

    remaining = await db.execute(select(Tenant).where(Tenant.id == fresh.id))
    assert remaining.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_purge_never_touches_non_demo_tenants(
    db: AsyncSession, sync_test_engine, monkeypatch
):
    import app.modules.demo.tasks as tasks

    now = datetime.now(timezone.utc)
    # A non-demo tenant with a long-past would-be-TTL — proves the
    # ``is_demo`` predicate is doing its job.
    real = await _make_tenant(
        db,
        is_demo=False,
        expires_at=now - timedelta(days=30),
        last_active_at=now - timedelta(days=30),
    )

    monkeypatch.setattr(tasks, "_sync_engine", lambda: sync_test_engine)

    tasks.purge_expired_demo_tenants()

    remaining = await db.execute(select(Tenant).where(Tenant.id == real.id))
    assert remaining.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_purge_delete_skips_tenant_that_flipped_off_is_demo(
    db: AsyncSession, sync_test_engine, monkeypatch
):
    """HRP-249 review (HIGH) — TOCTOU between candidate SELECT and
    per-tenant DELETE. If a tenant flips from demo to non-demo in that
    window (e.g. demo → paid upgrade flow), the DELETE must be a no-op,
    not wipe a real customer."""
    import app.modules.demo.tasks as tasks

    # A paid tenant standing in for the post-upgrade state. The
    # candidate scan is monkeypatched to return its id, simulating the
    # race: at SELECT time the tenant was still demo, by DELETE time it
    # had been upgraded.
    real = await _make_tenant(db, is_demo=False)
    real_id = real.id

    monkeypatch.setattr(tasks, "_sync_engine", lambda: sync_test_engine)
    monkeypatch.setattr(
        tasks, "_expired_demo_tenant_ids", lambda db, now: [real_id]
    )
    s3_calls: list = []
    monkeypatch.setattr(
        tasks,
        "_purge_tenant_s3_assets",
        lambda tid: s3_calls.append(tid),
    )

    summary = tasks.purge_expired_demo_tenants()

    assert summary == {"scanned": 1, "deleted": 0}
    remaining = await db.execute(select(Tenant).where(Tenant.id == real_id))
    assert remaining.scalar_one_or_none() is not None
    assert s3_calls == [], "non-demo tenant must not trigger S3 purge"


@pytest.mark.asyncio
async def test_purge_cascades_to_tenant_scoped_children(
    db: AsyncSession, sync_test_engine, monkeypatch
):
    import app.modules.demo.tasks as tasks

    now = datetime.now(timezone.utc)
    tenant = await _make_tenant(
        db,
        is_demo=True,
        expires_at=now - timedelta(minutes=1),
        last_active_at=now,
    )
    division = Division(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Engineering",
    )
    db.add(division)
    await db.commit()
    division_id = division.id

    monkeypatch.setattr(tasks, "_sync_engine", lambda: sync_test_engine)

    tasks.purge_expired_demo_tenants()

    # Drop the identity-map so the next SELECT actually round-trips to
    # Postgres rather than handing back the still-cached Division row.
    # ``expunge_all`` is sync and async-safe; ``expire_all`` on an
    # ``AsyncSession`` triggers ``MissingGreenlet`` as soon as any
    # downstream assertion touches a relationship attribute.
    db.expunge_all()
    found = await db.execute(
        select(Division).where(Division.id == division_id)
    )
    assert found.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_purge_cascades_through_talent_candidate(
    db: AsyncSession, sync_test_engine, monkeypatch
):
    """Tenant delete must cascade past TalentCandidate → Employee FK.

    Pre-fix the ``talent_candidates.employee_id`` FK had no ON DELETE
    clause, so when ``tenants`` cascaded into both ``employees`` and
    ``talent_candidates`` Postgres rejected the ``employees`` delete
    while the candidate row still pointed at it — the whole tenant
    purge tripped over the FK violation seen in prod logs.
    """
    import app.modules.demo.tasks as tasks
    from app.modules.auth.models import User
    from app.modules.employee.models import Employee
    from app.modules.talent_market.models import TalentCandidate, TalentCard

    now = datetime.now(timezone.utc)
    tenant = await _make_tenant(
        db,
        is_demo=True,
        expires_at=now - timedelta(minutes=1),
        last_active_at=now,
    )

    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"u-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="x",
        first_name="Demo",
        last_name="User",
    )
    db.add(user)
    await db.flush()

    employee = Employee(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        user_id=user.id,
        hire_date=now.date(),
    )
    db.add(employee)
    await db.flush()

    card = TalentCard(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        title="Demo card",
        card_type="talent",
        author_id=user.id,
        start_date=now.date(),
    )
    db.add(card)
    await db.flush()

    # TalentCandidate is not tenant-scoped — it cascades through its
    # card_id → talent_cards (tenant-scoped). The bug surfaces because
    # talent_candidates.employee_id pointed at employees with no CASCADE,
    # so tenant deletion couldn't reap the employees while the candidate
    # row still referenced them.
    candidate = TalentCandidate(
        id=uuid.uuid4(),
        card_id=card.id,
        employee_id=employee.id,
    )
    db.add(candidate)
    await db.commit()
    tenant_id = tenant.id
    employee_id = employee.id

    monkeypatch.setattr(tasks, "_sync_engine", lambda: sync_test_engine)

    summary = tasks.purge_expired_demo_tenants()

    assert summary["deleted"] >= 1
    # See ``test_purge_deletes_tenant_with_division``: expunge_all is
    # the async-safe identity-map drop. ``expire_all`` triggers
    # ``MissingGreenlet`` on the next relationship access.
    db.expunge_all()
    remaining = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    assert remaining.scalar_one_or_none() is None
    employee_left = await db.execute(
        select(Employee).where(Employee.id == employee_id)
    )
    assert employee_left.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_purge_cascades_through_pdp_comment(
    db: AsyncSession, sync_test_engine, monkeypatch
):
    """HRP-305 regression — the prod incident.

    Pre-fix ``pdp_comments.user_id`` had no ``ondelete`` clause, so
    Postgres rejected the user delete the moment the cascade reached
    it from ``tenants → users`` while ``pdps → pdp_comments`` was still
    pending. With ``ON DELETE CASCADE`` on the user FK the comment
    rides out on whichever cascade resolves first.
    """
    import app.modules.demo.tasks as tasks
    from app.modules.assessment.models import PDP, PDPComment
    from app.modules.auth.models import User
    from app.modules.employee.models import Employee
    from app.modules.position.models import Position

    now = datetime.now(timezone.utc)
    tenant = await _make_tenant(
        db,
        is_demo=True,
        expires_at=now - timedelta(minutes=1),
        last_active_at=now,
    )

    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"u-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="x",
        first_name="Demo",
        last_name="User",
    )
    db.add(user)
    await db.flush()

    pos = Position(tenant_id=tenant.id, title="Eng", source="manual")
    db.add(pos)
    await db.flush()

    employee = Employee(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        user_id=user.id,
        position_id=pos.id,
        position_title=pos.title,
        hire_date=now.date(),
    )
    db.add(employee)
    await db.flush()

    pdp = PDP(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        title="Demo PDP",
        employee_id=employee.id,
        author_id=user.id,
        status="draft",
    )
    db.add(pdp)
    await db.flush()

    comment = PDPComment(
        id=uuid.uuid4(),
        pdp_id=pdp.id,
        user_id=user.id,
        text="ok",
    )
    db.add(comment)
    await db.commit()
    tenant_id = tenant.id
    comment_id = comment.id

    monkeypatch.setattr(tasks, "_sync_engine", lambda: sync_test_engine)

    summary = tasks.purge_expired_demo_tenants()

    assert summary["deleted"] >= 1
    # See ``test_purge_deletes_tenant_with_division``: expunge_all is
    # the async-safe identity-map drop. ``expire_all`` triggers
    # ``MissingGreenlet`` on the next relationship access.
    db.expunge_all()
    remaining = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    assert remaining.scalar_one_or_none() is None
    comment_left = await db.execute(
        select(PDPComment).where(PDPComment.id == comment_id)
    )
    assert comment_left.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_purge_cascades_pdp_comment_via_user_fk_only(
    db: AsyncSession, sync_test_engine, monkeypatch
):
    """HRP-305 cross-tenant regression — exercise the user_id FK path.

    The sibling test above (`test_purge_cascades_through_pdp_comment`)
    happens to also be cleared by the `pdp_id` cascade since the PDP is
    co-tenant; reverting `pdp_comments.user_id` to NO ACTION would not
    trip it. This test points `pdp_comments.user_id` at a user in the
    *purged* demo tenant while the parent PDP lives in a *surviving*
    demo tenant — so the only way the comment row can be cleaned up is
    through the new user_id CASCADE. Reverting that ondelete makes the
    purge crash here.
    """
    import app.modules.demo.tasks as tasks
    from app.modules.assessment.models import PDP, PDPComment
    from app.modules.auth.models import User
    from app.modules.employee.models import Employee
    from app.modules.position.models import Position

    now = datetime.now(timezone.utc)
    # Tenant A — about to expire and get purged.
    tenant_a = await _make_tenant(
        db,
        is_demo=True,
        expires_at=now - timedelta(minutes=1),
        last_active_at=now,
    )
    # Tenant B — demo but with a long TTL, so purge leaves it alone.
    tenant_b = await _make_tenant(
        db,
        is_demo=True,
        expires_at=now + timedelta(hours=4),
        last_active_at=now,
    )

    commenter = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        email=f"a-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="x",
        first_name="A",
        last_name="User",
    )
    pdp_owner = User(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        email=f"b-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="x",
        first_name="B",
        last_name="Owner",
    )
    db.add_all([commenter, pdp_owner])
    await db.flush()

    pos = Position(tenant_id=tenant_b.id, title="Eng", source="manual")
    db.add(pos)
    await db.flush()

    employee = Employee(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        user_id=pdp_owner.id,
        position_id=pos.id,
        position_title=pos.title,
        hire_date=now.date(),
    )
    db.add(employee)
    await db.flush()

    surviving_pdp = PDP(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        title="Surviving PDP",
        employee_id=employee.id,
        author_id=pdp_owner.id,
        status="draft",
    )
    db.add(surviving_pdp)
    await db.flush()

    # Comment lives under the surviving PDP but is authored by a user
    # in the purged tenant — only the user_id cascade can remove it.
    cross_comment = PDPComment(
        id=uuid.uuid4(),
        pdp_id=surviving_pdp.id,
        user_id=commenter.id,
        text="cross-tenant comment",
    )
    db.add(cross_comment)
    await db.commit()
    tenant_a_id = tenant_a.id
    tenant_b_id = tenant_b.id
    comment_id = cross_comment.id
    pdp_id = surviving_pdp.id

    monkeypatch.setattr(tasks, "_sync_engine", lambda: sync_test_engine)

    summary = tasks.purge_expired_demo_tenants()

    assert summary["deleted"] >= 1
    # See ``test_purge_deletes_tenant_with_division``: expunge_all is
    # the async-safe identity-map drop. ``expire_all`` triggers
    # ``MissingGreenlet`` on the next relationship access.
    db.expunge_all()
    # Tenant A is gone, tenant B survives.
    a_left = await db.execute(select(Tenant).where(Tenant.id == tenant_a_id))
    assert a_left.scalar_one_or_none() is None
    b_left = await db.execute(select(Tenant).where(Tenant.id == tenant_b_id))
    assert b_left.scalar_one_or_none() is not None
    # The PDP itself survives (its tenant did).
    pdp_left = await db.execute(select(PDP).where(PDP.id == pdp_id))
    assert pdp_left.scalar_one_or_none() is not None
    # But the cross-tenant comment was cleaned up via the user_id CASCADE.
    comment_left = await db.execute(
        select(PDPComment).where(PDPComment.id == comment_id)
    )
    assert comment_left.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_guard_blocks_non_demo_tenant(db: AsyncSession):
    """HRP-305 — trigger raises P0001 on DELETE of a non-demo tenant."""
    from sqlalchemy.exc import DBAPIError

    real = await _make_tenant(db, is_demo=False)
    real_id = real.id

    with pytest.raises(DBAPIError) as exc:
        await db.delete(real)
        await db.commit()

    assert getattr(exc.value.orig, "sqlstate", None) == "P0001"
    assert "non-demo tenant" in str(exc.value)
    await db.rollback()

    # And the row stayed put.
    remaining = await db.execute(select(Tenant).where(Tenant.id == real_id))
    assert remaining.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_delete_guard_allows_demo_tenant(db: AsyncSession):
    """HRP-305 — demo tenants delete fine through the trigger."""
    demo = await _make_tenant(db, is_demo=True)
    demo_id = demo.id

    await db.delete(demo)
    await db.commit()

    remaining = await db.execute(select(Tenant).where(Tenant.id == demo_id))
    assert remaining.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_guard_blocks_non_demo_user(db: AsyncSession):
    """HRP-305 — trigger raises P0001 on DELETE of a non-demo user."""
    from app.modules.auth.models import User
    from sqlalchemy.exc import DBAPIError

    real = await _make_tenant(db, is_demo=False)
    u = User(
        id=uuid.uuid4(),
        tenant_id=real.id,
        email=f"u-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="x",
        first_name="Real",
        last_name="User",
    )
    db.add(u)
    await db.commit()
    user_id = u.id

    with pytest.raises(DBAPIError) as exc:
        await db.delete(u)
        await db.commit()

    assert getattr(exc.value.orig, "sqlstate", None) == "P0001"
    assert "non-demo tenant" in str(exc.value)
    await db.rollback()

    remaining = await db.execute(select(User).where(User.id == user_id))
    assert remaining.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_purge_s3_continues_after_middle_page_failure(
    db: AsyncSession, sync_test_engine, monkeypatch
):
    """HRP-276 / M6: ``_purge_tenant_s3_assets`` must tolerate a single
    failing page and still delete the rest. Pre-fix the try/except sat
    outside the page loop, so any page-level error would skip the
    remaining pages and orphan their blobs.
    """
    import app.modules.demo.tasks as tasks

    delete_calls: list[list[str]] = []

    class _FakeClient:
        def get_paginator(self, _name):
            return self

        def paginate(self, *, Bucket, Prefix):
            return [
                {"Contents": [{"Key": "p1/a"}, {"Key": "p1/b"}]},
                {"Contents": [{"Key": "p2/a"}]},
                {"Contents": [{"Key": "p3/a"}, {"Key": "p3/b"}]},
            ]

        def delete_objects(self, *, Bucket, Delete):
            page_keys = [obj["Key"] for obj in Delete["Objects"]]
            # Fail only on the middle page (single-key payload).
            if page_keys == ["p2/a"]:
                raise RuntimeError("S3 flake on middle page")
            delete_calls.append(page_keys)

    monkeypatch.setattr(
        "app.core.s3.get_s3_client", lambda: _FakeClient()
    )

    tasks._purge_tenant_s3_assets("fake-tenant")

    # Pages 1 and 3 were processed; page 2's failure was logged and
    # the loop continued.
    assert delete_calls == [["p1/a", "p1/b"], ["p3/a", "p3/b"]]


def _patch_activity_factory_to_test_engine(monkeypatch) -> None:
    """Re-point ``activity._session_factory`` at the test database.

    HRP-276 / H1: the touch helper now writes through its own session
    so the UPDATE survives a read-only request transaction. The own
    session uses ``app.database.async_session`` by default, which is
    bound to ``settings.database_url`` — the dev DB, not the test DB.
    Tests must redirect it explicitly.
    """
    from app.modules.demo import activity
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from tests.conftest import TEST_DB_URL

    test_engine = create_async_engine(TEST_DB_URL)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(activity, "_session_factory", lambda: test_factory)


@pytest.mark.asyncio
async def test_touch_updates_last_active_for_demo_tenant(
    db: AsyncSession, monkeypatch
):
    from app.modules.demo import activity

    # Force the helper to bypass Redis so we exercise the SQL path in
    # isolation — Redis may or may not be reachable on the test host.
    monkeypatch.setattr(activity, "_redis_client", lambda: None)
    _patch_activity_factory_to_test_engine(monkeypatch)

    now = datetime.now(timezone.utc)
    tenant = await _make_tenant(
        db,
        is_demo=True,
        expires_at=now + timedelta(hours=2),
        last_active_at=now - timedelta(minutes=30),
    )

    await activity.touch_demo_tenant_activity(db, tenant.id)

    await db.refresh(tenant)
    assert tenant.last_active_at is not None
    assert tenant.last_active_at > now - timedelta(seconds=5)


@pytest.mark.asyncio
async def test_touch_no_op_on_non_demo_tenant(
    db: AsyncSession, monkeypatch
):
    from app.modules.demo import activity

    monkeypatch.setattr(activity, "_redis_client", lambda: None)
    _patch_activity_factory_to_test_engine(monkeypatch)

    baseline = datetime.now(timezone.utc) - timedelta(days=7)
    tenant = await _make_tenant(
        db,
        is_demo=False,
        last_active_at=baseline,
    )

    await activity.touch_demo_tenant_activity(db, tenant.id)

    await db.refresh(tenant)
    # ``last_active_at`` is left untouched because the UPDATE's
    # ``is_demo = true`` predicate filtered the row out.
    assert tenant.last_active_at == baseline


@pytest.mark.asyncio
async def test_touch_survives_request_session_rollback(
    db: AsyncSession, monkeypatch
):
    """HRP-276 / H1: GETs in ``get_db`` never commit — the dedicated
    touch session must persist last_active_at even when the borrowed
    request session is rolled back. Verified by writing the touch,
    rolling back the test session, then reading from a third fresh
    session — the timestamp survives.
    """
    from app.modules.demo import activity
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from tests.conftest import TEST_DB_URL

    monkeypatch.setattr(activity, "_redis_client", lambda: None)
    _patch_activity_factory_to_test_engine(monkeypatch)

    now = datetime.now(timezone.utc)
    tenant = await _make_tenant(
        db,
        is_demo=True,
        expires_at=now + timedelta(hours=2),
        last_active_at=now - timedelta(minutes=30),
    )
    tenant_id = tenant.id

    await activity.touch_demo_tenant_activity(db, tenant_id)

    # Simulate the GET request path: drop everything that lived on the
    # request session without committing.
    await db.rollback()

    # Third, completely fresh session reads from disk — the touch's own
    # session must have committed.
    verify_engine = create_async_engine(TEST_DB_URL)
    verify_factory = async_sessionmaker(
        verify_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with verify_factory() as verify:
        row = (
            await verify.execute(
                select(Tenant.last_active_at).where(Tenant.id == tenant_id)
            )
        ).scalar_one()
    await verify_engine.dispose()

    assert row is not None
    assert row > now - timedelta(seconds=5)
