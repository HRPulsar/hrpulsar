"""Truncation detection in ``llm_client`` provider helpers.

Prod 2026-07-08: a vacancy-profile generation hit the 8192-token default
output budget, the model stopped mid-string, and the clipped JSON
surfaced as an opaque ``json.JSONDecodeError: Unterminated string``.
The helpers now raise ``LLMOutputTruncatedError`` whenever the provider
reports a max-tokens stop, recruitment call sites request a 32768-token
budget (clamped per model inside ``llm_client``), and the vacancy-profile
generator retries once with a compact-profile instruction when even that
budget overflows.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from app.modules.ai import llm_client
from app.modules.ai.llm_client import LLMOutputTruncatedError

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


def _anthropic_client(stop_reason: str) -> SimpleNamespace:
    response = SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(text='{"ok": true}')],
    )
    return SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=response))
    )


class TestAnthropicTruncation:
    async def test_max_tokens_stop_reason_raises(self) -> None:
        client = _anthropic_client("max_tokens")
        with (
            patch.object(llm_client, "_get_anthropic", return_value=client),
            pytest.raises(LLMOutputTruncatedError, match="max_tokens"),
        ):
            await llm_client._generate_anthropic(
                "p", None, "claude-sonnet-4-6", 0.3, 8192
            )

    async def test_end_turn_returns_text(self) -> None:
        client = _anthropic_client("end_turn")
        with patch.object(llm_client, "_get_anthropic", return_value=client):
            result = await llm_client._generate_anthropic(
                "p", None, "claude-sonnet-4-6", 0.3, 8192
            )
        assert result == '{"ok": true}'


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


def _openai_client(finish_reason: str) -> SimpleNamespace:
    choice = SimpleNamespace(
        finish_reason=finish_reason,
        message=SimpleNamespace(content='{"ok": true}'),
    )
    response = SimpleNamespace(choices=[choice])
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=response))
        )
    )


class TestOpenAITruncation:
    async def test_length_finish_reason_raises(self) -> None:
        client = _openai_client("length")
        with (
            patch.object(llm_client, "_get_openai", return_value=client),
            pytest.raises(LLMOutputTruncatedError),
        ):
            await llm_client._generate_openai("p", None, "gpt-4o", 0.3, 8192)

    async def test_stop_finish_reason_returns_text(self) -> None:
        client = _openai_client("stop")
        with patch.object(llm_client, "_get_openai", return_value=client):
            result = await llm_client._generate_openai("p", None, "gpt-4o", 0.3, 8192)
        assert result == '{"ok": true}'

    async def test_max_tokens_clamped_to_model_cap(self) -> None:
        # gpt-4o rejects max_tokens > 16384 with HTTP 400 — a 32768 request
        # must be clamped before it reaches the API.
        client = _openai_client("stop")
        with patch.object(llm_client, "_get_openai", return_value=client):
            await llm_client._generate_openai("p", None, "gpt-4o", 0.3, 32768)
        sent = client.chat.completions.create.call_args.kwargs
        assert sent["max_tokens"] == 16384

    async def test_unknown_model_clamped_to_default_cap(self) -> None:
        client = _openai_client("stop")
        with patch.object(llm_client, "_get_openai", return_value=client):
            await llm_client._generate_openai("p", None, "gpt-99-turbo", 0.3, 32768)
        sent = client.chat.completions.create.call_args.kwargs
        assert sent["max_tokens"] == 16384


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


def _gemini_client(finish_reason: object) -> SimpleNamespace:
    response = SimpleNamespace(
        text='{"ok": true}',
        candidates=[SimpleNamespace(finish_reason=finish_reason)],
    )
    return SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=AsyncMock(return_value=response))
        )
    )


class TestGeminiTruncation:
    async def test_max_tokens_finish_reason_raises(self) -> None:
        # google-genai returns a FinishReason enum whose str() is
        # "FinishReason.MAX_TOKENS" — the check matches on substring.
        client = _gemini_client("FinishReason.MAX_TOKENS")
        with (
            patch.object(llm_client, "_get_gemini", return_value=client),
            pytest.raises(LLMOutputTruncatedError),
        ):
            await llm_client._generate_gemini("p", None, "gemini-2.5-pro", 0.3, 8192)

    async def test_stop_finish_reason_returns_text(self) -> None:
        client = _gemini_client("FinishReason.STOP")
        with patch.object(llm_client, "_get_gemini", return_value=client):
            result = await llm_client._generate_gemini(
                "p", None, "gemini-2.5-pro", 0.3, 8192
            )
        assert result == '{"ok": true}'

    async def test_missing_candidates_returns_text(self) -> None:
        response = SimpleNamespace(text='{"ok": true}', candidates=None)
        client = SimpleNamespace(
            aio=SimpleNamespace(
                models=SimpleNamespace(
                    generate_content=AsyncMock(return_value=response)
                )
            )
        )
        with patch.object(llm_client, "_get_gemini", return_value=client):
            result = await llm_client._generate_gemini(
                "p", None, "gemini-2.5-pro", 0.3, 8192
            )
        assert result == '{"ok": true}'


# ---------------------------------------------------------------------------
# Recruitment call sites forward the bigger budget
# ---------------------------------------------------------------------------


class TestRecruitmentBudgetForwarding:
    async def test_generate_vacancy_profile_requests_32k(self) -> None:
        from app.modules.recruitment import ai_service

        captured: dict = {}

        async def fake_generate(prompt, **kwargs):
            captured.update(kwargs)
            return '{"vacancy_id": "x", "competences": []}'

        with patch.object(llm_client, "generate", new=fake_generate):
            await ai_service.generate_vacancy_profile({"title": "Dev"})

        assert captured["max_tokens"] == ai_service.RECRUITMENT_MAX_TOKENS
        assert ai_service.RECRUITMENT_MAX_TOKENS == 32768

    async def test_parse_resume_text_requests_32k(self) -> None:
        from app.modules.recruitment import ai_service

        captured: dict = {}

        async def fake_generate(prompt, **kwargs):
            captured.update(kwargs)
            return "{}"

        with patch.object(llm_client, "generate", new=fake_generate):
            await ai_service.parse_resume_text("resume text")

        assert captured["max_tokens"] == ai_service.RECRUITMENT_MAX_TOKENS


# ---------------------------------------------------------------------------
# Vacancy profile retries once with the compact instruction on truncation
# ---------------------------------------------------------------------------


class TestProfileCompactRetry:
    async def test_truncation_triggers_compact_retry(self) -> None:
        from app.modules.recruitment import ai_service

        prompts: list[str] = []

        async def fake_generate(prompt, **kwargs):
            prompts.append(prompt)
            if len(prompts) == 1:
                raise LLMOutputTruncatedError("claude-sonnet-4-6", 32768)
            return '{"vacancy_id": "x", "competences": []}'

        with patch.object(llm_client, "generate", new=fake_generate):
            result = await ai_service.generate_vacancy_profile({"title": "Dev"})

        assert result == {"vacancy_id": "x", "competences": []}
        assert len(prompts) == 2
        assert "COMPACT" in prompts[1]
        assert prompts[1].startswith(prompts[0])

    async def test_second_truncation_propagates(self) -> None:
        from app.modules.recruitment import ai_service

        calls = {"n": 0}

        async def fake_generate(prompt, **kwargs):
            calls["n"] += 1
            raise LLMOutputTruncatedError("claude-sonnet-4-6", 32768)

        with (
            patch.object(llm_client, "generate", new=fake_generate),
            pytest.raises(LLMOutputTruncatedError),
        ):
            await ai_service.generate_vacancy_profile({"title": "Dev"})

        assert calls["n"] == 2
