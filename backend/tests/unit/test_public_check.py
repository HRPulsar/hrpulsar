"""HRP-922: the anonymous process check - create, poll, read the frozen
result - on the Coverage pipeline with the model mocked.

Every test gets a sandbox of its own (a unique slug): the sandbox tenant
cannot be deleted (the non-demo tenant guard), and the breakdown cache in
Redis is keyed by it, so a shared one would leak answers between tests.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from app.config import settings
from app.core import ai_usage_hooks
from app.modules.ai import llm_client
from app.modules.auth.models import User
from app.modules.company.models import Tenant
from app.modules.primitives import catalog_data
from app.modules.public_check import router, schemas, service, tasks
from app.modules.public_check.models import PublicCheck
from app.modules.work import service as work_service
from app.modules.work import tasks as work_tasks
from app.modules.work.models import WorkContainer, WorkDecompositionSession, WorkStep
from app.modules.work.schemas import DecompositionSchema
from sqlalchemy import delete, func, select, update

pytestmark = pytest.mark.asyncio

# The production value, before the fixture below swaps it per test.
REAL_SANDBOX_SLUG = service.SANDBOX_SLUG

URL = "/api/public-check/checks"

# Five steps, one per outcome: strong codes only (an agent alone), a draft
# code (an AI draft to check), a regulatory signature over a strong code
# (review by responsibility, no code decides), a judgement code (stays with
# people) and a boundary code alone (out of scope). An hour, monthly each.
_STEPS = [
    ("Read the request", ["P1", "P3"], "none", "draft"),
    ("Draft the reply", ["P4"], "none", "draft"),
    ("File the return", ["P1"], "regulatory", "external_change"),
    ("Decide on the exception", ["P6"], "none", "draft"),
    ("Carry the box", ["B1"], "none", "draft"),
]
_SPLIT = {
    "steps": [
        {"title": title, "hours_per_run": 1, "runs_per_year": 12}
        for title, *_ in _STEPS
    ]
}
_CLASSES = {
    "steps": [
        {
            "primitives": codes,
            "responsibility": responsibility,
            "output_type": output,
            "evidence": [{"code": c, "quote": "q", "confidence": 0.9} for c in codes],
        }
        for _title, codes, responsibility, output in _STEPS
    ]
}


def _answer(*_args, schema=None, **_kwargs):
    if schema is DecompositionSchema:
        return schema.model_validate(_SPLIT)
    return schema.model_validate(_CLASSES)


def _no_call(*_a, **_k):
    raise AssertionError("the model must not be called")


def _text() -> str:
    # Fresh per test: the breakdown cache outlives a run.
    return f"Our team answers customer requests and files returns. {uuid.uuid4()}"


@pytest.fixture(autouse=True)
def _own_sandbox(monkeypatch):
    monkeypatch.setattr(service, "SANDBOX_SLUG", f"pc_sandbox_{uuid.uuid4().hex[:10]}")


@pytest.fixture(autouse=True)
def _no_ip_throttle(monkeypatch):
    # The per-IP throttle of HRP-923 has its own tests
    # (test_public_check_guards.py); here every check comes from one peer.
    monkeypatch.setattr(router.limiter, "enabled", False)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "public_check_enabled", True)


@pytest.fixture
async def seeded(db, monkeypatch):
    await db.execute(catalog_data.seed_insert())
    await db.commit()
    monkeypatch.setattr(work_tasks, "_max_attempts", lambda _settings: 1)
    monkeypatch.setattr(work_tasks, "BREAKDOWN_CACHE_TTL_S", 60)


async def _start(client, db, **body) -> tuple[str, PublicCheck]:
    resp = await client.post(URL, json={"description": _text(), **body})
    assert resp.status_code == 202, resp.text
    token = resp.json()["token"]
    check = await db.scalar(
        select(PublicCheck)
        .where(PublicCheck.token_hash == service.hash_token(token))
        .execution_options(populate_existing=True)
    )
    return token, check


async def _run(session_factory, check_id, answer=_answer):
    with patch.object(llm_client, "generate_json", side_effect=answer):
        return await tasks.execute_check(session_factory, check_id)


class TestCheckFlow:
    async def test_create_poll_and_read_the_result(
        self, client, db, seeded, enabled, session_factory
    ):
        token, check = await _start(
            client,
            db,
            answers={
                "industry": "Retail",
                "team_size": 8,
                "frequency": "monthly",
                "hourly_rate": 50,
                "currency": "EUR",
            },
            utm={"source": "linkedin", "campaign": "hook-a", "gclid": "dropped"},
        )
        assert check.status == "pending"
        assert check.utm == {"source": "linkedin", "campaign": "hook-a"}
        ttl = check.expires_at - check.created_at
        assert timedelta(days=10) <= ttl < timedelta(days=10, minutes=1)

        queued = (await client.get(f"{URL}/{token}")).json()
        assert (queued["status"], queued["phase"], queued["result"]) == (
            "pending",
            None,
            None,
        )

        assert (await _run(session_factory, check.id))["status"] == "ready"

        body = (await client.get(f"{URL}/{token}")).json()
        assert body["status"] == "ready" and body["error_code"] is None
        assert body["answers"]["hourly_rate"] == 50
        result = body["result"]
        buckets = result["buckets"]
        assert [s["title"] for s in buckets["moves"]] == ["Read the request"]
        assert [s["title"] for s in buckets["to_review"]] == [
            "Draft the reply",
            "File the return",
        ]
        assert [s["title"] for s in buckets["stays"]] == ["Decide on the exception"]
        assert [s["title"] for s in result["out_of_scope"]] == ["Carry the box"]
        reasons = {
            s["title"]: s["reason"]
            for s in [*sum(buckets.values(), []), *result["out_of_scope"]]
        }
        assert reasons["Read the request"]["mode"] == "automatable"
        assert reasons["Read the request"]["codes"] == ["P1", "P3"]
        assert reasons["Draft the reply"] == {
            "mode": "draft_then_review",
            "codes": ["P4"],
            "responsibility": "none",
            "output_type": "draft",
        }
        # Accountability decides, no code does.
        assert reasons["File the return"]["mode"] == "review_required"
        assert reasons["File the return"]["codes"] == []
        assert reasons["File the return"]["responsibility"] == "regulatory"
        assert reasons["Decide on the exception"]["codes"] == ["P6"]
        assert reasons["Carry the box"] == {
            "mode": "blocked_physical",
            "codes": ["B1"],
            "responsibility": "none",
            "output_type": "draft",
        }
        # Four steps in scope, 12 h a year each; half of a reviewed step's
        # hours stays with its checker.
        assert result["hours"] == {
            "total": 48.0,
            "moves": 12.0,
            "to_review": 24.0,
            "stays": 12.0,
            "to_review_after": 12.0,
            "freed": 24.0,
            "unestimated": 0,
        }
        assert result["shares"] == {"moves": 25.0, "to_review": 50.0, "stays": 25.0}
        assert result["money"] == {
            "total": 2400.0,
            "moves": 600.0,
            "to_review": 1200.0,
            "stays": 600.0,
            "to_review_after": 600.0,
            "freed": 1200.0,
            "currency": "EUR",
        }
        assert result["preliminary"] is True
        step = buckets["moves"][0]
        assert (
            step["hours_per_run"],
            step["runs_per_year"],
            step["hours_per_year"],
        ) == (
            1.0,
            12,
            12.0,
        )

    async def test_the_answers_reach_the_model_and_the_rate_does_not(
        self, client, db, seeded, enabled, session_factory
    ):
        seen: list[str] = []

        def _capture(prompt, **kwargs):
            seen.append(prompt)
            return _answer(prompt, **kwargs)

        _token, check = await _start(
            client,
            db,
            answers={"industry": "Logistics", "team_size": 3, "frequency": "weekly"},
        )
        await _run(session_factory, check.id, _capture)
        assert seen and all("Industry: Logistics" in p for p in seen)
        assert all("Team size: 3 people" in p for p in seen)
        assert all("every week" in p for p in seen)

        # Digits no hex uuid of the description is likely to hold: "80" sat in
        # about one description in ten and failed the test at random.
        _token, priced = await _start(client, db, answers={"hourly_rate": 98765.4})
        seen.clear()
        await _run(session_factory, priced.id, _capture)
        assert seen and not any("98765" in p for p in seen)

    async def test_no_rate_no_money(self, client, db, seeded, enabled, session_factory):
        token, check = await _start(client, db)
        await _run(session_factory, check.id)
        result = (await client.get(f"{URL}/{token}")).json()["result"]
        assert result["money"] is None and result["hours"]["total"] == 48.0

    async def test_the_breakdown_runs_in_the_language_of_the_request(
        self, client, db, seeded, enabled, session_factory
    ):
        systems: list[list[str]] = []

        def _capture(prompt, **kwargs):
            systems.append(kwargs["system"])
            return _answer(prompt, **kwargs)

        _token, check = await _start(client, db, locale="de")
        await _run(session_factory, check.id, _capture)
        assert len(systems) == 2
        assert all("Generate ALL content in German" in s[-1] for s in systems)

        systems.clear()
        _token, check = await _start(client, db)
        await _run(session_factory, check.id, _capture)
        assert all("Generate ALL content in English" in s[-1] for s in systems)

    async def test_the_same_input_again_is_served_from_the_breakdown_cache(
        self, client, db, seeded, enabled, session_factory
    ):
        """HRP-921 keys by company: every check shares the sandbox's cache."""
        body = {"description": _text(), "answers": {"industry": "Retail"}}
        first = await client.post(URL, json=body)
        again = await client.post(
            URL, json={**body, "description": f"  {body['description']} "}
        )
        results = []
        for resp, answer in ((first, _answer), (again, _no_call)):
            token = resp.json()["token"]
            check = await db.scalar(
                select(PublicCheck).where(
                    PublicCheck.token_hash == service.hash_token(token)
                )
            )
            assert (await _run(session_factory, check.id, answer))["status"] == "ready"
            results.append((await client.get(f"{URL}/{token}")).json()["result"])
        assert results[0] == results[1]

    async def test_the_result_is_frozen_against_later_edits(
        self, client, db, seeded, enabled, session_factory
    ):
        token, check = await _start(client, db)
        await _run(session_factory, check.id)
        before = (await client.get(f"{URL}/{token}")).json()["result"]
        await db.execute(
            update(WorkStep)
            .where(WorkStep.container_id == check.container_id)
            .values(title="Edited", hours_per_run=5)
        )
        await db.execute(
            delete(WorkStep).where(
                WorkStep.container_id == check.container_id, WorkStep.position == 1
            )
        )
        await db.commit()
        assert (await client.get(f"{URL}/{token}")).json()["result"] == before


