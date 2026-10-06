"""HRP-923: abuse and cost guards of the public process check - the per-IP
throttle, the captcha, the daily budget with its pause, the input limits -
and the daily purge of expired checks with their sandbox containers.

Requests come through the test client, whose peer (127.0.0.1) is a trusted
proxy, so ``X-Forwarded-For`` names the visitor exactly as Caddy does in
production.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
import redis.exceptions
from app.config import settings
from app.core import turnstile
from app.core.celery_app import celery
from app.core.redis import redis_client
from app.modules.ai import llm_client
from app.modules.public_check import router, schemas, service, tasks
from app.modules.public_check.models import PublicCheck
from app.modules.work.models import (
    WorkContainer,
    WorkDecompositionSession,
    WorkStep,
    WorkStepPrimitive,
)
from celery.schedules import crontab
from sqlalchemy import func, select, update

from tests.unit.test_public_check import _answer, seeded  # noqa: F401 - fixture

URL = "/api/public-check/checks"
VISITOR = {"X-Forwarded-For": "203.0.113.7"}
NEIGHBOUR = {"X-Forwarded-For": "198.51.100.9"}


def _body(**extra):
    return {
        "description": f"We answer requests and file returns. {uuid.uuid4()}",
        **extra,
    }


@pytest.fixture(autouse=True)
def _guarded(monkeypatch):
    """The service on, its own sandbox, every guard at a known state."""
    monkeypatch.setattr(settings, "public_check_enabled", True)
    monkeypatch.setattr(service, "SANDBOX_SLUG", f"pc_guard_{uuid.uuid4().hex[:10]}")
    monkeypatch.setattr(router.limiter, "enabled", False)
    monkeypatch.setattr(settings, "public_check_turnstile_secret", "")
    monkeypatch.setattr(settings, "public_check_daily_limit", 0)
    monkeypatch.setattr(settings, "public_check_paused", False)


@pytest.fixture
async def clean_budget():
    """Today's and tomorrow's budget keys of the check counter start empty."""

    async def _drop():
        async with redis_client() as client:
            keys = await client.keys("public_check:daily:*")
            if keys:
                await client.delete(*keys)

    await _drop()
    yield
    await _drop()


@pytest.fixture
def throttled(monkeypatch):
    monkeypatch.setattr(router.limiter, "enabled", True)
    monkeypatch.setattr(settings, "public_check_rate_limit", "2/hour")
    router.limiter.reset()
    yield
    router.limiter.reset()


class _Siteverify:
    """Cloudflare's siteverify: answers ``success`` with the ``action`` and
    ``hostname`` the token was solved for, or raises ``error``."""

    def __init__(
        self,
        success: bool = True,
        error: Exception | None = None,
        action: str = router.ACTION_CHECK,
        hostname: str = "check.example.test",
    ):
        self.success, self.error, self.sent = success, error, []
        self.action, self.hostname = action, hostname

    def __call__(self, **_kwargs):  # httpx.AsyncClient(timeout=...)
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url, data):
        self.sent.append((url, data))
        if self.error:
            raise self.error
        return httpx.Response(
            200,
            json={
                "success": self.success,
                "action": self.action,
                "hostname": self.hostname,
            },
        )


@pytest.fixture
def siteverify(monkeypatch):
    def _install(**answer) -> _Siteverify:
        fake = _Siteverify(**answer)
        monkeypatch.setattr(settings, "public_check_turnstile_secret", "secret")
        monkeypatch.setattr(turnstile, "httpx", SimpleNamespace(AsyncClient=fake))
        return fake

    return _install


async def _checks(db) -> int:
    return await db.scalar(select(func.count()).select_from(PublicCheck))


class TestIpThrottle:
    async def test_the_visitor_over_the_limit_gets_a_coded_429(self, client, throttled):
        for _ in range(2):
            assert (
                await client.post(URL, json=_body(), headers=VISITOR)
            ).status_code == 202
        refused = await client.post(URL, json=_body(), headers=VISITOR)
        assert refused.status_code == 429
        assert refused.json()["code"] == "public_check_rate_limited"
        # When the visitor's hour resets, not slowapi's text.
        assert 1 <= int(refused.headers["Retry-After"]) <= 3600
        # Another visitor behind the same proxy has a budget of their own:
        # the key is the client, not the proxy's address.
        assert (
            await client.post(URL, json=_body(), headers=NEIGHBOUR)
        ).status_code == 202

    async def test_polling_is_not_throttled(self, client, throttled):
        token = (await client.post(URL, json=_body(), headers=VISITOR)).json()["token"]
        for _ in range(10):
            resp = await client.get(f"{URL}/{token}", headers=VISITOR)
            assert resp.status_code == 200


class TestCaptcha:
    async def test_no_secret_no_captcha(self, client):
        assert (await client.post(URL, json=_body())).status_code == 202

    async def test_a_passed_challenge_lets_the_check_in(self, client, siteverify):
        fake = siteverify(success=True)
        resp = await client.post(
            URL, json=_body(turnstile_token="tok"), headers=VISITOR
        )
        assert resp.status_code == 202
        [(url, data)] = fake.sent
        assert url == turnstile.VERIFY_URL
        assert data == {
            "secret": "secret",
            "response": "tok",
            "remoteip": "203.0.113.7",
        }

    @pytest.mark.parametrize(
        ("token", "answer"),
        [
            (None, {"success": True}),
            ("tok", {"success": False}),
            ("tok", {"error": httpx.ConnectError("down")}),
        ],
        ids=["no-token", "refused", "network-error"],
    )
    async def test_a_failed_challenge_is_a_coded_400_and_no_check(
        self, client, db, siteverify, token, answer
    ):
        siteverify(**answer)
        before = await _checks(db)
        body = _body() if token is None else _body(turnstile_token=token)
        resp = await client.post(URL, json=body)
        assert resp.status_code == 400
        assert resp.json()["code"] == "public_check_captcha_failed"
        assert await _checks(db) == before

    @pytest.mark.parametrize(
        "answer",
        [{"action": router.ACTION_SAVE}, {"hostname": "evil.example"}],
        ids=["another-form", "another-site"],
    )
    async def test_a_token_solved_elsewhere_is_refused(
        self, client, db, siteverify, monkeypatch, answer
    ):
        monkeypatch.setattr(settings, "public_check_host", "check.example.test")
        siteverify(**answer)
        before = await _checks(db)
        resp = await client.post(URL, json=_body(turnstile_token="tok"))
        assert resp.status_code == 400
        assert resp.json()["code"] == "public_check_captcha_failed"
        assert await _checks(db) == before

    async def test_an_http_error_of_siteverify_fails_closed(self, monkeypatch):
        class _Down(_Siteverify):
            async def post(self, url, data):
                return httpx.Response(500)

        monkeypatch.setattr(turnstile, "httpx", SimpleNamespace(AsyncClient=_Down()))
        assert await turnstile.verify_turnstile("s", "tok", remote_ip=None) is False


class TestDailyBudget:
    async def test_zero_is_no_cap_and_never_counts(self, monkeypatch):
        def _no_redis():
            raise AssertionError("no cap, no counting")

        monkeypatch.setattr(service, "redis_client", _no_redis)
        for _ in range(3):
            await service.spend_daily("checks", 0)

    async def test_the_check_over_the_cap_is_told_to_come_back_tomorrow(
        self, client, db, monkeypatch, clean_budget
    ):
        monkeypatch.setattr(settings, "public_check_daily_limit", 2)
        for _ in range(2):
            assert (await client.post(URL, json=_body())).status_code == 202
        before = await _checks(db)
        refused = await client.post(URL, json=_body())
        assert refused.status_code == 429
        assert refused.json()["code"] == "public_check_daily_limit"
        assert await _checks(db) == before
        # Until the next 00:00 UTC.
        midnight = (datetime.now(UTC) + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        left = (midnight - datetime.now(UTC)).total_seconds()
        assert abs(int(refused.headers["Retry-After"]) - left) <= 5

        class _Tomorrow(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(days=1)

        monkeypatch.setattr(service, "datetime", _Tomorrow)
        assert (await client.post(URL, json=_body())).status_code == 202

    async def test_a_failed_captcha_spends_no_budget(
        self, client, monkeypatch, siteverify, clean_budget
    ):
        monkeypatch.setattr(settings, "public_check_daily_limit", 1)
        siteverify(success=False)
        assert (
            await client.post(URL, json=_body(turnstile_token="t"))
        ).status_code == 400
        siteverify(success=True)
        assert (
            await client.post(URL, json=_body(turnstile_token="t"))
        ).status_code == 202

    async def test_the_pause_closes_intake_and_running_checks_go_on(
        self, client, monkeypatch
    ):
        token = (await client.post(URL, json=_body())).json()["token"]
        monkeypatch.setattr(settings, "public_check_paused", True)
        refused = await client.post(URL, json=_body())
        assert refused.status_code == 429
        assert refused.json()["code"] == "public_check_daily_limit"
        assert (await client.get(f"{URL}/{token}")).status_code == 200

    async def test_the_pause_refuses_before_the_throttle_and_the_captcha(
        self, client, monkeypatch, siteverify, throttled
    ):
        fake = siteverify(success=True)
        monkeypatch.setattr(settings, "public_check_rate_limit", "1/hour")
        monkeypatch.setattr(settings, "public_check_paused", True)
        refused = await client.post(
            URL, json=_body(turnstile_token="t"), headers=VISITOR
        )
        assert refused.status_code == 429
        assert refused.json()["code"] == "public_check_daily_limit"
        assert int(refused.headers["Retry-After"]) >= 1
        assert fake.sent == []  # no call to Cloudflare
        # The visitor's only check of the hour is still there.
        monkeypatch.setattr(settings, "public_check_paused", False)
        resp = await client.post(URL, json=_body(turnstile_token="t"), headers=VISITOR)
        assert resp.status_code == 202

    @pytest.mark.parametrize(
        "error",
        [
            ConnectionError("refused"),
            redis.exceptions.ConnectionError("refused"),
            redis.exceptions.TimeoutError("slow"),
        ],
        ids=["socket", "redis-connection", "redis-timeout"],
    )
    async def test_an_unreachable_redis_fails_closed(self, monkeypatch, error):
        def _down():
            raise error

        monkeypatch.setattr(service, "redis_client", _down)
        with pytest.raises(service.AppError) as refused:
            await service.spend_daily("checks", 1)
        assert refused.value.code == "public_check_unavailable"

    async def test_a_reply_error_of_redis_surfaces(self, monkeypatch):
        def _wrong():
            raise redis.exceptions.ResponseError("WRONGTYPE")

        monkeypatch.setattr(service, "redis_client", _wrong)
        with pytest.raises(redis.exceptions.ResponseError):
            await service.spend_daily("checks", 1)

    @pytest.mark.parametrize("amount", [0, -1, 1.5])
    async def test_the_amount_is_a_positive_whole_number(self, amount):
        with pytest.raises(ValueError, match="positive whole number"):
            await service.spend_daily("minutes", 10, amount=amount)

    async def test_redis_down_refuses_checks_with_a_warning(
        self, client, db, monkeypatch, caplog
    ):
        def _down():
            raise ConnectionError("redis is down")

        monkeypatch.setattr(settings, "public_check_daily_limit", 1)
        monkeypatch.setattr(service, "redis_client", _down)
        before = await _checks(db)
        with caplog.at_level(logging.WARNING, logger=service.logger.name):
            resp = await client.post(URL, json=_body())
        assert resp.status_code == 503
        assert resp.json()["code"] == "public_check_unavailable"
        assert await _checks(db) == before
        assert "daily budget" in caplog.text


class TestInputLimits:
    async def test_the_description_limits_hold_at_their_edges(self, client):
        def _post(n):
            return client.post(URL, json={"description": "x" * n})

        assert (await _post(schemas.DESCRIPTION_MIN)).status_code == 202
        assert (await _post(schemas.DESCRIPTION_MAX)).status_code == 202
        assert (await _post(schemas.DESCRIPTION_MIN - 1)).status_code == 422
        assert (await _post(schemas.DESCRIPTION_MAX + 1)).status_code == 422

    async def test_the_captcha_token_is_bounded(self, client):
        long_token = "t" * (schemas.TURNSTILE_TOKEN_MAX + 1)
        resp = await client.post(URL, json=_body(turnstile_token=long_token))
        assert resp.status_code == 422


class TestPurge:
    async def _check(self, client, db, session_factory, *, run=False) -> PublicCheck:
        token = (await client.post(URL, json=_body())).json()["token"]
        check = await db.scalar(
            select(PublicCheck).where(
                PublicCheck.token_hash == service.hash_token(token)
            )
        )
        if run:
            with patch.object(llm_client, "generate_json", side_effect=_answer):
                assert (await tasks.execute_check(session_factory, check.id))[
                    "status"
                ] == "ready"
        return check

    async def _count(self, db, model, column, value) -> int:
        return await db.scalar(
            select(func.count()).select_from(model).where(column == value)
        )

    @pytest.mark.usefixtures("seeded")
    async def test_expired_go_with_their_tree_the_rest_stays_and_a_rerun_is_a_no_op(
        self, client, db, session_factory, monkeypatch
    ):
        monkeypatch.setattr(service, "PURGE_BATCH", 1)  # several batches
        expired = [
            await self._check(client, db, session_factory, run=True),
            await self._check(client, db, session_factory),
        ]
        kept = await self._check(client, db, session_factory)
        fresh = await self._check(client, db, session_factory)
        steps = (
            await db.scalars(
                select(WorkStep.id).where(
                    WorkStep.container_id == expired[0].container_id
                )
            )
        ).all()
        assert steps  # the run materialised its steps
        await db.execute(
            update(PublicCheck)
            .where(PublicCheck.id.in_([c.id for c in expired]))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.execute(
            update(PublicCheck).where(PublicCheck.id == kept.id).values(expires_at=None)
        )
        await db.commit()

        result = await service.purge_expired(db)
        assert result["checks"] >= 2

        for check in expired:
            assert await self._count(db, PublicCheck, PublicCheck.id, check.id) == 0
            assert (
                await self._count(
                    db, WorkContainer, WorkContainer.id, check.container_id
                )
                == 0
            )
            assert (
                await self._count(
                    db,
                    WorkDecompositionSession,
                    WorkDecompositionSession.id,
                    check.session_id,
                )
                == 0
            )
        assert (
            await self._count(
                db, WorkStep, WorkStep.container_id, expired[0].container_id
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(WorkStepPrimitive)
                .where(WorkStepPrimitive.step_id.in_(steps))
            )
            == 0
        )
        for check in (kept, fresh):
            assert await self._count(db, PublicCheck, PublicCheck.id, check.id) == 1
            assert (
                await self._count(
                    db, WorkContainer, WorkContainer.id, check.container_id
                )
                == 1
            )

        again = await service.purge_expired(db)
        assert (again["checks"], again["orphan_containers"]) == (0, 0)

    async def test_old_sandbox_containers_no_check_points_at_are_dropped(
        self, client, db, session_factory, tenant
    ):
        check = await self._check(client, db, session_factory)
        sandbox_id, user_id = await service.ensure_sandbox(db)
        old = datetime.now(UTC) - timedelta(days=2)

        def _container(tenant_id, owner_id, created_at):
            return WorkContainer(
                tenant_id=tenant_id,
                owner_id=owner_id,
                created_by_id=owner_id,
                type="process",
                title="debris",
                catalog_version="test",
                created_at=created_at,
            )

        orphan = _container(sandbox_id, user_id, old)
        young = _container(sandbox_id, user_id, datetime.now(UTC))
        foreign = _container(tenant.id, None, old)
        db.add_all([orphan, young, foreign])
        await db.execute(
            update(WorkContainer)
            .where(WorkContainer.id == check.container_id)
            .values(created_at=old)
        )
        await db.commit()

        result = await service.purge_expired(db)
        assert result["orphan_containers"] == 1
        assert await self._count(db, WorkContainer, WorkContainer.id, orphan.id) == 0
        for kept in (young.id, foreign.id, check.container_id):
            assert await self._count(db, WorkContainer, WorkContainer.id, kept) == 1


def test_the_purge_runs_daily_on_a_wall_clock():
    entry = celery.conf.beat_schedule["purge-expired-public-checks"]
    assert entry["task"] == tasks.purge_expired.name
    assert entry["schedule"] == crontab(hour=4, minute=20)


def test_the_purge_task_runs():
    # A direct call, as beat's worker would make it - its own event loop and
    # engine on the test database.
    result = tasks.purge_expired()
    assert set(result) == {"checks", "orphan_containers", "addresses"}
