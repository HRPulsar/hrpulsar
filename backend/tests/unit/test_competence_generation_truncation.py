"""HRP-432: fail-fast on truncated LLM output in competence generation.

Truncation is deterministic for a given prompt+budget, and the budget is
already at the per-model ceiling — observed live: five identical ~4-minute
attempts (~80k wasted output tokens per click) surfacing as a misleading
``service_error`` ("AI service temporarily unavailable"). The retry loop
must raise ``output_truncated`` on the first truncated attempt instead.
"""

from unittest.mock import patch

import pytest
from app.modules.ai import llm_client
from app.modules.ai.llm_client import LLMOutputTruncatedError
from app.modules.ai_competence_generation import tasks
from pydantic import BaseModel

pytestmark = pytest.mark.asyncio


class _Payload(BaseModel):
    ok: bool


class TestTruncationFailFast:
    async def test_truncation_raises_immediately_without_retries(self) -> None:
        calls = {"n": 0}

        async def fake_generate_json(prompt, **kwargs):
            calls["n"] += 1
            raise LLMOutputTruncatedError("claude-sonnet-4-6", 64000)

        with (
            patch.object(llm_client, "generate_json", new=fake_generate_json),
            pytest.raises(RuntimeError, match="output_truncated") as excinfo,
        ):
            await tasks._generate_with_retries(
                user_prompt="p",
                system="s",
                schema=_Payload,
                tenant_settings=None,
                max_attempts=5,
            )

        assert calls["n"] == 1
        assert isinstance(excinfo.value.__cause__, LLMOutputTruncatedError)

    async def test_transient_provider_error_still_retries(self) -> None:
        calls = {"n": 0}

        async def fake_generate_json(prompt, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("boom")
            return _Payload(ok=True)

        with patch.object(llm_client, "generate_json", new=fake_generate_json):
            result, code = await tasks._generate_with_retries(
                user_prompt="p",
                system="s",
                schema=_Payload,
                tenant_settings=None,
                max_attempts=5,
            )

        assert calls["n"] == 2
        assert code is None
        assert isinstance(result, _Payload)

    async def test_tree_scopes_request_model_ceiling(self) -> None:
        # llm_client clamps per model (Haiku 8192, Opus 32000, gpt-4o
        # 16384); the scope map asks for the sonnet-class ceiling from
        # the model registry — the single source of truth for caps.
        from app.modules.ai import model_registry

        ceiling = model_registry.ANTHROPIC_OUTPUT_CAPS[
            model_registry.ANTHROPIC_BALANCED
        ]
        assert ceiling > 16384  # must exceed the budget that truncated live
        for scope in ("whole_base", "group", "specialization_matrix"):
            assert tasks._max_tokens_for_scope(scope) == ceiling
        assert tasks._max_tokens_for_scope("competence_indicators") == 8192

    async def test_output_truncated_is_a_valid_session_error_code(self) -> None:
        from app.modules.ai_competence_generation.models import ERROR_CODES

        assert "output_truncated" in ERROR_CODES