class TestFailures:
    async def test_a_failed_run_is_an_error_with_a_code(
        self, client, db, seeded, enabled, session_factory
    ):
        def _fail(*_a, **_k):
            raise RuntimeError("synthetic outage")

        token, check = await _start(client, db)
        assert (await _run(session_factory, check.id, _fail))["status"] == "error"
        body = (await client.get(f"{URL}/{token}")).json()
        assert body["status"] == "error" and body["result"] is None
        assert body["error_code"]

    async def test_a_dead_queue_answers_503_and_fails_the_check(
        self, client, db, seeded, enabled
    ):
        with patch("app.core.task_enqueue.enqueue_task", side_effect=OSError("down")):
            resp = await client.post(URL, json={"description": _text()})
        assert resp.status_code == 503
        assert resp.json()["code"] == "public_check_unavailable"
        rows = (
            await db.execute(
                select(PublicCheck.status)
                .order_by(PublicCheck.created_at.desc())
                .limit(1)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert rows == "error"

    async def test_a_reaped_run_reads_as_an_error_while_the_check_waits(
        self, client, db, seeded, enabled
    ):
        token, check = await _start(client, db)
        await db.execute(
            update(WorkDecompositionSession)
            .where(WorkDecompositionSession.id == check.session_id)
            .values(status="error", error_code="reaped_stuck")
        )
        await db.commit()
        body = (await client.get(f"{URL}/{token}")).json()
        assert (body["status"], body["error_code"]) == ("error", "reaped_stuck")

    async def test_a_run_retried_after_it_finished_changes_nothing(
        self, client, db, seeded, enabled, session_factory
    ):
        token, check = await _start(client, db)
        await _run(session_factory, check.id)
        before = (await client.get(f"{URL}/{token}")).json()
        assert (await _run(session_factory, check.id, _no_call))["status"] == "ready"
        assert (await client.get(f"{URL}/{token}")).json() == before


class TestRedelivery:
    """A worker that dies after its claim leaves the check ``running``; the
    redelivered task (``acks_late``) settles it without a second run."""

    async def _claimed(self, client, db, session_factory):
        token, check = await _start(client, db)
        async with session_factory() as s:
            assert await service.claim_check(s, check.id) == check.session_id
        return token, check

    @pytest.mark.parametrize("applied", [False, True])
    async def test_a_finished_run_is_frozen_on_redelivery(
        self, client, db, seeded, enabled, session_factory, applied
    ):
        token, check = await self._claimed(client, db, session_factory)
        with patch.object(llm_client, "generate_json", side_effect=_answer):
            await work_tasks.execute_session(session_factory, check.session_id)
        if applied:  # it died after materialising, before the snapshot
            async with session_factory() as s:
                run = await s.get(WorkDecompositionSession, check.session_id)
                await work_service.materialise_session(
                    s, run.tenant_id, run.id, idempotency_key=f"public-check:{check.id}"
                )
        assert (await client.get(f"{URL}/{token}")).json()["phase"] == "finishing"
        assert (await _run(session_factory, check.id, _no_call))["status"] == "ready"
        body = (await client.get(f"{URL}/{token}")).json()
        assert body["status"] == "ready"
        assert len(body["result"]["buckets"]["moves"]) == 1

    async def test_a_failed_run_fails_the_check_on_redelivery(
        self, client, db, seeded, enabled, session_factory
    ):
        token, check = await self._claimed(client, db, session_factory)
        await db.execute(
            update(WorkDecompositionSession)
            .where(WorkDecompositionSession.id == check.session_id)
            .values(status="error", error_code="overload")
        )
        await db.commit()
        assert (await _run(session_factory, check.id, _no_call))["status"] == "error"
        row = await db.scalar(
            select(PublicCheck)
            .where(PublicCheck.id == check.id)
            .execution_options(populate_existing=True)
        )
        assert (row.status, row.error_code) == ("error", "overload")

    async def test_a_live_run_is_left_to_its_worker(
        self, client, db, seeded, enabled, session_factory
    ):
        token, check = await self._claimed(client, db, session_factory)
        await db.execute(
            update(WorkDecompositionSession)
            .where(WorkDecompositionSession.id == check.session_id)
            .values(status="running", phase="classifying")
        )
        await db.commit()
        assert (await _run(session_factory, check.id, _no_call))["status"] == "running"
        body = (await client.get(f"{URL}/{token}")).json()
        assert (body["status"], body["phase"]) == ("running", "classifying")

    async def test_the_stuck_cutoff_runs_on_the_run_s_clock(
        self, client, db, seeded, enabled, session_factory
    ):
        """The claim stamps the check once; the run's phase flips refresh
        the run - a long but live run must not read as reaped."""
        token, check = await self._claimed(client, db, session_factory)
        long_ago = datetime.now(UTC) - timedelta(hours=1)
        await db.execute(
            update(PublicCheck)
            .where(PublicCheck.id == check.id)
            .values(updated_at=long_ago)
        )
        await db.execute(
            update(WorkDecompositionSession)
            .where(WorkDecompositionSession.id == check.session_id)
            .values(status="running", phase="classifying")
        )
        await db.commit()
        body = (await client.get(f"{URL}/{token}")).json()
        assert (body["status"], body["phase"]) == ("running", "classifying")
        await db.execute(
            update(WorkDecompositionSession)
            .where(WorkDecompositionSession.id == check.session_id)
            .values(updated_at=long_ago)
        )
        await db.commit()
        body = (await client.get(f"{URL}/{token}")).json()
        assert (body["status"], body["error_code"]) == ("error", "reaped_stuck")


class TestAccess:
    async def test_every_route_is_404_while_the_service_is_off(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(settings, "public_check_enabled", False)
        for resp in (
            await client.post(URL, json={"description": _text()}),
            await client.post(URL, json={}),
            await client.get(f"{URL}/anything"),
        ):
            assert resp.status_code == 404
            assert resp.json()["code"] == "public_check_not_found"

    async def test_unknown_and_expired_links_answer_the_same_404(
        self, client, db, seeded, enabled
    ):
        token, check = await _start(client, db)
        await db.execute(
            update(PublicCheck)
            .where(PublicCheck.id == check.id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()
        expired = await client.get(f"{URL}/{token}")
        unknown = await client.get(f"{URL}/not-a-real-token")
        assert expired.status_code == unknown.status_code == 404
        assert expired.json() == unknown.json()

    async def test_a_check_without_a_term_does_not_expire(
        self, client, db, seeded, enabled
    ):
        token, check = await _start(client, db)
        await db.execute(
            update(PublicCheck)
            .where(PublicCheck.id == check.id)
            .values(expires_at=None)
        )
        await db.commit()
        assert (await client.get(f"{URL}/{token}")).status_code == 200

    async def test_the_check_reads_with_the_title_of_its_container(
        self, client, db, seeded, enabled
    ):
        # HRP-928: the share card names the process the way the sandbox
        # container does - the first line of the description, cut.
        description = f"Month-end close\n{_text()}"
        token, check = await _start(client, db, description=description)
        container = await db.get(WorkContainer, check.container_id)
        body = (await client.get(f"{URL}/{token}")).json()
        assert body["title"] == container.title == "Month-end close"

    async def test_the_check_reads_whether_it_was_dictated(
        self, client, db, seeded, enabled
    ):
        # Review 2.2 D3: "try again" re-sends the input as it came - a
        # dictated description stays marked for the new run's model.
        spoken, _ = await _start(client, db, dictated=True)
        typed, _ = await _start(client, db)
        assert (await client.get(f"{URL}/{spoken}")).json()["dictated"] is True
        assert (await client.get(f"{URL}/{typed}")).json()["dictated"] is False

    async def test_the_token_is_stored_only_as_its_hash(
        self, client, db, seeded, enabled
    ):
        token, check = await _start(client, db)
        assert len(token) >= 40
        assert check.token_hash == hashlib.sha256(token.encode()).hexdigest()
        stored = await db.scalar(
            select(func.count()).where(PublicCheck.token_hash == token)
        )
        assert stored == 0

    async def test_the_input_is_bounded(self, client, enabled):
        too_short = await client.post(
            URL, json={"description": "x" * (schemas.DESCRIPTION_MIN - 1)}
        )
        too_long = await client.post(
            URL, json={"description": "x" * (schemas.DESCRIPTION_MAX + 1)}
        )
        bad_locale = await client.post(
            URL, json={"description": _text(), "locale": "fr"}
        )
        bad_answer = await client.post(
            URL, json={"description": _text(), "answers": {"team_size": 0}}
        )
        long_utm = await client.post(
            URL, json={"description": _text(), "utm": {"source": "x" * 201}}
        )
        for resp in (too_short, too_long, bad_locale, bad_answer, long_utm):
            assert resp.status_code == 422


class TestSandbox:
    async def test_two_first_checks_at_once_make_one_sandbox(self, db, session_factory):
        async def _ensure():
            async with session_factory() as s:
                ids = await service.ensure_sandbox(s)
                await s.commit()
                return ids

        first, second = await asyncio.gather(_ensure(), _ensure())
        assert first == second
        tenants = await db.scalar(
            select(func.count()).where(Tenant.slug == service.SANDBOX_SLUG)
        )
        users = await db.scalar(select(func.count()).where(User.tenant_id == first[0]))
        assert (tenants, users) == (1, 1)

    async def test_an_active_company_holding_the_slug_is_never_the_sandbox(
        self, client, db, seeded, enabled
    ):
        squatter = Tenant(name="Public Check Sandbox", slug=service.SANDBOX_SLUG)
        db.add(squatter)
        await db.commit()
        checks = await db.scalar(select(func.count()).select_from(PublicCheck))
        resp = await client.post(URL, json={"description": _text()})
        assert resp.status_code == 503
        assert resp.json()["code"] == "public_check_unavailable"
        for model in (User, WorkContainer, WorkDecompositionSession):
            count = await db.scalar(
                select(func.count()).where(model.tenant_id == squatter.id)
            )
            assert count == 0, model.__name__
        assert await db.scalar(select(func.count()).select_from(PublicCheck)) == checks

    def test_open_registration_cannot_take_the_slug(self):
        from app.modules.auth.service import _slugify as register_slug
        from app.modules.signup.service import _slugify as signup_slug

        for name in (
            "Public Check Sandbox",
            "public_check_sandbox",
            " Public__Check_Sandbox ",
        ):
            assert register_slug(name) != REAL_SANDBOX_SLUG
            assert signup_slug(name) != REAL_SANDBOX_SLUG

    async def test_the_sandbox_cannot_sign_in_or_receive_mail(self, db):
        tenant_id, user_id = await service.ensure_sandbox(db)
        await db.commit()
        tenant = await db.get(Tenant, tenant_id)
        user = await db.get(User, user_id)
        assert tenant.is_active is False and tenant.is_demo is False
        assert user.is_active is False and user.email_verified_at is None
        assert user.email.endswith(".invalid")


def test_the_run_is_filed_under_the_check():
    """HRP-923's budget and HRP-931's cost per check read these."""
    check_id = uuid.uuid4()

    class Sess:
        id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        container_id = uuid.uuid4()
        params = {
            "billing_action": service.USAGE_ACTION,
            "usage_entity": {"type": "public_check", "id": str(check_id)},
        }

    work_tasks._bind_session_context(Sess())
    ctx = ai_usage_hooks.current()
    assert ctx.action == "public_check.run"
    assert (ctx.entity_type, ctx.entity_id) == ("public_check", check_id)


def test_the_container_title_is_cut_by_characters():
    token = "x" * 300
    assert service._title(token) == "x" * 117 + "..."
    assert service._title("Monthly close\nDetails follow") == "Monthly close"
