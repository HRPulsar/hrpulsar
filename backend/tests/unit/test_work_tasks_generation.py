"""HRP-951 / HRP-949 / HRP-921 / HRP-1208 / HRP-1239: what the breakdown worker
sends and keeps.

The prompt layout - the shared prefix alone in the first system block, the
same bytes on the split, the classification and a reclassification - and
the pinned sampling; the first pass's codes kept in the payload next to the
final ones; the result cache that answers a repeated text without a model
call and without a charge; the check that the steps came back in the
content language, with its one retry.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from app.core import billing_hooks
from app.core.errors import AppError
from app.core.redis import redis_client
from app.modules.ai import llm_client
from app.modules.ai_settings.models import TenantAISettings
from app.modules.demo.seed_data_work import WORK_CONTAINERS
from app.modules.primitives import catalog_data
from app.modules.work import prompts, service, tasks
from app.modules.work.schemas import (
    ContainerCreate,
    DecomposedStep,
    DecompositionSchema,
)

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
        # HRP-1239: the split, the one call that writes prose, is also told
        # that the description's language does not decide the steps'.
        assert [k["system"][-1] for k in seen] == [
            f"{directive} {prompts.LANGUAGE_RULE}",
            directive,
            directive,
        ]
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


ONBOARDING = next(spec for spec in WORK_CONTAINERS if spec.get("preset_steps"))


async def _onboarding_run(
    db, tenant, user, *, demo: bool, description: str, preset_language=None
):
    """The demo's onboarding process with the given description, its seeded
    goal, and a pending run over it - started as the free preset run when
    ``preset_language`` is given, the way the start endpoint records it."""
    tenant.is_demo = demo
    await db.commit()
    data = ContainerCreate(
        type="process",
        title=ONBOARDING["title"],
        description=description,
        goal=ONBOARDING["goal"],
    )
    container = await service.create_container(db, tenant.id, data, user_id=user.id)
    return await service.create_session(
        db, tenant.id, user.id, container.id, preset_language=preset_language
    )


class TestDemoPreset:
    """HRP-1208: the demo's own process, unchanged, is answered with the
    steps prepared with the seed - no model call, no charge. An edited text,
    or a company that is not a demo sandbox, gets a real run."""

    async def _run(self, session_factory, sess, *, model_allowed: bool):
        consumed: list[str] = []
        released: list[dict] = []

        async def _consume(*_a, **_k):
            consumed.append("x")

        async def _release(_db, _tenant_id, **kw):
            released.append(kw)
            return 1

        async def _no_call(*_a, **_k):
            raise AssertionError("the model must not be called on the preset")

        with (
            patch.object(
                llm_client,
                "generate_json",
                side_effect=_answer if model_allowed else _no_call,
            ),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
            patch.object(billing_hooks, "release_action", side_effect=_release),
        ):
            result = await tasks.execute_session(session_factory, sess.id)
        return result, consumed, released

    async def test_the_unchanged_preset_is_answered_without_a_call_or_a_charge(
        self, db, tenant, user, seeded, session_factory
    ):
        # Spacing is not an edit: the text is compared normalised.
        text = "  " + ONBOARDING["description"].replace(". ", ".\n\n", 2) + " "
        sess = await _onboarding_run(db, tenant, user, demo=True, description=text)
        result, consumed, released = await self._run(
            session_factory, sess, model_allowed=False
        )
        assert result["status"] == "ready"
        assert consumed == []
        assert len(released) == 1  # the hold, had one been taken, goes
        await db.refresh(sess)
        assert sess.status == "ready" and sess.phase is None
        # No model answered: the run names none.
        assert sess.llm_model is None
        steps = sess.payload["steps"]
        assert [s["title"] for s in steps] == [
            s["title"] for s in ONBOARDING["preset_steps"]
        ]
        # The shape the worker writes for a model's answer, so apply and
        # the screen take it as one.
        for step in steps:
            DecomposedStep.model_validate(step)
            assert step["evidence"] == []
            assert step["first_pass_codes"] == step["primitives"]

        applied = await service.apply_session(
            db, tenant.id, sess.id, idempotency_key="preset-apply-1"
        )
        assert len(applied["created_steps"]) == len(ONBOARDING["preset_steps"])

    async def test_an_edited_description_is_generated_and_charged(
        self, db, tenant, user, seeded, session_factory
    ):
        sess = await _onboarding_run(
            db,
            tenant,
            user,
            demo=True,
            description=f"{ONBOARDING['description']} {uuid.uuid4()}",
        )
        result, consumed, _ = await self._run(session_factory, sess, model_allowed=True)
        assert result["status"] == "ready"
        assert consumed == ["x"]
        await db.refresh(sess)
        assert [s["title"] for s in sess.payload["steps"]] == ["Intake", "Signature"]

    async def test_a_company_with_the_same_text_is_generated_and_charged(
        self, db, tenant, user, seeded, session_factory
    ):
        sess = await _onboarding_run(
            db, tenant, user, demo=False, description=ONBOARDING["description"]
        )
        result, consumed, _ = await self._run(session_factory, sess, model_allowed=True)
        assert result["status"] == "ready"
        assert consumed == ["x"]

    async def test_the_language_of_the_start_holds_until_the_worker(
        self, db, tenant, user, seeded, session_factory
    ):
        """The content language changes between the start and the worker:
        the preset is matched in the language the start found it in, so the
        free start is not answered by a model call."""
        sess = await _onboarding_run(
            db,
            tenant,
            user,
            demo=True,
            description=ONBOARDING["description"],
            preset_language="en",
        )
        assert sess.params["preset"] is True
        db.add(TenantAISettings(tenant_id=tenant.id, content_language="de"))
        await db.commit()

        result, consumed, _ = await self._run(
            session_factory, sess, model_allowed=False
        )
        assert result["status"] == "ready"
        assert consumed == []
        await db.refresh(sess)
        assert [s["title"] for s in sess.payload["steps"]] == [
            s["title"] for s in ONBOARDING["preset_steps"]
        ]

    async def test_a_free_start_that_misses_the_preset_is_refused_without_a_call(
        self, db, tenant, user, seeded, session_factory
    ):
        """Started free - no precheck, no hold - but the snapshot is not the
        preset: the balance is asked before any model call, and a refusal
        ends the run with its code."""
        sess = await _onboarding_run(
            db,
            tenant,
            user,
            demo=True,
            description=f"{ONBOARDING['description']} {uuid.uuid4()}",
            preset_language="en",
        )

        async def _refuse(*_a, **_k):
            raise AppError("credits_demo_quota_exhausted", 429)

        with patch.object(billing_hooks, "precheck_action", side_effect=_refuse):
            result, consumed, _ = await self._run(
                session_factory, sess, model_allowed=False
            )
        assert result["status"] == "error"
        assert consumed == []
        await db.refresh(sess)
        assert (sess.status, sess.error_code) == (
            "error",
            "credits_demo_quota_exhausted",
        )

    async def test_a_free_start_that_misses_the_preset_is_prechecked_then_paid(
        self, db, tenant, user, seeded, session_factory
    ):
        """The same miss with a balance that covers it: the precheck comes
        first, then the model, then the charge."""
        order: list[str] = []
        sess = await _onboarding_run(
            db,
            tenant,
            user,
            demo=True,
            description=f"{ONBOARDING['description']} {uuid.uuid4()}",
            preset_language="en",
        )

        async def _precheck(*_a, **_k):
            order.append("precheck")

        def _model(*args, **kwargs):
            order.append("model")
            return _answer(*args, **kwargs)

        async def _consume(*_a, **_k):
            order.append("consume")

        with (
            patch.object(billing_hooks, "precheck_action", side_effect=_precheck),
            patch.object(llm_client, "generate_json", side_effect=_model),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
        ):
            result = await tasks.execute_session(session_factory, sess.id)
        assert result["status"] == "ready"
        assert order[0] == "precheck" and order[-1] == "consume"
        assert "model" in order


# HRP-1239. Russian sample text as escapes - the public sync guard refuses
# Cyrillic in this file: "Intake of the request", "Signing of the contract",
# "A lawyer checks every counterparty contract before signing.", a bank
# product's name, and "Code review in" / "Rollout to" for the mixed titles.
_RU_INTAKE = "\u041f\u0440\u0438\u0451\u043c \u0437\u0430\u044f\u0432\u043a\u0438"
_RU_SIGNING = (
    "\u041f\u043e\u0434\u043f\u0438\u0441\u0430\u043d\u0438\u0435 "
    "\u0434\u043e\u0433\u043e\u0432\u043e\u0440\u0430"
)
_RU_DESCRIPTION = (
    "\u042e\u0440\u0438\u0441\u0442 \u043f\u0440\u043e\u0432\u0435\u0440\u044f\u0435\u0442 "
    "\u043a\u0430\u0436\u0434\u044b\u0439 \u0434\u043e\u0433\u043e\u0432\u043e\u0440 "
    "\u043a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442\u0430 "
    "\u043f\u0435\u0440\u0435\u0434 "
    "\u043f\u043e\u0434\u043f\u0438\u0441\u0430\u043d\u0438\u0435\u043c."
)
_RU_BANK = (
    "\u0421\u0431\u0435\u0440\u0431\u0430\u043d\u043a "
    "\u0411\u0438\u0437\u043d\u0435\u0441 \u041e\u043d\u043b\u0430\u0439\u043d"
)
_RU_REVIEW_IN = "\u0420\u0435\u0432\u044c\u044e \u043a\u043e\u0434\u0430 \u0432"
_RU_ROLLOUT_TO = "\u0412\u044b\u043a\u043b\u0430\u0434\u043a\u0430 \u043d\u0430"
_RU_SPLIT = {
    "steps": [
        {"title": _RU_INTAKE},
        {"title": _RU_SIGNING, "description": _RU_DESCRIPTION},
    ]
}


def _titled(*titles: str) -> list[dict]:
    return [{"title": title} for title in titles]


class TestContentLanguage:
    """HRP-1239: the steps are written in the content language whatever
    language the description is in. The split's answer is read by its
    script; one in the wrong language is asked for once more, and a second
    one ends the run as a failed generation - not charged, its hold
    released, nothing cached."""

    def test_the_check_reads_the_script_of_the_generated_text(self):
        russian, english = _RU_SPLIT["steps"], _SPLIT["steps"]
        assert tasks._in_content_language(english, "en")
        assert tasks._in_content_language(english, "de")
        assert tasks._in_content_language(russian, "ru")
        assert not tasks._in_content_language(russian, "en")
        assert not tasks._in_content_language(russian, "de")
        assert not tasks._in_content_language(english, "ru")
        # A name quoted from a Russian description is not a wrong language...
        assert tasks._in_content_language(
            _titled(
                "Intake of the invoice",
                "Approval by the CFO",
                f"Payment via {_RU_BANK}",
            ),
            "en",
        )
        # Titles kept as the source words them, over translated
        # descriptions, are the wrong language: the titles answer for
        # themselves, however many letters the descriptions bring.
        assert not tasks._in_content_language(
            [
                {
                    "title": _RU_INTAKE,
                    "description": "The request is registered and gets a number.",
                },
                {
                    "title": _RU_SIGNING,
                    "description": "A lawyer checks every counterparty contract first.",
                },
            ],
            "en",
        )
        # ...nor are the Latin names and terms Russian is written with.
        assert tasks._in_content_language(
            _titled(
                "Code review",
                f"{_RU_REVIEW_IN} GitHub",
                f"{_RU_ROLLOUT_TO} staging",
            ),
            "ru",
        )
        # A code the directive does not know is answered in English.
        assert not tasks._in_content_language(russian, "fr")
        # No letters, nothing to judge by.
        assert tasks._in_content_language([], "en")
        assert tasks._in_content_language(_titled("2026"), "ru")

    def test_a_quoted_name_passes_an_untranslated_step_does_not(self):
        """Review of HRP-1239: a breakdown has few descriptions, so one
        sentence naming a Russian document is most of their letters; and a
        few titles left in Russian among ten are no majority of anything."""
        english = [f"Step {n} of the purchase" for n in range(10)]
        assert tasks._in_content_language(
            [
                *_titled(*english[:-1]),
                {"title": english[-1], "description": f"Per {_RU_BANK}."},
            ],
            "en",
        )
        partial = _titled(
            *english[:6], _RU_INTAKE, _RU_SIGNING, _RU_INTAKE, _RU_SIGNING
        )
        assert not tasks._in_content_language(partial, "en")
        assert not tasks._in_content_language(partial, "de")
        # Steps that each carry a Latin name: a share of the whole still
        # judges a short breakdown.
        assert not tasks._in_content_language(
            _titled(
                f"{_RU_REVIEW_IN} GitHub",
                f"{_RU_ROLLOUT_TO} staging",
                f"{_RU_REVIEW_IN} GitLab",
            ),
            "en",
        )
        # Two steps, one of them naming a long Russian product, are not
        # judged as a whole: the name would be most of their letters.
        payroll = "1\u0421:\u0417\u0430\u0440\u043f\u043b\u0430\u0442\u0430 \u0438 \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u043f\u0435\u0440\u0441\u043e\u043d\u0430\u043b\u043e\u043c"
        assert tasks._in_content_language(
            _titled(f"Export from {payroll}", "Pay"), "en"
        )
        assert tasks._in_content_language(
            _titled(f"Export aus {payroll}", "Zahlen"), "de"
        )
        # A name of a few letters may stand for itself.
        assert tasks._in_content_language(
            _titled(*english[:9], "\u0421\u0431\u0435\u0440"), "en"
        )
        # Russian: English titles over one Russian description are English.
        assert not tasks._in_content_language(
            [
                *_titled(*english[:-1]),
                {"title": english[-1], "description": _RU_DESCRIPTION},
            ],
            "ru",
        )

    async def test_an_answer_in_the_wrong_language_is_asked_for_once_more(self):
        """The reported case: the description in Russian, the content
        language English, and the model mirrors the description."""
        asked: list[str] = []
        sampling: list[tuple] = []

        async def _mirrors_then_obeys(prompt, *, schema=None, **kwargs):
            asked.append(prompt)
            sampling.append(
                tuple(kwargs.get(k) for k in ("temperature", "top_p", "seed"))
            )
            return schema.model_validate(_RU_SPLIT if len(asked) == 1 else _SPLIT)

        with patch.object(llm_client, "generate_json", side_effect=_mirrors_then_obeys):
            steps = await tasks.split_steps(
                {**CONTAINER, "description": _RU_DESCRIPTION},
                primitives=PRIMITIVES,
                tenant_settings=_settings(),
                credentials=None,
                model="claude-sonnet-5",
                max_attempts=1,
            )
        assert [s["title"] for s in steps] == ["Intake", "Signature"]
        first, second = asked
        # Every split is told the description's language decides nothing;
        # only the retry is told what was wrong with the answer before it.
        assert first.endswith(prompts.LANGUAGE_RULE)
        assert second == f"{first}\n\n{prompts.LANGUAGE_CORRECTION}"
        # The retry samples: pinned, it would come back the same.
        assert sampling[0] == (0.0, 1.0, 0)
        assert sampling[1] != sampling[0]

    async def test_no_retry_for_a_run_nobody_wants_any_more(self):
        calls: list[str] = []

        async def _mirrors(prompt, *, schema=None, **_kwargs):
            calls.append(prompt)
            return schema.model_validate(_RU_SPLIT)

        async def _cancelled() -> bool:
            return False

        with (
            patch.object(llm_client, "generate_json", side_effect=_mirrors),
            pytest.raises(RuntimeError, match="cancelled"),
        ):
            await tasks.split_steps(
                CONTAINER,
                primitives=PRIMITIVES,
                tenant_settings=_settings(),
                credentials=None,
                model="claude-sonnet-5",
                max_attempts=1,
                still_wanted=_cancelled,
            )
        assert len(calls) == 1

    async def _run_retried(
        self, db, tenant, user, session_factory, answers, monkeypatch
    ):
        """A run whose split answers ``answers`` in turn; what was charged,
        how many splits were asked for, and what went to the cache."""
        consumed: list[str] = []
        splits: list[str] = []
        remembered: list[dict] = []

        async def _consume(*_a, **_k):
            consumed.append("x")

        async def _remember(_key, payload):
            remembered.append(payload)

        def _split_in_turn(prompt, *, schema=None, **kwargs):
            if schema is not DecompositionSchema:
                return _answer(prompt, schema=schema, **kwargs)
            splits.append(prompt)
            return schema.model_validate(answers[len(splits) - 1])

        monkeypatch.setattr(tasks, "_remember_breakdown", _remember)
        sess = await _session(db, tenant, user, f"{_RU_DESCRIPTION} {uuid.uuid4()}")
        with (
            patch.object(llm_client, "generate_json", side_effect=_split_in_turn),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
        ):
            result = await tasks.execute_session(session_factory, sess.id)
        await db.refresh(sess)
        return sess, result, consumed, splits, remembered

    async def test_the_retried_answer_is_delivered_charged_once_and_kept(
        self, db, tenant, user, seeded, session_factory, monkeypatch
    ):
        sess, result, consumed, splits, remembered = await self._run_retried(
            db, tenant, user, session_factory, [_RU_SPLIT, _SPLIT], monkeypatch
        )
        assert result["status"] == "ready"
        assert len(splits) == 2
        assert consumed == ["x"]  # one breakdown, however many calls it took
        assert [s["title"] for s in sess.payload["steps"]] == ["Intake", "Signature"]
        # The answer that passed serves the next run on the same text.
        assert remembered == [sess.payload]

    async def test_a_russian_workspace_gets_its_steps_in_russian(
        self, db, tenant, user, seeded, session_factory, monkeypatch
    ):
        db.add(TenantAISettings(tenant_id=tenant.id, content_language="ru"))
        await db.commit()
        sess, result, consumed, splits, _ = await self._run_retried(
            db, tenant, user, session_factory, [_SPLIT, _RU_SPLIT], monkeypatch
        )
        assert result["status"] == "ready"
        assert len(splits) == 2
        assert consumed == ["x"]
        assert [s["title"] for s in sess.payload["steps"]] == [_RU_INTAKE, _RU_SIGNING]

    async def test_a_run_cancelled_during_the_answer_is_not_asked_again(
        self, db, tenant, user, seeded, session_factory, monkeypatch
    ):
        splits: list[str] = []
        sess = await _session(db, tenant, user, f"{_RU_DESCRIPTION} {uuid.uuid4()}")

        async def _cancelled_meanwhile(prompt, *, schema=None, **_kwargs):
            splits.append(prompt)
            async with session_factory() as other:
                await service.cancel_session(other, tenant.id, sess.id)
            return schema.model_validate(_RU_SPLIT)

        with patch.object(
            llm_client, "generate_json", side_effect=_cancelled_meanwhile
        ):
            result = await tasks.execute_session(session_factory, sess.id)
        assert result == {"status": "cancelled", "session_id": str(sess.id)}
        assert len(splits) == 1

    async def test_a_second_answer_in_the_wrong_language_ends_the_run_unbilled(
        self, db, tenant, user, seeded, session_factory, monkeypatch
    ):
        consumed: list[str] = []
        released: list[dict] = []
        remembered: list[dict] = []
        asked: list[type] = []

        async def _consume(*_a, **_k):
            consumed.append("x")

        async def _release(_db, _tenant_id, **kw):
            released.append(kw)
            return 1

        async def _remember(_key, payload):
            remembered.append(payload)

        def _mirrors(*_a, schema=None, **_k):
            asked.append(schema)
            return schema.model_validate(_RU_SPLIT)

        monkeypatch.setattr(tasks, "_remember_breakdown", _remember)
        sess = await _session(db, tenant, user, f"{_RU_DESCRIPTION} {uuid.uuid4()}")
        with (
            patch.object(llm_client, "generate_json", side_effect=_mirrors),
            patch.object(billing_hooks, "consume_action", side_effect=_consume),
            patch.object(billing_hooks, "release_action", side_effect=_release),
        ):
            result = await tasks.execute_session(session_factory, sess.id)
        assert result == {
            "status": "error",
            "session_id": str(sess.id),
            "error_code": "wrong_language",
        }
        # The answer and its one retry; steps nobody will see are not classified.
        assert asked == [DecompositionSchema] * 2
        assert consumed == []
        assert len(released) == 1  # the hold of the run goes
        assert remembered == []
        await db.refresh(sess)
        assert (sess.status, sess.phase, sess.payload) == ("error", None, None)
        assert sess.error_code == "wrong_language"
        assert sess.error_message == "The steps came back in the wrong language"
        # The container is free for the next attempt.
        await service.create_session(db, tenant.id, user.id, sess.container_id)
