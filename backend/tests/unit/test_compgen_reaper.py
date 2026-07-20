"""HRP-163: reap stuck-`running` competence-generation sessions.

`_force_terminate_running` handles in-process crashes; this beat job is
the safety net for OOM / SIGKILL / host reboot, where the Python except
branch never runs and the row would otherwise stay in `running`
forever — blocking the user's partial unique active-session index.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest_asyncio
from app.modules.ai_competence_generation import tasks
from app.modules.ai_competence_generation.models import (
    CompetenceGenerationSession,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture(autouse=True)
async def _touch_foreign_running_rows(db: AsyncSession):
    """The reaper scans the WHOLE shared test DB, not just rows this file
    creates. In a long full-suite run a `running` row left behind by an
    earlier test drifts past the 15-minute cutoff by the time this file
    executes, inflating the reap counts (historical flake: green in
    isolation, red in ~15-min+ full runs). Refresh `updated_at` on any
    pre-existing running rows so only rows this file backdates are stale."""
    await db.execute(
        CompetenceGenerationSession.__table__.update()
        .where(CompetenceGenerationSession.status == "running")
        .values(updated_at=datetime.now(timezone.utc))
    )
    await db.commit()


@pytest_asyncio.fixture
async def session_factory(db: AsyncSession):
    """Match the convention from ``test_competence_generation_celery``:
    one fresh async sessionmaker per test against the shared schema."""
    from app.config import settings as app_settings

    test_url = app_settings.database_url.rsplit("/", 1)[0] + "/hrpulsar_test"
    engine = create_async_engine(test_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _make_session(
    db: AsyncSession,
    tenant,
    user,
    *,
    status: str,
    updated_at: datetime,
) -> CompetenceGenerationSession:
    sess = CompetenceGenerationSession(
        tenant_id=tenant.id,
        user_id=user.id,
        scope="whole_base",
        status=status,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    # ``updated_at`` is server-defaulted + onupdate-managed; force it past
    # the cutoff with a direct UPDATE so the row looks stuck.
    await db.execute(
        CompetenceGenerationSession.__table__.update()
        .where(CompetenceGenerationSession.id == sess.id)
        .values(updated_at=updated_at)
    )
    await db.commit()
    await db.refresh(sess)
    return sess


class TestReapStuckSessions:
    async def test_reaps_session_past_cutoff(
        self,
        db: AsyncSession,
        tenant,
        user,
        session_factory,
    ):
        stale = datetime.now(timezone.utc) - timedelta(minutes=30)
        sess = await _make_session(db, tenant, user, status="running", updated_at=stale)

        result = await tasks._reap_stuck_sessions_body(session_factory)

        assert result == {"reaped": 1}
        async with session_factory() as fresh:
            reaped = await fresh.get(CompetenceGenerationSession, sess.id)
            assert reaped is not None
            assert reaped.status == "error"
            assert reaped.error_code == "reaped_stuck"
            assert "Generation worker exited without finishing" in (
                reaped.error_message or ""
            )
            assert reaped.finished_at is not None

    async def test_leaves_fresh_running_alone(
        self,
        db: AsyncSession,
        tenant,
        user,
        session_factory,
    ):
        # Within the 15-minute window — the worker is probably alive.
        fresh_ts = datetime.now(timezone.utc) - timedelta(minutes=5)
        sess = await _make_session(
            db, tenant, user, status="running", updated_at=fresh_ts
        )

        result = await tasks._reap_stuck_sessions_body(session_factory)
        assert result == {"reaped": 0}

        async with session_factory() as fresh:
            still = await fresh.get(CompetenceGenerationSession, sess.id)
            assert still is not None
            assert still.status == "running"
            assert still.error_code is None

    async def test_leaves_non_running_status_alone(
        self,
        db: AsyncSession,
        tenant,
        user,
        session_factory,
    ):
        stale = datetime.now(timezone.utc) - timedelta(minutes=30)
        ready = await _make_session(db, tenant, user, status="ready", updated_at=stale)

        result = await tasks._reap_stuck_sessions_body(session_factory)
        assert result == {"reaped": 0}

        async with session_factory() as fresh:
            still_ready = await fresh.get(CompetenceGenerationSession, ready.id)
            assert still_ready is not None
            assert still_ready.status == "ready"

    async def test_releases_partial_unique_index(
        self,
        db: AsyncSession,
        tenant,
        user,
        session_factory,
    ):
        """The whole point of reaping: after the flip, the user can start
        a new session without tripping ``ux_compgen_one_active_per_user``.
        """
        stale = datetime.now(timezone.utc) - timedelta(minutes=30)
        old = await _make_session(db, tenant, user, status="running", updated_at=stale)

        await tasks._reap_stuck_sessions_body(session_factory)

        # The unique partial index forbids two active rows per user; if
        # reaping worked the new row inserts cleanly.
        async with session_factory() as fresh:
            new_sess = CompetenceGenerationSession(
                tenant_id=tenant.id,
                user_id=user.id,
                scope="whole_base",
                status="pending",
            )
            fresh.add(new_sess)
            await fresh.commit()
            await fresh.refresh(new_sess)
            assert new_sess.id != old.id
