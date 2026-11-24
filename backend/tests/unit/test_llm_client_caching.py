"""HRP-951 / HRP-921: how ``llm_client`` lays a request out.

A block-list ``system`` is the caching layout: Anthropic gets the first
block marked ``cache_control: ephemeral`` and the rest plain; every other
provider gets one joined system message and never sees the mark. The
pinned sampling parameters (``top_p``, ``seed``) reach only the providers
that take them.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from app.config import settings
from app.modules.ai import llm_client, model_registry, providers
from pydantic import BaseModel

pytestmark = pytest.mark.asyncio

PREFIX = "The rules, the catalog and the examples. " * 8
BLOCKS = [PREFIX, "Answer in German.", "the schema"]


def _anthropic(captured: dict) -> SimpleNamespace:
    response = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(text="{}")]
    )

    async def _create(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return response

    return SimpleNamespace(messages=SimpleNamespace(create=_create))


def _openai(captured: dict) -> SimpleNamespace:
    choice = SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(content="{}")
    )

    async def _create(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(choices=[choice])

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
    )


def _gemini(captured: dict) -> SimpleNamespace:
    async def _generate(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            text="{}", candidates=[SimpleNamespace(finish_reason="STOP")]
        )

    return SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=_generate))
    )


class TestAnthropicSystemBlocks:
    async def test_first_block_is_cached_the_rest_plain(self) -> None:
        captured: dict = {}
        with patch.object(
            llm_client, "_get_anthropic", return_value=_anthropic(captured)
        ):
            await llm_client._generate_anthropic(
                "p", BLOCKS, "claude-sonnet-5", 0.0, 8192
            )
        assert captured["system"] == [
            {"type": "text", "text": PREFIX, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Answer in German."},
            {"type": "text", "text": "the schema"},
        ]

    async def test_plain_string_system_is_unchanged(self) -> None:
        captured: dict = {}
        with patch.object(
            llm_client, "_get_anthropic", return_value=_anthropic(captured)
        ):
            await llm_client._generate_anthropic(
                "p", "sys", "claude-sonnet-5", 0.0, 8192
            )
        assert captured["system"] == "sys"

    async def test_sampling_pins_do_not_reach_anthropic(self) -> None:
        # No seed exists there, and top_p next to temperature is rejected.
        captured: dict = {}
        with patch.object(
            llm_client, "_get_anthropic", return_value=_anthropic(captured)
        ):
            await llm_client.generate(
                "p",
                system=BLOCKS,
                model="claude-haiku-4-5-20251001",
                temperature=0.0,
                top_p=1.0,
                seed=0,
            )
        assert "top_p" not in captured
        assert "seed" not in captured
        assert captured["temperature"] == 0.0
        assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}


class TestOtherProviders:
    async def test_openai_gets_one_system_message_and_the_pins(self) -> None:
        captured: dict = {}
        with patch.object(llm_client, "_get_openai", return_value=_openai(captured)):
            await llm_client.generate(
                "p", system=BLOCKS, model="gpt-4o", temperature=0.0, top_p=1.0, seed=0
            )
        assert captured["messages"][0] == {
            "role": "system",
            "content": "\n\n".join(BLOCKS),
        }
        assert (captured["temperature"], captured["top_p"], captured["seed"]) == (
            0.0,
            1.0,
            0,
        )
        assert "cache_control" not in repr(captured)

    async def test_openai_reasoning_models_take_only_the_seed(self) -> None:
        # HRP-1240: the reasoning shape still takes the seed pin (probed on
        # o3 and gpt-5 … gpt-6.2); temperature and top_p stay out.
        captured: dict = {}
        with patch.object(llm_client, "_get_openai", return_value=_openai(captured)):
            await llm_client.generate(
                "p", system=BLOCKS, model="o1-mini", top_p=1.0, seed=0
            )
        assert not {"top_p", "temperature"} & captured.keys()
        assert captured["seed"] == 0

    @pytest.mark.parametrize("model", ["gpt-5.5", model_registry.OPENAI_BALANCED])
    async def test_gpt5_onwards_get_the_reasoning_shape(self, model: str) -> None:
        # HRP-1240: GPT-5+ answered HTTP 400 to max_tokens and to any
        # non-default temperature/top_p — every call failed. Reasoning
        # spends the budget too, so a small one is raised to the floor.
        captured: dict = {}
        with patch.object(llm_client, "_get_openai", return_value=_openai(captured)):
            await llm_client.generate(
                "p", system="sys", model=model, temperature=0.3, top_p=1.0,
                max_tokens=4096,
            )
        assert not {"max_tokens", "temperature", "top_p"} & captured.keys()
        assert (
            captured["max_completion_tokens"]
            == model_registry.REASONING_MIN_OUTPUT_TOKENS
        )
        assert captured["messages"][0]["role"] == "system"

    async def test_legacy_chat_models_keep_their_budget_and_sampling(self) -> None:
        captured: dict = {}
        with patch.object(llm_client, "_get_openai", return_value=_openai(captured)):
            await llm_client.generate(
                "p", system="sys", model="ft:gpt-4o-mini:org::abc",
                temperature=0.3, max_tokens=4096,
            )
        assert (captured["max_tokens"], captured["temperature"]) == (4096, 0.3)

    @pytest.mark.parametrize(
        ("model", "reasoning"),
        [
            ("gpt-6.2-sol", True),
            ("gpt-4o", False),
            ("llama3.1", False),
            ("gpt-oss:20b", False),
            ("gpt-35-turbo", False),
        ],
    )
    async def test_a_base_url_proxy_gets_the_shape_of_the_model_name(
        self, model: str, reasoning: bool
    ) -> None:
        # HRP-1240: an OpenAI row behind a proxy serving GPT-5+ answered
        # 400 to the chat shape; a local server keeps max_tokens.
        captured: dict = {}
        with patch.object(llm_client, "_get_openai", return_value=_openai(captured)):
            await llm_client._generate_openai(
                "p", "sys", model, 0.3, 4096, base_url="https://proxy.example/v1"
            )
        assert ("max_completion_tokens" in captured) is reasoning
        assert ("temperature" in captured) is not reasoning

    async def test_thinking_claude_gets_the_budget_floor(self) -> None:
        captured: dict = {}
        with patch.object(
            llm_client, "_get_anthropic", return_value=_anthropic(captured)
        ):
            await llm_client.generate(
                "p", system="sys", model=model_registry.ANTHROPIC_FAST, max_tokens=4096
            )
        assert captured["max_tokens"] == model_registry.REASONING_MIN_OUTPUT_TOKENS
        assert "temperature" not in captured

    async def test_gemini_4_gets_no_sampling_params(self) -> None:
        # HRP-1240: Gemini 3.6+ deprecates temperature/top_p (ignored now,
        # HTTP 400 in later generations); the seed pin still goes.
        captured: dict = {}
        with patch.object(llm_client, "_get_gemini", return_value=_gemini(captured)):
            await llm_client.generate(
                "p",
                system="sys",
                model=model_registry.GEMINI_BALANCED,
                temperature=0.0,
                top_p=1.0,
                seed=0,
            )
        assert not {"temperature", "top_p"} & captured["config"].keys()
        assert captured["config"]["seed"] == 0
        assert (
            captured["config"]["max_output_tokens"]
            == model_registry.REASONING_MIN_OUTPUT_TOKENS
        )

    async def test_gemini_folds_blocks_into_the_prompt_and_takes_the_pins(
        self,
    ) -> None:
        captured: dict = {}
        with patch.object(llm_client, "_get_gemini", return_value=_gemini(captured)):
            await llm_client.generate(
                "p",
                system=BLOCKS,
                model="gemini-2.5-flash",
                temperature=0.0,
                top_p=1.0,
                seed=0,
            )
        assert captured["contents"] == "\n\n".join(BLOCKS) + "\n\np"
        assert (captured["config"]["top_p"], captured["config"]["seed"]) == (1.0, 0)
        assert "cache_control" not in repr(captured)

    async def test_pins_left_unset_are_not_sent(self) -> None:
        captured: dict = {}
        with patch.object(llm_client, "_get_openai", return_value=_openai(captured)):
            await llm_client.generate("p", system="sys", model="gpt-4o")
        assert "top_p" not in captured
        assert "seed" not in captured


GATEWAY = "https://gateway.example/v1"


class TestTemperatureAgreement:
    """HRP-1241: what dispatch sends is what ``providers.accepts_temperature``
    says — the settings page reads the same rule to grey out the control."""

    @pytest.mark.parametrize(
        ("provider", "model", "base_url", "api_key"),
        [
            # Platform keys.
            ("anthropic", model_registry.ANTHROPIC_BALANCED, None, None),
            ("anthropic", "claude-haiku-4-5-20251001", None, None),
            ("openai", model_registry.OPENAI_BALANCED, None, None),
            ("openai", "gpt-4o", None, None),
            ("gemini", model_registry.GEMINI_BALANCED, None, None),
            ("gemini", "gemini-2.5-pro", None, None),
            ("yandex", "gpt://b1g/yandexgpt/latest", None, None),
            # The workspace's own keys.
            ("anthropic", model_registry.ANTHROPIC_THOROUGH, None, "byok"),
            ("openai", "gpt-6.2-sol", None, "byok"),
            ("gemini", "gemini-2.5-flash", None, "byok"),
            # A gateway or local server behind a base_url.
            ("openai_compatible", "gpt-6.2-sol", GATEWAY, None),
            ("openai_compatible", "gpt-oss:20b", GATEWAY, None),
            ("openai_compatible", "claude-sonnet-5-5", GATEWAY, None),
            ("openai_compatible", "gemini-4-hydrogen", GATEWAY, None),
            ("openai_compatible", "llama3.1", GATEWAY, None),
            ("yandex", "yandexgpt-lite", GATEWAY, None),
        ],
    )
    async def test_dispatch_sends_temperature_exactly_where_the_rule_says(
        self, provider: str, model: str, base_url: str | None, api_key: str | None
    ) -> None:
        captured: dict = {}
        credentials = (
            providers.GenerationTarget(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                source="local" if base_url else "byok",
            )
            if base_url or api_key
            else None
        )
        with (
            patch.object(
                llm_client, "_get_anthropic", return_value=_anthropic(captured)
            ),
            patch.object(llm_client, "_get_openai", return_value=_openai(captured)),
            patch.object(llm_client, "_get_gemini", return_value=_gemini(captured)),
            patch.object(settings, "yandex_api_key", "platform-key"),
        ):
            await llm_client.generate(
                "p",
                system="sys",
                model=model,
                temperature=0.3,
                top_p=0.9,
                credentials=credentials,
            )
        sent = captured.get("config", captured)
        expected = providers.accepts_temperature(
            model, provider=provider, base_url=base_url
        )
        assert ("temperature" in sent) is expected
        assert "top_p" not in sent or expected  # never without temperature


class _Schema(BaseModel):
    steps: list[str]


class TestGenerateJson:
    async def test_schema_block_follows_the_cached_prefix(self) -> None:
        seen: dict = {}

        async def _generate(prompt: str, **kwargs: object) -> str:
            seen.update(kwargs)
            return '{"steps": []}'

        with patch.object(llm_client, "generate", side_effect=_generate):
            await llm_client.generate_json(
                "p", system=[PREFIX, "lang"], schema=_Schema, top_p=1.0, seed=0
            )
        assert seen["system"][:2] == [PREFIX, "lang"]
        assert seen["system"][2].startswith("Return JSON that strictly conforms")
        assert (seen["top_p"], seen["seed"]) == (1.0, 0)

    async def test_string_system_keeps_the_joined_shape(self) -> None:
        seen: dict = {}

        async def _generate(prompt: str, **kwargs: object) -> str:
            seen.update(kwargs)
            return '{"steps": []}'

        with patch.object(llm_client, "generate", side_effect=_generate):
            await llm_client.generate_json("p", system="sys", schema=_Schema)
        assert isinstance(seen["system"], str)
        assert seen["system"].startswith("sys\n\nReturn JSON")
