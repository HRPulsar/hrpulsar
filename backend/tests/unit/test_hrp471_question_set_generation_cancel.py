"""HRP-471: question-set generation runs in the background and can be cancelled.

The API used to run the model inside the request, so the block could only
show a dead "Generating…" button and nothing could be stopped. Now the
request answers with a placeholder (or the regeneration target flipped to
``regenerating``), the worker fills it, and Cancel acts on that row:

* billing is split: the enqueue prechecks the pinned cost and holds it on
  the set, the worker consumes it in the transaction that turns the row
  ``ready`` and drops the hold — a job that is cancelled or dies only drops
  the hold and is never charged (the real 402 lives in
  ``tests/unit/ee/test_hrp471_question_set_hold.py``);
* a placeholder disappears; a regeneration target settles back to what it
  can show (its questions, or ``failed`` if it never had any);
* a result that arrives after a Cancel is dropped, never written; a job
  whose row was cancelled and re-enqueued does not settle the new job's row;
* whatever raises — before, in or after the model — settles the row.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from app.core import billing_hooks
from app.core.celery_app import celery
from app.main import app
from app.modules.recruitment import question_service
from app.modules.recruitment.models import QuestionSet
from app.modules.recruitment.schemas import GenerateQuestionSetRequest
from app.modules.recruitment.tasks import generation as generation_tasks
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tests.unit.test_hrp205_question_sets import _bootstrap, _gen_questions

pytestmark = pytest.mark.asyncio

LLM = "app.modules.recruitment.question_service._call_llm"
ACTION = "recruitment.generate_question_set"
COST = 8.0


@pytest.fixture(autouse=True)
def billing(monkeypatch) -> dict[str, AsyncMock]:
    """The split-billing hooks, captured (the service reaches them through
    the module, so the no-op/EE binding is irrelevant here)."""
    hooks = {
        "resolve": AsyncMock(return_value=COST),
        "precheck": AsyncMock(),
        "consume": AsyncMock(),
        "reserve": AsyncMock(),
        "release": AsyncMock(return_value=1),
    }
    monkeypatch.setattr(billing_hooks, "resolve_cost", hooks["resolve"])
    monkeypatch.setattr(billing_hooks, "precheck_action", hooks["precheck"])
    monkeypatch.setattr(billing_hooks, "consume_action", hooks["consume"])
    monkeypatch.setattr(billing_hooks, "reserve_action", hooks["reserve"])
    monkeypatch.setattr(billing_hooks, "release_action", hooks["release"])
    return hooks


@pytest.fixture(autouse=True)
def events(monkeypatch) -> AsyncMock:
    """Notification events the service publishes, captured."""
    publish = AsyncMock()
    monkeypatch.setattr(question_service, "_publish_event", publish)
    return publish


def _released(billing: dict[str, AsyncMock]) -> list[uuid.UUID]:
    """Set ids whose generation hold was dropped, in call order."""
    return [c.kwargs["entity_id"] for c in billing["release"].await_args_list]


def _failed_events(events: AsyncMock) -> int:
    return sum(
        1
        for c in events.await_args_list
        if c.args[0] == "recruitment.question_set.failed"
    )


@pytest.fixture
def dispatched(monkeypatch) -> list[tuple]:
    """Celery ``delay`` calls, captured instead of sent."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        generation_tasks.generate_question_set_task,
        "delay",
        lambda *args: calls.append(args),
    )
    return calls


def _cv_id(ctx: dict) -> uuid.UUID:
    return uuid.UUID(str(ctx["cv"]["id"]))


async def _setup(db, tenant, user) -> dict:
    ctx = await _bootstrap(db, tenant, user)
    # Ids captured up front: the worker's settle path rolls the (shared
    # test) session back, which expires the fixture rows — reading
    # ``tenant.id`` afterwards would be a lazy load outside the greenlet.
    ctx["tenant_id"], ctx["user_id"] = tenant.id, user.id
    return ctx


async def _enqueue(db, ctx, **kwargs) -> dict:
    return await question_service.enqueue_question_set_generation(
        db,
        ctx["tenant_id"],
        _cv_id(ctx),
        GenerateQuestionSetRequest(**kwargs),
        current_user_id=ctx["user_id"],
    )


