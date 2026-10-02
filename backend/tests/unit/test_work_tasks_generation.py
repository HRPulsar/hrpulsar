"""HRP-951 / HRP-949 / HRP-921: what the breakdown worker sends and keeps.

The prompt layout - the shared prefix alone in the first system block, the
same bytes on the split, the classification and a reclassification - and
the pinned sampling; the first pass's codes kept in the payload next to the
final ones; the result cache that answers a repeated text without a model
call and without a charge.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from app.core import billing_hooks
from app.core.redis import redis_client
from app.modules.ai import llm_client
from app.modules.primitives import catalog_data
from app.modules.work import prompts, service, tasks
from app.modules.work.schemas import ContainerCreate, DecompositionSchema

pytestmark = pytest.mark.asyncio

PRIMITIVES = [p for p in catalog_data.PRIMITIVES if not p.get("retired_in")]
CONTAINER = {
    "type": "process",
    "title": "Contract review",
    "description": "Legal reviews every counterparty contract before signature.",
    "goal": None,
}
_SPLIT = {
    "steps": [
        {"title": "Intake", "primitives": ["P5"], "responsibility": "none"},
        {"title": "Signature", "primitives": ["P6"], "responsibility": "none"},
    ]
}
_CLASSES = {
    "steps": [
        {
            "primitives": ["P1"],
            "responsibility": "none",
            "output_type": "draft",
            "evidence": [{"code": "P1", "quote": "logs", "confidence": 0.9}],
        },
        {
            "primitives": [],
            "responsibility": "regulatory",
            "output_type": "external_change",
            "evidence": [],
        },
    ]
}


def _settings() -> SimpleNamespace:
    return SimpleNamespace(content_language="en", effort_level="balanced")


def _answer(*_args, schema=None, **_kwargs):
    """By the schema asked for: the split, or as many classifications as
    the schema pins (the whole list, or the one step of a reclassification)."""
    if schema is DecompositionSchema:
        return schema.model_validate(_SPLIT)
    count = schema.model_fields["steps"].metadata[0].min_length
    return schema.model_validate({"steps": _CLASSES["steps"][:count]})


class TestPromptLayout:
    async def test_split_classify_and_reclassify_share_the_first_block(self):
        """HRP-951: the block the provider caches is the same bytes on all
        three calls; the classify task and the language directive follow it."""
        seen: list[dict] = []

        async def _capture(prompt, **kwargs):
            seen.append(kwargs)
            return _answer(prompt, **kwargs)

        call = {
            "primitives": PRIMITIVES,
            "tenant_settings": _settings(),
            "credentials": None,
            "model": "claude-sonnet-5",
            "max_attempts": 1,
        }
        with patch.object(llm_client, "generate_json", side_effect=_capture):
            steps = await tasks.split_steps(CONTAINER, **call)
            await tasks.classify_steps(CONTAINER, steps, **call)
            await tasks.classify_steps(
                CONTAINER, steps, **call, only=0, comment="a scripted call"
            )
        prefix = prompts.build_system_prompt(PRIMITIVES)
        assert len(prefix) > 20_000  # the part worth caching
        assert [k["system"][0] for k in seen] == [prefix] * 3
        directive = tasks._language(_settings())
        assert [k["system"][-1] for k in seen] == [directive] * 3
        assert seen[1]["system"][1] == seen[2]["system"][1]
        assert "Task of this call" in seen[1]["system"][1]
        # Joined, the blocks are the v8 system prompt byte for byte: the
        # layout changes nothing for a provider without prompt caching.
        assert "\n\n".join(seen[1]["system"]) == "\n\n".join(
            [prompts.build_classify_system_prompt(PRIMITIVES), directive]
        )
        # HRP-921 (a): pinned sampling on every call, from the one constant.
        assert [(k["temperature"], k["top_p"], k["seed"]) for k in seen] == [
            (0.0, 1.0, 0)
        ] * 3
        # HRP-995: the split, the classification and the one-step
        # reclassification think before they answer, and the thinking
        # counts against max_tokens - all three ask for the breakdown
        # budget, which stays on the non-streaming path.
        assert [k["max_tokens"] for k in seen] == [tasks.BREAKDOWN_MAX_TOKENS] * 3
        assert (
            8192
            < tasks.BREAKDOWN_MAX_TOKENS
            <= llm_client._ANTHROPIC_STREAM_THRESHOLD_TOKENS
        )


@pytest.fixture
async def seeded(db, monkeypatch):
    await db.execute(catalog_data.seed_insert())
    await db.commit()
    # The keys these tests write are unique per run; let them go quickly.
    monkeypatch.setattr(tasks, "BREAKDOWN_CACHE_TTL_S", 60)


async def _session(db, tenant, user, description: str):
    """A container with the given text and a pending run over it. The text
    carries a fresh token unless the test wants two runs of the same text:
    the result cache (HRP-921) is keyed by it and outlives a test run."""
    data = ContainerCreate(
        type="process", title="Contract review", description=description
    )
    container = await service.create_container(db, tenant.id, data, user_id=user.id)
    return await service.create_session(db, tenant.id, user.id, container.id)


def _fresh_text() -> str:
    return f"Legal reviews every counterparty contract before signature. {uuid.uuid4()}"


class TestPayload:
    async def test_first_pass_codes_stay_next_to_the_final_ones(
        self, db, tenant, user, seeded, session_factory
    ):
        """HRP-949: the first call's codes are kept per step, filtered to the
        catalog like the final ones; the final codes still win on screen."""
        sess = await _session(db, tenant, user, _fresh_text())
        with patch.object(llm_client, "generate_json", side_effect=_answer):
            result = await tasks.execute_session(session_factory, sess.id)
        assert result["status"] == "ready"
        await db.refresh(sess)
        steps = sess.payload["steps"]
        assert [s["first_pass_codes"] for s in steps] == [["P5"], ["P6"]]
        assert [s["primitives"] for s in steps] == [["P1"], []]


def _key(tenant: str = "tenant-a", **container) -> str:
    base = {"type": "process", "title": "Contract review", "goal": None}
    return tasks.breakdown_cache_key(
        {**base, **container},
        tenant_id=tenant,
        language="English.",
        model="claude-sonnet-5",
        catalog="P1 Draft",
    )


class TestResultCache:
    def test_key_ignores_spacing_and_compatibility_forms_but_not_case(self):
        """HRP-921 (b): NFKC, trimmed, whitespace collapsed; the case, the
        company, the model, the language and the catalog all tell keys apart."""
        plain = _key(description="Legal reviews every counterparty contract.")
        assert (
            _key(description="  Legal   reviews\nevery counterparty\tcontract. ")
            == plain
        )
        assert (
            _key(
                description="Legal reviews every counterparty contract.".replace(
                    "fi", "ﬁ"
                )
            )
            == plain
        )
        assert _key(description="legal reviews every counterparty contract.") != plain
        # Another company's identical text is its own key: it pays for its
        # own breakdown and cannot tell that anyone analysed the text before.
        same_text_other_tenant = _key(
            tenant="tenant-b", description="Legal reviews every counterparty contract."
        )
        assert same_text_other_tenant != plain
        text = {"type": "process", "title": "Contract review", "goal": None}
        text["description"] = "Legal reviews every counterparty contract."
        assert (
            tasks.breakdown_cache_key(
                text,
                tenant_id="tenant-a",
                language="German.",
                model="claude-sonnet-5",
                catalog="P1 Draft",
            )
            != plain
        )
        assert (
            tasks.breakdown_cache_key(
                text,
                tenant_id="tenant-a",
                language="English.",
                model="gpt-4o",
                catalog="P1 Draft",
            )
            != plain
        )
        assert (
            tasks.breakdown_cache_key(
                text,
                tenant_id="tenant-a",
                language="English.",
                model="claude-sonnet-5",
                catalog="P1 Draft\nP2 Review",
            )
            != plain
        )

    async def test_the_same_text_again_is_served_without_a_call_or_a_charge(
        self, db, tenant, user, seeded, session_factory
    ):
        text = _fresh_text()
        consumed: list[str] = []
        released: list[dict] = []

        async def _consume(*_a, **_k):
            consumed.append("x")

        async def _release(_db, _tenant_id, **kw):
            released.append(kw)
            return 1

        first = await _session(db, tenant, user, text)
        with (
            patch.object(llm_client, "generate_json", side_effect=_answer),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
        ):
            assert (await tasks.execute_session(session_factory, first.id))[
                "status"
            ] == "ready"
        assert consumed == ["x"]

        async def _no_call(*_a, **_k):
            raise AssertionError("the model must not be called on a cache hit")

        # Another container, the same text with different spacing.
        again = await _session(db, tenant, user, f"  {text.replace(' ', '  ')} ")
        with (
            patch.object(llm_client, "generate_json", side_effect=_no_call),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
            patch.object(billing_hooks, "release_action", side_effect=_release),
        ):
            assert (await tasks.execute_session(session_factory, again.id))[
                "status"
            ] == "ready"
        assert consumed == ["x"]  # nothing more
        assert len(released) == 1  # the hold of the run goes
        await db.refresh(first)
        await db.refresh(again)
        assert again.payload == first.payload
        assert again.status == "ready" and again.phase is None
        assert again.llm_model == first.llm_model

    def test_key_follows_the_catalog_the_model_reads(self):
        """A primitive's title, scope or verdict can change while every code
        stays - and a quarterly verdict revision does so without bumping
        CATALOG_VERSION (review 01.10): the key carries the rendered
        catalog, not its version."""
        text = {"type": "process", "title": "Contract review", "goal": None}
        keys = {
            tasks.breakdown_cache_key(
                text,
                tenant_id="tenant-a",
                language="English.",
                model="claude-sonnet-5",
                catalog=catalog,
            )
            for catalog in ("P1 Draft (AI verdict: assists)", "P1 Draft (AI verdict: replaces)")
        }
        assert len(keys) == 2

    async def test_a_corrupt_entry_is_a_miss_not_a_failure(
        self, db, tenant, user, seeded, session_factory
    ):
        """Garbage under the key: a normal, charged call - and the good
        answer replaces the garbage."""
        key = f"work:breakdown:test-{uuid.uuid4().hex}"
        async with redis_client() as client:
            await client.set(key, "not json {", ex=60)
        consumed: list[str] = []

        async def _consume(*_a, **_k):
            consumed.append("x")

        sess = await _session(db, tenant, user, _fresh_text())
        with (
            patch.object(tasks, "breakdown_cache_key", return_value=key),
            patch.object(llm_client, "generate_json", side_effect=_answer),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
        ):
            result = await tasks.execute_session(session_factory, sess.id)
        assert result["status"] == "ready"
        assert consumed == ["x"]
        async with redis_client() as client:
            stored = await client.get(key)
        assert json.loads(stored)["steps"]

    async def test_a_redis_outage_is_a_miss_not_a_failure(
        self, db, tenant, user, seeded, session_factory
    ):
        @asynccontextmanager
        async def _broken():
            raise ConnectionError("redis down")
            yield  # pragma: no cover

        consumed: list[str] = []

        async def _consume(*_a, **_k):
            consumed.append("x")

        sess = await _session(db, tenant, user, _fresh_text())
        with (
            patch.object(tasks, "redis_client", _broken),
            patch.object(llm_client, "generate_json", side_effect=_answer),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
        ):
            result = await tasks.execute_session(session_factory, sess.id)
        assert result["status"] == "ready"
        assert consumed == ["x"]  # a real call, charged as such
