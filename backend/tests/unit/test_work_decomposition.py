"""HRP-755 / HRP-775: AI decomposition sessions — one active run per
container, the worker's two phases (split, then classify the fixed list)
with their happy and failure paths, the reaper, idempotent apply, the
comment-driven reclassification of one step, and the few-shot corpus
staying English and on-catalog."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from app.core import billing_hooks
from app.core.errors import AppError
from app.modules.ai import llm_client
from app.modules.primitives import catalog_data
from app.modules.work import _examples, prompts, service, tasks
from app.modules.work.models import WorkDecompositionSession, WorkStep
from app.modules.work.schemas import (
    ContainerCreate,
    DecompositionSchema,
    ReclassifyRequest,
    SessionRead,
    StepCreate,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Phase one (split): the codes here are the first guess the second phase
# replaces - deliberately wrong, so a test that sees them knows phase two
# did not run.
_PAYLOAD = {
    "steps": [
        {
            "title": "Intake of the request through a structured form",
            "primitives": ["P5"],
            "responsibility": "none",
            "output_type": "draft",
        },
        {
            "title": "Signature by the authorised signatory",
            "primitives": ["P6"],
            "responsibility": "none",
            "output_type": "draft",
        },
        {
            "title": "Check against the playbook",
            "primitives": ["P4"],
            "responsibility": "none",
            "output_type": "draft",
            "hours_per_run": 2,
            "runs_per_year": 250,
        },
    ]
}
# Phase two (classify): one entry per step, in order, with the evidence
# per code (HRP-776).
_CLASSES = {
    "steps": [
        {
            "primitives": ["P1"],
            "responsibility": "none",
            "output_type": "draft",
            "evidence": [
                {"code": "P1", "quote": "logs the request", "confidence": 0.9}
            ],
        },
        # No capability, no evidence - but the key is there: the schema
        # requires it since v2work.v8, so an answer shaped like the split
        # examples fails validation instead of landing without confidence.
        {
            "primitives": [],
            "responsibility": "regulatory",
            "output_type": "external_change",
            "evidence": [],
        },
        # P99 is not in the catalog: dropped with its evidence, the step is
        # kept. P2 is a guess below the tentative threshold.
        {
            "primitives": ["P2", "P99"],
            "responsibility": "none",
            "output_type": "draft",
            "evidence": [
                {"code": "P2", "quote": "against our playbook", "confidence": 0.6},
                {"code": "P99", "quote": "x", "confidence": 1.0},
                {"code": "P2", "quote": "a duplicate is ignored", "confidence": 0.1},
            ],
        },
    ]
}


def _ok(*_args, schema=None, **_kwargs):
    """Answers by the schema asked for: the split or the classification."""
    if schema is DecompositionSchema:
        return schema.model_validate(_PAYLOAD)
    return schema.model_validate(_CLASSES)


def _fail(*_args, **_kwargs):
    raise RuntimeError("synthetic LLM outage")


@pytest.fixture
async def primitives(db: AsyncSession):
    await db.execute(catalog_data.seed_insert())
    await db.commit()


async def _container(db: AsyncSession, tenant, user, **overrides):
    data = ContainerCreate(
        **{
            "type": "process",
            "title": "Contract review",
            "description": "Legal reviews every counterparty contract before signature.",
            **overrides,
        }
    )
    return await service.create_container(db, tenant.id, data, user_id=user.id)


class TestCorpus:
    def test_examples_are_english_and_on_catalog(self):
        codes = {p["code"] for p in catalog_data.PRIMITIVES}
        for question, answer in _examples.EXAMPLES:
            assert question["title"] and question["description"]
            assert answer["steps"], question["title"]
            for step in answer["steps"]:
                assert set(step["primitives"]) <= codes, step
                assert step["responsibility"] in prompts.RESPONSIBILITIES
                assert step["output_type"] in prompts.OUTPUT_TYPES
        # Cyrillic anywhere in backend/** fails the public sync guard
        # (scripts/sync_repos.sh); the translated corpus is the file most
        # likely to pick some up.
        modules = Path(_examples.__file__).parent.parent
        for path in list(modules.glob("work/*.py")) + list(
            modules.glob("primitives/*.py")
        ):
            assert not re.search(r"[\u0400-\u04ff]", path.read_text()), path.name

    def test_system_prompt_lists_every_code_and_the_rules(self):
        system = prompts.build_system_prompt(catalog_data.PRIMITIVES)
        for p in catalog_data.PRIMITIVES:
            assert f"- {p['code']} - " in system
        for phrase in (
            "do not improve",
            "no capability at all",
            "kind: boundary",
            "property of the step",
            # rounds 2-3 (decision 2026-09-09): sign-off inside the step,
            # content-weighing approval is P6, boundaries, posting is P3,
            # responsibility hints
            "stays inside that step",
            "is a judgment: P6",
            "party outside the company",
            "Assigning people, collecting opinions",
            "Posting transactions to accounts",
            "Registering an object in a system",
            "`formal` when someone other than the doer",
            "Example 6 output",
        ):
            assert phrase in system, phrase
        # HRP-775: the second pass carries the same rules plus the task
        # that pins the list.
        classify = prompts.build_classify_system_prompt(catalog_data.PRIMITIVES)
        assert classify.startswith(system)
        assert "exactly one entry per step" in classify
        user = prompts.build_classify_user_prompt(
            {"type": "process", "title": "T", "description": "D", "goal": None},
            [{"title": "One", "description": "first"}, {"title": "Two"}],
            only=1,
            comment="It is a supplier conversation",
        )
        assert "1. One - first\n2. Two" in user
        assert "Classify only step 2: Two" in user
        assert "Comment from the company on this step: It is a supplier" in user
        assert "Classify all 2 steps" in prompts.build_classify_user_prompt(
            {"title": "T"}, [{"title": "One"}, {"title": "Two"}]
        )
        # The few-shot corpus must not contradict the rules it accompanies.
        for _question, answer in _examples.EXAMPLES:
            for step in answer["steps"]:
                if "P7" in step["primitives"]:
                    assert "manager" not in step["title"].lower(), step["title"]


class TestSessions:
    async def test_one_active_per_container(self, db, tenant, user, primitives):
        c = await _container(db, tenant, user)
        first = await service.create_session(db, tenant.id, user.id, c.id)
        assert first.status == "pending"
        assert first.base_snapshot["container"]["title"] == "Contract review"
        assert first.params["billing_action"] == "work_decomposition.start"
        # The rollback of the refused insert expires every loaded row, the
        # fixtures included; keep plain ids around.
        tenant_id, user_id, container_id, first_id = tenant.id, user.id, c.id, first.id

        with pytest.raises(HTTPException) as exc:
            await service.create_session(db, tenant_id, user_id, container_id)
        assert exc.value.status_code == 409

        await service.cancel_session(db, tenant_id, first_id)
        second = await service.create_session(db, tenant_id, user_id, container_id)
        assert second.id != first_id

        # A drafted run nobody applied holds the slot with its own message.
        second.status = "ready"
        await db.commit()
        with pytest.raises(HTTPException) as exc:
            await service.create_session(db, tenant_id, user_id, container_id)
        assert (
            exc.value.detail == AppError("work_decomposition_pending_apply", 409).detail
        )

    async def test_archived_container_takes_no_session(
        self, db, tenant, user, primitives
    ):
        c = await _container(db, tenant, user)
        c.status = "archived"
        await db.commit()
        with pytest.raises(HTTPException) as exc:
            await service.create_session(db, tenant.id, user.id, c.id)
        assert exc.value.status_code == 409

    async def test_needs_a_description(self, db, tenant, user, primitives):
        c = await _container(db, tenant, user, description="   ")
        with pytest.raises(HTTPException) as exc:
            await service.create_session(db, tenant.id, user.id, c.id)
        assert exc.value.status_code == 422

    async def test_the_read_keeps_the_price_to_itself(
        self, db, tenant, user, primitives
    ):
        """``params`` carries the price pinned for the charge; that is our
        bookkeeping, not something a reader of the breakdown is shown."""
        c = await _container(db, tenant, user)
        sess = await service.create_session(db, tenant.id, user.id, c.id, cost=12.5)
        assert sess.params["cost"] == 12.5
        assert SessionRead.model_validate(sess).params == {
            "billing_action": service.BILLING_ACTION_START
        }

    async def test_cancel_revokes_the_task(
        self, db, tenant, user, primitives, monkeypatch
    ):
        from app.core import celery_app as celery_module

        revoked: list[str] = []
        monkeypatch.setattr(
            celery_module.celery.control,
            "revoke",
            lambda task_id, **kw: revoked.append(task_id),
        )
        c = await _container(db, tenant, user)
        sess = await service.create_session(db, tenant.id, user.id, c.id)
        sess.celery_task_id = "task-1"
        await db.commit()
        cancelled = await service.cancel_session(db, tenant.id, sess.id)
        assert cancelled.status == "cancelled"
        assert cancelled.phase is None
        assert revoked == ["task-1"]
        # Idempotent: a second cancel neither fails nor revokes again.
        await service.cancel_session(db, tenant.id, sess.id)
        assert revoked == ["task-1"]


class TestWorker:
    async def test_ready_payload_keeps_only_catalog_codes(
        self, db, tenant, user, primitives, session_factory
    ):
        c = await _container(db, tenant, user)
        sess = await service.create_session(db, tenant.id, user.id, c.id)
        with patch.object(llm_client, "generate_json", side_effect=_ok):
            result = await tasks.execute_session(session_factory, sess.id)
        assert result["status"] == "ready"
        await db.refresh(sess)
        assert sess.status == "ready"
        assert sess.llm_model
        steps = sess.payload["steps"]
        # Codes, responsibility and output type come from phase two; the
        # titles and the scales from phase one.
        assert [s["primitives"] for s in steps] == [["P1"], [], ["P2"]]
        assert steps[1]["responsibility"] == "regulatory"
        assert steps[1]["output_type"] == "external_change"
        assert [s["title"] for s in steps] == [s["title"] for s in _PAYLOAD["steps"]]
        assert (steps[2]["hours_per_run"], steps[2]["runs_per_year"]) == (2, 250)
        assert (steps[0]["hours_per_run"], steps[0]["runs_per_year"]) == (None, None)
        assert sess.phase is None
        # Evidence follows the kept codes: one entry per code, unknown and
        # duplicate entries dropped.
        assert steps[0]["evidence"] == [
            {"code": "P1", "quote": "logs the request", "confidence": 0.9}
        ]
        assert steps[1]["evidence"] == []
        assert steps[2]["evidence"] == [
            {"code": "P2", "quote": "against our playbook", "confidence": 0.6}
        ]

    def test_normalise_cuts_long_quotes(self):
        out = tasks._normalise(
            [
                {
                    "title": "t",
                    "primitives": ["P1"],
                    "evidence": [{"code": "P1", "quote": "q" * 900, "confidence": 1}],
                }
            ],
            {"P1"},
        )
        assert len(out["steps"][0]["evidence"][0]["quote"]) == tasks.QUOTE_MAX

    def test_normalise_drops_estimates_that_are_not_numbers(self):
        """``json`` accepts NaN and Infinity, and the estimates are
        unbounded on purpose - an unusable one is dropped like any other
        out-of-range value, never raised over a paid answer."""
        out = tasks._normalise(
            [
                {
                    "title": "t",
                    "primitives": [],
                    "hours_per_run": float("nan"),
                    "runs_per_year": float("nan"),
                },
                {
                    "title": "u",
                    "primitives": [],
                    "hours_per_run": float("inf"),
                    "runs_per_year": float("inf"),
                },
            ],
            set(),
        )
        assert [(s["hours_per_run"], s["runs_per_year"]) for s in out["steps"]] == [
            (None, None),
            (None, None),
        ]

    async def test_second_phase_keeps_count_and_order(
        self, db, tenant, user, primitives, session_factory, monkeypatch
    ):
        """A classification with the wrong number of entries is a parse
        error: nothing is paired with the wrong step and nothing is billed.
        Meanwhile the row shows the phase in flight."""
        monkeypatch.setattr(tasks, "_max_attempts", lambda _settings: 1)
        c = await _container(db, tenant, user)
        sess = await service.create_session(db, tenant.id, user.id, c.id)
        phases: list[str | None] = []

        async def _short(*_a, schema=None, **_k):
            async with session_factory() as other:
                row = await other.get(WorkDecompositionSession, sess.id)
                phases.append(row.phase)
            if schema is DecompositionSchema:
                return schema.model_validate(_PAYLOAD)
            return schema.model_validate({"steps": _CLASSES["steps"][:2]})

        with patch.object(llm_client, "generate_json", side_effect=_short):
            result = await tasks.execute_session(session_factory, sess.id)
        assert result["status"] == "error"
        assert phases == ["splitting", "classifying"]
        await db.refresh(sess)
        assert (sess.error_code, sess.payload, sess.phase) == (
            "parse_error",
            None,
            None,
        )
        assert "classifying" in sess.error_message

    async def test_cancel_between_phases_is_not_billed(
        self, db, tenant, user, primitives, session_factory
    ):
        c = await _container(db, tenant, user)
        sess = await service.create_session(db, tenant.id, user.id, c.id)
        consumed: list[str] = []

        async def _split_then_cancel(*_a, schema=None, **_k):
            assert schema is DecompositionSchema, "phase two must not run"
            async with session_factory() as other:
                row = await other.get(WorkDecompositionSession, sess.id)
                row.status = "cancelled"
                await other.commit()
            return schema.model_validate(_PAYLOAD)

        async def _consume(*_a, **_k):
            consumed.append("x")

        with (
            patch.object(llm_client, "generate_json", side_effect=_split_then_cancel),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
        ):
            result = await tasks.execute_session(session_factory, sess.id)
        assert result["status"] == "cancelled"
        assert consumed == []
        await db.refresh(sess)
        assert sess.payload is None

    async def test_failure_marks_error_without_payload(
        self, db, tenant, user, primitives, session_factory, monkeypatch
    ):
        monkeypatch.setattr(tasks, "_max_attempts", lambda _settings: 1)
        c = await _container(db, tenant, user)
        sess = await service.create_session(db, tenant.id, user.id, c.id)
        with patch.object(llm_client, "generate_json", side_effect=_fail):
            result = await tasks.execute_session(session_factory, sess.id)
        assert result["status"] == "error"
        await db.refresh(sess)
        assert sess.status == "error"
        assert sess.error_code == "service_error"
        assert sess.payload is None
        # The container is free for the next attempt.
        await service.create_session(db, tenant.id, user.id, c.id)

    async def test_cancel_before_llm_skips_the_call(
        self, db, tenant, user, primitives, session_factory
    ):
        c = await _container(db, tenant, user)
        sess = await service.create_session(db, tenant.id, user.id, c.id)
        sess.status = "cancelled"
        await db.commit()

        def _boom(*_a, **_k):
            raise AssertionError("LLM must not be called")

        with patch.object(llm_client, "generate_json", side_effect=_boom):
            result = await tasks.execute_session(session_factory, sess.id)
        assert result["status"] == "cancelled"

    async def test_cancel_during_llm_is_not_billed(
        self, db, tenant, user, primitives, session_factory
    ):
        c = await _container(db, tenant, user)
        sess = await service.create_session(db, tenant.id, user.id, c.id)
        consumed: list[str] = []

        async def _cancel_then_answer(*_a, schema=None, **_k):
            if schema is DecompositionSchema:
                return schema.model_validate(_PAYLOAD)
            # The cancel lands during the second call.
            async with session_factory() as other:
                row = await other.get(WorkDecompositionSession, sess.id)
                assert row is not None
                row.status = "cancelled"
                await other.commit()
            return schema.model_validate(_CLASSES)

        async def _consume(*_a, **_k):
            consumed.append("x")

        with (
            patch.object(llm_client, "generate_json", side_effect=_cancel_then_answer),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
        ):
            result = await tasks.execute_session(session_factory, sess.id)
        assert result["status"] == "cancelled"
        assert consumed == []
        await db.refresh(sess)
        assert sess.status == "cancelled"
        assert sess.payload is None

    async def test_start_reserves_credits_and_the_failure_releases(
        self, auth_client, db, tenant, user, primitives, session_factory, monkeypatch
    ):
        """HRP-547: the one-active-run guard is per container, so without a
        hold a tenant starts one run per container and every one of them
        passes the same balance check before the first worker deducts
        anything. The hold is taken at the start and dropped by the run
        that ends without a charge."""
        from app.core import task_enqueue

        class _Result:
            id = "celery-task-id"

        monkeypatch.setattr(task_enqueue, "enqueue_task", lambda *a, **k: _Result())
        monkeypatch.setattr(tasks, "_max_attempts", lambda _settings: 1)
        reserved: list[dict] = []
        released: list[dict] = []

        async def _reserve(_db, _tenant_id, _user_id, action, **kw):
            reserved.append({"action": action, **kw})

        async def _release(_db, _tenant_id, **kw):
            released.append(kw)
            return 1

        c = await _container(db, tenant, user)
        with (
            patch.object(billing_hooks, "reserve_action", side_effect=_reserve),
            patch.object(billing_hooks, "release_action", side_effect=_release),
        ):
            started = await auth_client.post(
                "/api/work/decomposition/sessions", json={"container_id": str(c.id)}
            )
            assert started.status_code == 201, started.text
            session_id = uuid.UUID(started.json()["id"])
            [hold] = reserved
            # The hold names the run and is priced like the charge it will
            # settle; it lives as long as the reaper leaves the run alone.
            assert hold["action"] == service.BILLING_ACTION_START
            assert hold["entity_type"] == service.DECOMPOSITION_RESERVE_ENTITY
            assert hold["entity_id"] == session_id
            assert hold["ttl"] == timedelta(minutes=tasks.REAPER_STUCK_AGE_MINUTES)
            assert hold["amount_override"] == await billing_hooks.resolve_cost(
                db, tenant.id, service.BILLING_ACTION_START
            )
            assert released == []

            with patch.object(llm_client, "generate_json", side_effect=_fail):
                result = await tasks.execute_session(session_factory, session_id)
        assert result["status"] == "error"
        assert released == [
            {
                "entity_type": service.DECOMPOSITION_RESERVE_ENTITY,
                "entity_id": session_id,
                "action": service.BILLING_ACTION_START,
            }
        ]

    async def test_failure_message_keeps_the_provider_text_out(
        self, db, tenant, user, primitives, session_factory, monkeypatch
    ):
        """``error_message`` is shown to everyone who reads the container;
        a provider message can quote the prompt or a response body from
        whatever the endpoint really is."""
        monkeypatch.setattr(tasks, "_max_attempts", lambda _settings: 1)
        c = await _container(db, tenant, user)
        sess = await service.create_session(db, tenant.id, user.id, c.id)
        with patch.object(llm_client, "generate_json", side_effect=_fail):
            await tasks.execute_session(session_factory, sess.id)
        await db.refresh(sess)
        assert sess.error_message == "Decomposition failed while splitting"

    async def test_reaper_flips_only_stale_running_rows(
        self, db, tenant, user, primitives, session_factory
    ):
        c = await _container(db, tenant, user)
        stale_sess = await service.create_session(db, tenant.id, user.id, c.id)
        fresh_c = await _container(db, tenant, user, title="Fresh")
        fresh_sess = await service.create_session(db, tenant.id, user.id, fresh_c.id)
        stale = datetime.now(UTC) - timedelta(
            minutes=tasks.REAPER_STUCK_AGE_MINUTES + 5
        )
        await db.execute(
            WorkDecompositionSession.__table__.update()
            .where(WorkDecompositionSession.id == stale_sess.id)
            .values(status="running", updated_at=stale)
        )
        await db.execute(
            WorkDecompositionSession.__table__.update()
            .where(WorkDecompositionSession.id == fresh_sess.id)
            .values(status="running")
        )
        # A pending row the broker lost holds the slot just the same.
        lost_c = await _container(db, tenant, user, title="Lost")
        lost_sess = await service.create_session(db, tenant.id, user.id, lost_c.id)
        await db.execute(
            WorkDecompositionSession.__table__.update()
            .where(WorkDecompositionSession.id == lost_sess.id)
            .values(updated_at=stale)
        )
        await db.commit()
        result = await tasks._reap_stuck_sessions_body(session_factory)
        assert result["reaped"] >= 2
        await db.refresh(stale_sess)
        await db.refresh(fresh_sess)
        await db.refresh(lost_sess)
        assert (stale_sess.status, stale_sess.error_code) == ("error", "reaped_stuck")
        assert (lost_sess.status, lost_sess.error_code) == ("error", "reaped_stuck")
        assert fresh_sess.status == "running"


class TestReclassify:
    async def _two_steps(self, db, tenant, user):
        c = await _container(db, tenant, user)
        first = await service.create_step(
            db,
            tenant.id,
            c.id,
            StepCreate(title="Log the request", primitive_codes=["P1"]),
        )
        second = await service.create_step(
            db,
            tenant.id,
            c.id,
            StepCreate(title="Talk to the supplier", primitive_codes=["P5", "P8"]),
        )
        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        return c, first, second

    async def test_reclassify_changes_only_its_step(self, db, tenant, user, primitives):
        c, first, second = await self._two_steps(db, tenant, user)
        # A confirmed code the model keeps loses its confirmation: the
        # reclassification is a new claim.
        await service.confirm_step_primitive(db, tenant.id, second["id"], "P5")
        seen: list[tuple[str, int]] = []

        def _answer(prompt, *_a, schema=None, **_k):
            seen.append((prompt, schema.model_fields["steps"].metadata[0].min_length))
            return schema.model_validate(
                {
                    "steps": [
                        {
                            "primitives": ["P5", "P7", "P99"],
                            "responsibility": "reputational",
                            "output_type": "external_change",
                            "evidence": [
                                {
                                    "code": "P5",
                                    "quote": "written up",
                                    "confidence": 0.6,
                                },
                                {
                                    "code": "P7",
                                    "quote": "negotiation",
                                    "confidence": 0.7,
                                },
                            ],
                        }
                    ]
                }
            )

        with patch.object(llm_client, "generate_json", side_effect=_answer):
            updated = await service.reclassify_step(
                db,
                tenant.id,
                second["id"],
                ReclassifyRequest(comment="An open-ended negotiation with a supplier"),
            )
        prompt, count = seen[0]
        assert count == 1
        assert "1. Log the request\n2. Talk to the supplier" in prompt
        assert "Classify only step 2: Talk to the supplier" in prompt
        assert "open-ended negotiation" in prompt
        assert updated["primitive_codes"] == ["P5", "P7"]
        assert updated["capabilities"] == [
            {
                "code": "P5",
                "confidence": 0.6,
                "quote": "written up",
                "confirmed": False,
            },
            {
                "code": "P7",
                "confidence": 0.7,
                "quote": "negotiation",
                "confirmed": False,
            },
        ]
        assert updated["responsibility"] == "reputational"
        assert updated["output_type"] == "external_change"
        assert updated["state"] == "tenant_edited"
        steps = {s["id"]: s for s in await service.list_steps(db, tenant.id, c.id)}
        assert steps[first["id"]]["primitive_codes"] == ["P1"]
        assert steps[first["id"]]["state"] == "accepted"
        await db.refresh(c)
        assert c.status == "draft"

    async def test_reclassify_failure_leaves_the_step(
        self, db, tenant, user, primitives
    ):
        c, _first, second = await self._two_steps(db, tenant, user)
        with (
            patch.object(llm_client, "generate_json", side_effect=_fail),
            pytest.raises(HTTPException) as exc,
        ):
            await service.reclassify_step(
                db, tenant.id, second["id"], ReclassifyRequest(comment="x")
            )
        assert exc.value.status_code == 502
        # The provider's own words stay in the log, not in the answer.
        assert "synthetic LLM outage" not in str(exc.value.detail)
        steps = {s["id"]: s for s in await service.list_steps(db, tenant.id, c.id)}
        assert steps[second["id"]]["primitive_codes"] == ["P5", "P8"]
        assert steps[second["id"]]["state"] == "accepted"


class TestApply:
    async def _ready_session(self, db, tenant, user, container):
        sess = await service.create_session(db, tenant.id, user.id, container.id)
        sess.status = "ready"
        sess.payload = {
            "steps": [
                {**s, **c, "primitives": [p for p in c["primitives"] if p != "P99"]}
                for s, c in zip(_PAYLOAD["steps"], _CLASSES["steps"], strict=True)
            ]
        }
        await db.commit()
        return sess

    async def test_apply_is_idempotent_and_replaces_steps(
        self, db, tenant, user, primitives
    ):
        c = await _container(db, tenant, user)
        manual = await service.create_step(
            db, tenant.id, c.id, StepCreate(title="Old manual step")
        )
        sess = await self._ready_session(db, tenant, user, c)

        with pytest.raises(HTTPException) as exc:
            await service.apply_session(
                db, tenant.id, uuid.uuid4(), idempotency_key="k1"
            )
        assert exc.value.status_code == 404

        # The manual step is ``tenant_edited``, so the replace is a discard
        # and has to be confirmed.
        result = await service.apply_session(
            db, tenant.id, sess.id, idempotency_key="k1", force=True
        )
        assert len(result["created_steps"]) == 3
        steps = await service.list_steps(db, tenant.id, c.id)
        assert [s["position"] for s in steps] == [1, 2, 3]
        assert {s["state"] for s in steps} == {"system_suggested"}
        assert steps[2]["primitive_codes"] == ["P2"]
        assert (steps[2]["hours_per_run"], steps[2]["runs_per_year"]) == (2, 250)
        # HRP-776: the links carry the model's confidence and quote.
        assert steps[0]["capabilities"] == [
            {
                "code": "P1",
                "confidence": 0.9,
                "quote": "logs the request",
                "confirmed": False,
            }
        ]
        assert steps[2]["capabilities"][0]["confidence"] == 0.6
        assert manual["id"] not in {s["id"] for s in steps}
        await db.refresh(c)
        assert c.source == "ai"

        again = await service.apply_session(
            db, tenant.id, sess.id, idempotency_key="k1", force=True
        )
        assert again == result
        assert len(await service.list_steps(db, tenant.id, c.id)) == 3

        with pytest.raises(HTTPException) as exc:
            await service.apply_session(db, tenant.id, sess.id, idempotency_key="k2")
        assert exc.value.status_code == 409

    async def test_apply_refuses_another_tenants_session(
        self, db, tenant, user, primitives
    ):
        """The tenant is part of the lookup, not a check on the row it
        returned: a stranger's session is never locked in the first place."""
        from app.modules.company.models import Tenant

        c = await _container(db, tenant, user)
        sess = await self._ready_session(db, tenant, user, c)
        other = Tenant(
            name=f"Other {uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:8]}"
        )
        db.add(other)
        await db.commit()
        with pytest.raises(HTTPException) as exc:
            await service.apply_session(db, other.id, sess.id, idempotency_key="k1")
        assert exc.value.status_code == 404

    async def test_apply_drops_codes_retired_since_ready(
        self, db, tenant, user, primitives
    ):
        from app.modules.primitives.models import Primitive

        c = await _container(db, tenant, user)
        sess = await self._ready_session(db, tenant, user, c)
        await db.execute(
            Primitive.__table__.update()
            .where(Primitive.code == "P2")
            .values(retired_in="v9")
        )
        await db.commit()
        try:
            await service.apply_session(db, tenant.id, sess.id, idempotency_key="k1")
            steps = await service.list_steps(db, tenant.id, c.id)
            assert [s["primitive_codes"] for s in steps] == [["P1"], [], []]
        finally:
            await db.execute(
                Primitive.__table__.update()
                .where(Primitive.code == "P2")
                .values(retired_in=None)
            )
            await db.commit()

    async def test_apply_refuses_archived_and_resets_accepted(
        self, db, tenant, user, primitives
    ):
        c = await _container(db, tenant, user)
        await service.create_step(db, tenant.id, c.id, StepCreate(title="old"))
        await service.accept_container(
            db, tenant.id, c.id, user_id=user.id, can_manage=True
        )
        sess = await self._ready_session(db, tenant, user, c)
        await service.apply_session(db, tenant.id, sess.id, idempotency_key="k1")
        await db.refresh(c)
        # A new breakdown is a new draft: accept has to happen again.
        assert c.status == "draft"

        # Archived after the draft was ready: the paid answer stays, apply waits.
        sess2 = await self._ready_session(db, tenant, user, c)
        c.status = "archived"
        await db.commit()
        with pytest.raises(HTTPException) as exc:
            await service.apply_session(db, tenant.id, sess2.id, idempotency_key="k2")
        assert exc.value.status_code == 409

    async def test_apply_will_not_silently_discard_paid_work(
        self, db, tenant, user, primitives
    ):
        """A generated SKILL.md and the hire needs of the steps that go:
        the first blocks the replace until it is confirmed, the second is
        pruned with the steps so coverage stops offering the same handoff."""
        from app.modules.work.models import WorkHireNeed, WorkStepSkill

        c = await _container(db, tenant, user)
        kept = await service.create_step(
            db, tenant.id, c.id, StepCreate(title="Sign the file")
        )
        db.add(
            WorkStepSkill(
                tenant_id=tenant.id,
                step_id=kept["id"],
                status="ready",
                content="# SKILL.md",
                catalog_version=catalog_data.CATALOG_VERSION,
            )
        )
        need = WorkHireNeed(
            tenant_id=tenant.id,
            container_id=c.id,
            step_ids=[str(kept["id"])],
            label="hire",
        )
        db.add(need)
        await db.commit()
        need_id = need.id
        sess = await self._ready_session(db, tenant, user, c)

        with pytest.raises(HTTPException) as exc:
            await service.apply_session(db, tenant.id, sess.id, idempotency_key="k1")
        assert exc.value.status_code == 409
        assert exc.value.code == "work_apply_would_discard"
        # Refused, not half-done: the draft and the steps are untouched.
        assert len(await service.list_steps(db, tenant.id, c.id)) == 1
        await db.refresh(sess)
        assert sess.status == "ready"

        await service.apply_session(
            db, tenant.id, sess.id, idempotency_key="k1", force=True
        )
        assert len(await service.list_steps(db, tenant.id, c.id)) == 3
        # Nothing points at the deleted step any more.
        assert await db.get(WorkHireNeed, need_id) is None

    async def test_apply_needs_ready(self, db, tenant, user, primitives):
        c = await _container(db, tenant, user)
        sess = await service.create_session(db, tenant.id, user.id, c.id)
        with pytest.raises(HTTPException) as exc:
            await service.apply_session(db, tenant.id, sess.id, idempotency_key="k1")
        assert exc.value.status_code == 409
        assert (
            await db.execute(select(WorkStep.id).where(WorkStep.container_id == c.id))
        ).first() is None


