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
from app.modules.ai import llm_client
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

    async def test_openai_reasoning_models_take_no_sampling(self) -> None:
        captured: dict = {}
        with patch.object(llm_client, "_get_openai", return_value=_openai(captured)):
            await llm_client.generate(
                "p", system=BLOCKS, model="o1-mini", top_p=1.0, seed=0
            )
        assert not {"top_p", "seed", "temperature"} & captured.keys()

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