async def _worker(db, ctx, job: dict, **kwargs) -> dict:
    """What the Celery task does with the enqueue's answer."""
    return await question_service._run_generation_job(
        db,
        ctx["tenant_id"],
        _cv_id(ctx),
        GenerateQuestionSetRequest(**kwargs),
        current_user_id=ctx["user_id"],
        into_set_id=uuid.UUID(str(job["id"])),
        expected_version=job["version"],
        cost=COST,
    )


async def _cancel(db, ctx, set_id) -> None:
    await question_service.cancel_question_set_generation(
        db, ctx["tenant_id"], uuid.UUID(str(set_id))
    )


async def _row(db: AsyncSession, set_id) -> QuestionSet | None:
    """The row as the database has it, not as the identity map remembers it."""
    return (
        await db.execute(
            select(QuestionSet)
            .where(QuestionSet.id == uuid.UUID(str(set_id)))
            .options(selectinload(QuestionSet.questions))
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


def _active(row: QuestionSet) -> list:
    return [q for q in row.questions if q.status == "active"]


async def _ready_set(db, ctx) -> dict:
    """A finished first set, made the way the worker makes one."""
    job = await _enqueue(db, ctx, mode="initial")
    with patch(LLM, new_callable=AsyncMock, return_value=_gen_questions(10)):
        return await _worker(db, ctx, job, mode="initial")


class TestEnqueue:
    async def test_answers_with_a_placeholder_and_prechecks_the_cost(
        self, db: AsyncSession, tenant, user, dispatched, billing
    ):
        ctx = await _setup(db, tenant, user)
        with patch(LLM, new_callable=AsyncMock) as llm:
            out = await _enqueue(db, ctx, mode="initial")
        llm.assert_not_called()

        assert out["status"] == "generating"
        assert out["questions"] == []
        assert out["name"], "the tab needs a name before the model answers"
        billing["precheck"].assert_awaited_once()
        assert billing["precheck"].await_args.args[2] == ACTION
        assert billing["precheck"].await_args.kwargs["amount_override"] == COST
        assert billing["precheck"].await_args.kwargs["reserved_entity"] is None
        billing["consume"].assert_not_awaited(), "nothing is charged at the click"
        # The credits are held on the set for as long as the worker may run.
        billing["reserve"].assert_awaited_once()
        hold = billing["reserve"].await_args
        assert hold.args[3] == ACTION
        assert hold.kwargs["entity_type"] == "question_set"
        assert hold.kwargs["entity_id"] == uuid.UUID(str(out["id"]))
        assert hold.kwargs["amount_override"] == COST
        assert hold.kwargs["ttl"] == timedelta(seconds=celery.conf.task_time_limit)
        (call,) = dispatched
        assert call[0] == str(out["id"])
        assert call[5] == out["version"]
        assert call[6] == COST, "the cost is pinned for the worker"

    async def test_a_refused_dispatch_settles_the_placeholder_and_its_hold(
        self, db: AsyncSession, tenant, user, billing, monkeypatch
    ):
        # Review 01.10: the job was sent after the placeholder and its hold
        # were committed; a broker that refused it left the row generating
        # for good, with the credits held.
        def refuse(*_args):
            raise ConnectionError("broker down")

        monkeypatch.setattr(generation_tasks.generate_question_set_task, "delay", refuse)
        ctx = await _setup(db, tenant, user)
        before = {r.id for r in (await db.execute(select(QuestionSet))).scalars()}
        with pytest.raises(ConnectionError):
            await _enqueue(db, ctx, mode="initial")
        rows = [r for r in (await db.execute(select(QuestionSet))).scalars() if r.id not in before]
        (row,) = rows
        row = await _row(db, row.id)
        assert row.status == "failed"
        assert _released(billing) == [row.id]

    async def test_worker_fills_the_same_row_and_charges_once(
        self, db: AsyncSession, tenant, user, dispatched, billing
    ):
        ctx = await _setup(db, tenant, user)
        job = await _enqueue(db, ctx, mode="initial")

        with patch(LLM, new_callable=AsyncMock, return_value=_gen_questions(10)):
            out = await _worker(db, ctx, job, mode="initial")

        assert out["id"] == job["id"], "the placeholder is the set — same tab"
        assert out["status"] == "ready"
        assert len(out["questions"]) == 10
        row = await _row(db, job["id"])
        assert row.llm_provider, "the worker records which model wrote the set"
        billing["consume"].assert_awaited_once()
        assert billing["consume"].await_args.args[3] == ACTION
        assert billing["consume"].await_args.kwargs["amount_override"] == COST
        assert _released(billing) == [uuid.UUID(str(job["id"]))]

    async def test_provenance_is_stamped_with_the_result_not_before(
        self, db: AsyncSession, tenant, user, dispatched
    ):
        ctx = await _setup(db, tenant, user)
        job = await _enqueue(db, ctx, mode="initial")
        seen: dict = {}

        async def model_looks_at_the_row(**_kwargs):
            seen["provider"] = (await _row(db, job["id"])).llm_provider
            return _gen_questions(10)

        with patch(LLM, new_callable=AsyncMock, side_effect=model_looks_at_the_row):
            await _worker(db, ctx, job, mode="initial")

        assert seen["provider"] is None, "nothing is written before the model"
        assert (await _row(db, job["id"])).llm_provider

    async def test_regeneration_keeps_the_questions_while_it_runs(
        self, db: AsyncSession, tenant, user, dispatched, billing
    ):
        ctx = await _setup(db, tenant, user)
        ready = await _ready_set(db, ctx)

        out = await _enqueue(db, ctx, mode="regenerated", target_set_id=ready["id"])

        assert out["id"] == ready["id"]
        assert out["status"] == "regenerating"
        assert len(out["questions"]) == 10, "the old set stays readable"
        # The set's own hold is not counted against its own regeneration.
        assert billing["precheck"].await_args.kwargs["reserved_entity"] == (
            "question_set",
            uuid.UUID(str(ready["id"])),
        )
        with pytest.raises(HTTPException) as exc:
            await _enqueue(db, ctx, mode="regenerated", target_set_id=ready["id"])
        assert exc.value.status_code == 409

    async def test_concurrent_regenerations_cannot_both_start(
        self, db: AsyncSession, tenant, user, dispatched, session_factory
    ):
        """Review: the in-flight check reads the target under lock, so a
        second regeneration waits for the first and then sees it running
        instead of passing on the same stale ``ready``."""
        ctx = await _setup(db, tenant, user)
        ready = await _ready_set(db, ctx)
        set_id = uuid.UUID(str(ready["id"]))

        async with session_factory() as first, session_factory() as second:
            row = await first.scalar(
                select(QuestionSet).where(QuestionSet.id == set_id).with_for_update()
            )
            row.status = "regenerating"  # the first enqueue, not committed yet
            await first.flush()

            racer = asyncio.create_task(
                _enqueue(second, ctx, mode="regenerated", target_set_id=ready["id"])
            )
            await asyncio.sleep(0.3)
            assert not racer.done(), "the second enqueue waits on the row lock"
            await first.commit()

            with pytest.raises(HTTPException) as exc:
                await asyncio.wait_for(racer, timeout=10)
            assert exc.value.status_code == 409


class TestCancel:
    async def test_placeholder_is_removed_and_nothing_is_charged(
        self, db: AsyncSession, tenant, user, dispatched, billing
    ):
        ctx = await _setup(db, tenant, user)
        job = await _enqueue(db, ctx, mode="initial")

        await _cancel(db, ctx, job["id"])

        assert await _row(db, job["id"]) is None
        billing["consume"].assert_not_awaited()
        assert _released(billing) == [uuid.UUID(str(job["id"]))]
        with pytest.raises(HTTPException) as exc:
            await _cancel(db, ctx, job["id"])
        assert exc.value.status_code == 404

    async def test_a_job_cancelled_while_queued_never_asks_the_model(
        self, db: AsyncSession, tenant, user, dispatched, billing
    ):
        ctx = await _setup(db, tenant, user)
        job = await _enqueue(db, ctx, mode="initial")
        await _cancel(db, ctx, job["id"])

        with patch(LLM, new_callable=AsyncMock) as llm:
            out = await _worker(db, ctx, job, mode="initial")

        llm.assert_not_called()
        assert out["status"] == "cancelled"
        billing["consume"].assert_not_awaited()

    async def test_regeneration_target_goes_back_to_ready_with_its_questions(
        self, db: AsyncSession, tenant, user, dispatched
    ):
        ctx = await _setup(db, tenant, user)
        ready = await _ready_set(db, ctx)
        job = await _enqueue(db, ctx, mode="regenerated", target_set_id=ready["id"])

        await _cancel(db, ctx, ready["id"])

        row = await _row(db, ready["id"])
        assert row.status == "ready"
        assert len(_active(row)) == 10
        assert row.version > job["version"], "a late worker result must miss"

    async def test_cancelling_a_retry_of_a_failed_set_leaves_it_failed(
        self, db: AsyncSession, tenant, user, dispatched
    ):
        """Review: a failed placeholder has nothing to show — cancelling its
        Re-generate must not turn it into an empty ``ready`` set."""
        ctx = await _setup(db, tenant, user)
        job = await _enqueue(db, ctx, mode="initial")
        with (
            patch(LLM, new_callable=AsyncMock, side_effect=RuntimeError("llm down")),
            pytest.raises(RuntimeError),
        ):
            await _worker(db, ctx, job, mode="initial")
        assert (await _row(db, job["id"])).status == "failed"

        retry = await _enqueue(db, ctx, mode="regenerated", target_set_id=job["id"])
        assert retry["status"] == "regenerating"
        await _cancel(db, ctx, job["id"])

        assert (await _row(db, job["id"])).status == "failed"

    async def test_cancel_on_a_finished_set_is_409(
        self, db: AsyncSession, tenant, user, dispatched
    ):
        ctx = await _setup(db, tenant, user)
        ready = await _ready_set(db, ctx)
        with pytest.raises(HTTPException) as exc:
            await _cancel(db, ctx, ready["id"])
        assert exc.value.status_code == 409


class TestLateResults:
    async def test_result_for_a_cancelled_placeholder_is_dropped(
        self, db: AsyncSession, tenant, user, dispatched, billing
    ):
        ctx = await _setup(db, tenant, user)
        job = await _enqueue(db, ctx, mode="initial")

        async def cancel_while_the_model_writes(**_kwargs):
            await _cancel(db, ctx, job["id"])
            return _gen_questions(10)

        with patch(
            LLM, new_callable=AsyncMock, side_effect=cancel_while_the_model_writes
        ):
            out = await _worker(db, ctx, job, mode="initial")

        assert out["status"] == "cancelled"
        assert await _row(db, job["id"]) is None
        billing["consume"].assert_not_awaited()

    async def test_result_for_a_cancelled_regeneration_is_dropped(
        self, db: AsyncSession, tenant, user, dispatched, billing
    ):
        ctx = await _setup(db, tenant, user)
        ready = await _ready_set(db, ctx)
        before = {q["text"] for q in ready["questions"]}
        job = await _enqueue(db, ctx, mode="regenerated", target_set_id=ready["id"])
        billing["consume"].reset_mock()

        async def cancel_while_the_model_writes(**_kwargs):
            await _cancel(db, ctx, ready["id"])
            return _gen_questions(12)

        with patch(
            LLM, new_callable=AsyncMock, side_effect=cancel_while_the_model_writes
        ):
            out = await _worker(
                db,
                ctx,
                job,
                mode="regenerated",
                target_set_id=ready["id"],
            )

        assert out["status"] == "cancelled"
        after = await _row(db, ready["id"])
        assert after.status == "ready"
        assert {q.text for q in _active(after)} == before
        billing["consume"].assert_not_awaited()

    async def test_a_dead_first_job_does_not_settle_a_re_enqueued_set(
        self, db: AsyncSession, tenant, user, dispatched, billing, events
    ):
        """Review: regenerate A → cancel → regenerate B → A's model call
        fails. A must not flip the row (now B's) to ready; B then lands and
        is charged exactly once."""
        ctx = await _setup(db, tenant, user)
        ready = await _ready_set(db, ctx)
        billing["consume"].reset_mock()
        billing["release"].reset_mock()
        job_a = await _enqueue(db, ctx, mode="regenerated", target_set_id=ready["id"])
        job_b: dict = {}

        async def cancel_and_re_enqueue_then_die(**_kwargs):
            await _cancel(db, ctx, ready["id"])
            job_b.update(
                await _enqueue(db, ctx, mode="regenerated", target_set_id=ready["id"])
            )
            raise RuntimeError("model down for A")

        with (
            patch(
                LLM, new_callable=AsyncMock, side_effect=cancel_and_re_enqueue_then_die
            ),
            pytest.raises(RuntimeError),
        ):
            await _worker(
                db,
                ctx,
                job_a,
                mode="regenerated",
                target_set_id=ready["id"],
            )

        row = await _row(db, ready["id"])
        assert row.status == "regenerating", "A's failure must not settle B's row"
        assert row.version == job_b["version"]
        assert _failed_events(events) == 0, "A's failure is not news to anyone"
        # Only the cancel dropped a hold so far; B's is still there.
        assert _released(billing) == [uuid.UUID(str(ready["id"]))]

        with patch(LLM, new_callable=AsyncMock, return_value=_gen_questions(12)):
            out = await _worker(
                db,
                ctx,
                job_b,
                mode="regenerated",
                target_set_id=ready["id"],
            )
        assert out["status"] == "ready"
        assert len(out["questions"]) == 12
        billing["consume"].assert_awaited_once()
        assert len(_released(billing)) == 2, "B's landing drops B's hold"


class TestJobFailure:
    async def test_placeholder_is_marked_failed_and_not_charged(
        self, db: AsyncSession, tenant, user, dispatched, billing, events
    ):
        ctx = await _setup(db, tenant, user)
        job = await _enqueue(db, ctx, mode="initial")

        with (
            patch(LLM, new_callable=AsyncMock, side_effect=RuntimeError("llm down")),
            pytest.raises(RuntimeError),
        ):
            await _worker(db, ctx, job, mode="initial")

        assert (await _row(db, job["id"])).status == "failed"
        billing["consume"].assert_not_awaited()
        assert _released(billing) == [uuid.UUID(str(job["id"]))]
        assert _failed_events(events) == 1

    async def test_regeneration_target_is_restored(
        self, db: AsyncSession, tenant, user, dispatched
    ):
        ctx = await _setup(db, tenant, user)
        ready = await _ready_set(db, ctx)
        job = await _enqueue(db, ctx, mode="regenerated", target_set_id=ready["id"])

        with (
            patch(LLM, new_callable=AsyncMock, side_effect=RuntimeError("llm down")),
            pytest.raises(RuntimeError),
        ):
            await _worker(
                db,
                ctx,
                job,
                mode="regenerated",
                target_set_id=ready["id"],
            )

        row = await _row(db, ready["id"])
        assert row.status == "ready"
        assert len(_active(row)) == 10

    async def test_a_job_that_dies_before_the_model_settles_the_row(
        self, db: AsyncSession, tenant, user, dispatched, billing, events, monkeypatch
    ):
        """Review: the resume vanished (or any pre-model step raised) —
        the row must not stay ``generating`` for good."""
        ctx = await _setup(db, tenant, user)
        job = await _enqueue(db, ctx, mode="initial")

        async def resume_gone(*_a, **_k):
            raise RuntimeError("resume deleted meanwhile")

        monkeypatch.setattr(question_service, "_load_generation_inputs", resume_gone)
        with pytest.raises(RuntimeError):
            await _worker(db, ctx, job, mode="initial")

        assert (await _row(db, job["id"])).status == "failed"
        billing["consume"].assert_not_awaited()
        assert _failed_events(events) == 1


_FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
_COMPONENT = (
    _FRONTEND / "src" / "components" / "recruitment" / "interview-question-sets.tsx"
)


@pytest.mark.skipif(not _COMPONENT.exists(), reason="frontend tree not present")
def test_the_block_calls_urls_the_app_serves():
    """The Cancel button's literal has to match the mounted route."""
    urls = re.findall(
        r"/v1/question-sets/\$\{[^}]+\}/cancel", _COMPONENT.read_text(encoding="utf-8")
    )
    referenced = {"/api" + re.sub(r"\$?\{[^}]*\}", "{}", u) for u in urls}
    mounted = {
        re.sub(r"\{[^}]*\}", "{}", getattr(route, "path", "")) for route in app.routes
    }
    assert "/api/v1/question-sets/{}/cancel" in referenced
    assert referenced <= mounted, sorted(referenced - mounted)