class TestRouter:
    async def test_start_get_apply_cancel(
        self, auth_client, db, tenant, user, primitives, monkeypatch
    ):
        from app.core import task_enqueue

        class _Result:
            id = "celery-task-id"

        enqueued: list[dict] = []

        def fake_enqueue(task, *args, **kwargs):
            enqueued.append({"args": args, **kwargs})
            return _Result()

        monkeypatch.setattr(task_enqueue, "enqueue_task", fake_enqueue)

        c = await _container(db, tenant, user)
        container_id = str(c.id)
        started = await auth_client.post(
            "/api/work/decomposition/sessions", json={"container_id": container_id}
        )
        assert started.status_code == 201, started.text
        body = started.json()
        assert body["status"] == "pending"
        assert body["celery_task_id"] == "celery-task-id"
        assert enqueued[0]["module"] == "work"
        assert enqueued[0]["action"] == "work_decomposition.start"

        assert (
            await auth_client.post(
                "/api/work/decomposition/sessions", json={"container_id": container_id}
            )
        ).status_code == 409

        latest = await auth_client.get(
            f"/api/work/containers/{container_id}/decomposition/latest"
        )
        assert latest.status_code == 200
        assert latest.json()["id"] == body["id"]

        not_ready = await auth_client.post(
            f"/api/work/decomposition/sessions/{body['id']}/apply",
            json={"idempotency_key": "key-12345"},
        )
        assert not_ready.status_code == 409

        cancelled = await auth_client.delete(
            f"/api/work/decomposition/sessions/{body['id']}"
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        foreign = await auth_client.get(
            f"/api/work/decomposition/sessions/{uuid.uuid4()}"
        )
        assert foreign.status_code == 404

        # Role gates (section 4.1): managers read; admin / hr start, apply, cancel.
        from tests.unit.test_work_containers import _user_with_role

        # The 409 above rolled back and expired the fixtures.
        await db.refresh(tenant)
        # HRP-810: the manager reads because the process is open to the
        # company; a restricted one would be a 404 before any role check.
        from app.modules.work.models import WorkContainer
        from sqlalchemy import update

        await db.execute(
            update(WorkContainer)
            .where(WorkContainer.id == uuid.UUID(container_id))
            .values(visibility="company")
        )
        await db.commit()
        _, manager_token = await _user_with_role(db, tenant, "manager")
        auth_client.headers["Authorization"] = f"Bearer {manager_token}"
        assert (
            await auth_client.get(f"/api/work/decomposition/sessions/{body['id']}")
        ).status_code == 200
        assert (
            await auth_client.post(
                "/api/work/decomposition/sessions", json={"container_id": container_id}
            )
        ).status_code == 403
        assert (
            await auth_client.post(
                f"/api/work/decomposition/sessions/{body['id']}/apply",
                json={"idempotency_key": "key-12345"},
            )
        ).status_code == 403
        assert (
            await auth_client.delete(f"/api/work/decomposition/sessions/{body['id']}")
        ).status_code == 403
        # An unknown step is absent whoever asks.
        assert (
            await auth_client.post(
                f"/api/work/steps/{uuid.uuid4()}/reclassify", json={"comment": "x"}
            )
        ).status_code == 404


def test_normalise_drops_out_of_range_hours():
    """W6: a number outside the CHECK bounds is dropped, not clamped, and
    the rest of the paid answer survives."""
    steps = tasks._normalise(
        [
            {"title": "a", "primitives": [], "hours_per_run": 500, "runs_per_year": 0},
            {"title": "b", "primitives": [], "hours_per_run": 0.5, "runs_per_year": 12},
            {"title": "c", "primitives": []},
        ],
        set(),
    )["steps"]
    assert (steps[0]["hours_per_run"], steps[0]["runs_per_year"]) == (None, None)
    assert (steps[1]["hours_per_run"], steps[1]["runs_per_year"]) == (0.5, 12)
    assert (steps[2]["hours_per_run"], steps[2]["runs_per_year"]) == (None, None)


class TestClassificationContract:
    def test_evidence_is_mandatory(self):
        """HRP-776: the few-shot answers carry no evidence, so an optional
        key let a model that copied them land every confidence NULL."""
        from app.modules.work.schemas import classification_schema
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            classification_schema(1).model_validate({"steps": [{"primitives": ["P1"]}]})
        ok = classification_schema(1).model_validate(
            {
                "steps": [
                    {
                        "primitives": ["P1"],
                        "evidence": [{"code": "P1", "quote": "q", "confidence": 0.9}],
                    }
                ]
            }
        )
        assert ok.steps[0].evidence[0].code == "P1"
        classify = prompts.build_classify_system_prompt(catalog_data.PRIMITIVES)
        assert "an answer without `evidence` is rejected" in classify

    def test_fractional_runs_are_rounded_not_fatal(self):
        from app.modules.work.schemas import DecompositionSchema

        assert tasks._hours({"hours_per_run": 1, "runs_per_year": 11.6}) == {
            "hours_per_run": 1,
            "runs_per_year": 12,
        }
        assert tasks._hours({"hours_per_run": 1, "runs_per_year": 0.4}) == {
            "hours_per_run": 1,
            "runs_per_year": None,
        }
        parsed = DecompositionSchema.model_validate(
            {"steps": [{"title": "Biennial audit", "runs_per_year": 0.5}]}
        )
        assert parsed.steps[0].runs_per_year == 0.5
