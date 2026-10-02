"""HRP-964: every provider call leaves a CallRecord through the seam."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.core import ai_usage_hooks
from app.modules.ai import llm_client, providers
from app.modules.ai.llm_client import LLMOutputTruncatedError

pytestmark = pytest.mark.asyncio


@pytest.fixture
def records(monkeypatch):
    seen: list[ai_usage_hooks.CallRecord] = []

    async def _capture(record):
        seen.append(record)

    monkeypatch.setattr(ai_usage_hooks, "record_call", _capture)
    return seen


def _openai_client(finish_reason="stop", usage=None, raise_exc=None):
    async def create(**_):
        if raise_exc is not None:
            raise raise_exc
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=finish_reason,
                    message=SimpleNamespace(content='{"ok": true}'),
                )
            ],
            **({"usage": usage} if usage is not None else {}),
        )

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )


async def test_openai_call_is_recorded_with_usage(monkeypatch, records):
    usage = SimpleNamespace(
        prompt_tokens=120,
        completion_tokens=30,
        prompt_tokens_details=SimpleNamespace(cached_tokens=100),
    )
    monkeypatch.setattr(llm_client, "_get_openai", lambda *a, **k: _openai_client(usage=usage))

    await llm_client.generate("hi", model="gpt-4o")

    (record,) = records
    assert record.kind == "generate"
    assert record.provider == "openai"
    assert record.model == "gpt-4o"
    assert record.credential_source == "platform"
    assert record.status == "ok"
    assert (record.input_tokens, record.output_tokens, record.cache_read_tokens) == (120, 30, 100)
    assert record.cache_write_tokens is None
    assert isinstance(record.latency_ms, int) and record.latency_ms >= 0


async def test_missing_usage_is_null(monkeypatch, records):
    monkeypatch.setattr(llm_client, "_get_openai", lambda *a, **k: _openai_client())

    await llm_client.generate("hi", model="gpt-4o")

    (record,) = records
    assert record.status == "ok"
    assert record.input_tokens is None and record.output_tokens is None


async def test_truncated_call_is_recorded_then_raised(monkeypatch, records):
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=8192, prompt_tokens_details=None)
    monkeypatch.setattr(
        llm_client, "_get_openai", lambda *a, **k: _openai_client("length", usage=usage)
    )

    with pytest.raises(LLMOutputTruncatedError):
        await llm_client.generate("hi", model="gpt-4o")

    (record,) = records
    assert record.status == "truncated"
    assert record.error_code == "output_truncated"
    assert record.output_tokens == 8192


async def test_provider_error_is_recorded_then_raised(monkeypatch, records):
    monkeypatch.setattr(
        llm_client,
        "_get_openai",
        lambda *a, **k: _openai_client(raise_exc=RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError):
        await llm_client.generate("hi", model="gpt-4o")

    (record,) = records
    assert record.status == "error"
    assert record.error_code == "RuntimeError"


async def test_app_error_is_recorded_with_its_code(monkeypatch, records):
    from app.core.errors import AppError

    monkeypatch.setattr(
        llm_client,
        "_get_openai",
        lambda *a, **k: _openai_client(raise_exc=AppError("llm_yandex_key_missing", 422)),
    )

    with pytest.raises(AppError):
        await llm_client.generate("hi", model="gpt-4o")

    (record,) = records
    assert record.status == "error"
    assert record.error_code == "llm_yandex_key_missing"


async def test_non_app_error_with_code_attr_is_recorded_as_class_name(monkeypatch, records):
    class FakeSdkError(Exception):
        code = "rate_limit_exceeded"

    monkeypatch.setattr(
        llm_client,
        "_get_openai",
        lambda *a, **k: _openai_client(raise_exc=FakeSdkError("boom")),
    )

    with pytest.raises(FakeSdkError):
        await llm_client.generate("hi", model="gpt-4o")

    (record,) = records
    assert record.status == "error"
    assert record.error_code == "FakeSdkError"


async def test_anthropic_byok_records_cache_tokens_and_source(monkeypatch, records):
    response = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(text="ok")],
        usage=SimpleNamespace(
            input_tokens=50,
            output_tokens=5,
            cache_read_input_tokens=40,
            cache_creation_input_tokens=10,
        ),
    )

    async def create(**_):
        return response

    monkeypatch.setattr(
        llm_client,
        "_get_anthropic",
        lambda *a, **k: SimpleNamespace(messages=SimpleNamespace(create=create)),
    )
    target = providers.GenerationTarget(provider="anthropic", api_key="k", source="byok")

    await llm_client.generate("hi", model="claude-sonnet-4-5", credentials=target)

    (record,) = records
    assert record.provider == "anthropic"
    assert record.credential_source == "byok"
    assert (record.cache_read_tokens, record.cache_write_tokens) == (40, 10)


async def test_gemini_records_usage_metadata(monkeypatch, records):
    response = SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason="STOP")],
        text="ok",
        usage_metadata=SimpleNamespace(
            prompt_token_count=7, candidates_token_count=3, cached_content_token_count=None
        ),
    )

    async def generate_content(**_):
        return response

    monkeypatch.setattr(
        llm_client,
        "_get_gemini",
        lambda *a, **k: SimpleNamespace(
            aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
        ),
    )

    await llm_client.generate("hi", model="gemini-2.5-flash")

    (record,) = records
    assert record.provider == "gemini"
    assert (record.input_tokens, record.output_tokens) == (7, 3)


async def test_gemini_thinking_counts_as_output(monkeypatch, records):
    response = SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason="STOP")],
        text="ok",
        usage_metadata=SimpleNamespace(
            prompt_token_count=7,
            candidates_token_count=3,
            thoughts_token_count=5,
            cached_content_token_count=None,
        ),
    )

    async def generate_content(**_):
        return response

    monkeypatch.setattr(
        llm_client,
        "_get_gemini",
        lambda *a, **k: SimpleNamespace(
            aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
        ),
    )

    await llm_client.generate("hi", model="gemini-2.5-flash")

    (record,) = records
    assert (record.input_tokens, record.output_tokens) == (7, 8)


async def test_gemini_usage_without_counts_stays_null():
    usage = llm_client._gemini_usage(SimpleNamespace(usage_metadata=None))
    assert usage.output_tokens is None


async def test_recorder_failure_does_not_break_generation(monkeypatch):
    async def _boom(record):
        raise RuntimeError("journal down")

    monkeypatch.setattr(ai_usage_hooks, "record_call", _boom)
    monkeypatch.setattr(llm_client, "_get_openai", lambda *a, **k: _openai_client())

    assert await llm_client.generate("hi", model="gpt-4o") == '{"ok": true}'


async def test_embedding_is_recorded(monkeypatch, records):
    async def create(**_):
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2])],
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=None, prompt_tokens_details=None),
        )

    monkeypatch.setattr(
        llm_client,
        "_get_openai",
        lambda *a, **k: SimpleNamespace(embeddings=SimpleNamespace(create=create)),
    )

    await llm_client.get_embedding("hi", model="text-embedding-3-small")

    (record,) = records
    assert record.kind == "embedding"
    assert record.input_tokens == 4 and record.output_tokens is None


async def test_an_unusable_anthropic_answer_keeps_its_tokens(monkeypatch, records):
    # Review 01.10: an answer with no text block was billed by the provider
    # but journaled as an error with no tokens, so its cost was lost.
    async def generate_anthropic(*_a, **_k):
        raise llm_client._with_usage(
            ValueError("Anthropic returned no text content block"),
            {"input_tokens": 50, "output_tokens": 900},
        )

    seen: dict = {}

    async def _record(*args, usage=None, **kwargs):
        seen["usage"] = usage

    monkeypatch.setattr(llm_client, "_generate_anthropic", generate_anthropic)
    monkeypatch.setattr(llm_client, "_record", _record)
    with pytest.raises(ValueError):
        await llm_client.generate("hi", model="claude-sonnet-5")
    assert seen["usage"] == {"input_tokens": 50, "output_tokens": 900}
