"""Regression: AI generation endpoints must not block on the LLM call.

Before POOL_HOLD_REDUCTION the request handler ran the LLM call (5–60 s)
inside the request transaction, pinning a DB pool slot for the entire
duration. After the refactor the default path is async (202 + task_id) and
the LLM call happens inside the Celery task — the handler should return
under 200 ms even though the underlying generation may take a minute.

We mock `*.delay` so no broker is required to run this test.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.load]


async def test_generate_positions_returns_fast(auth_client: AsyncClient):
    with patch("app.modules.ai.tasks.generate_positions_task") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "fast-path-task-id"
        mock_task.delay.return_value = mock_result

        t0 = time.monotonic()
        resp = await auth_client.post("/api/ai/generate-positions")
        elapsed = time.monotonic() - t0

    assert resp.status_code == 202, resp.text
    assert resp.json()["task_id"] == "fast-path-task-id"
    assert elapsed < 0.2, f"generate-positions took {elapsed:.3f}s — expected <0.2s"


async def test_generate_competences_returns_fast(auth_client: AsyncClient):
    with patch("app.modules.ai.tasks.generate_competences_task") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "comp-fast-id"
        mock_task.delay.return_value = mock_result

        t0 = time.monotonic()
        resp = await auth_client.post(
            "/api/ai/generate-competences",
            json={"specialization": "Backend Developer"},
        )
        elapsed = time.monotonic() - t0

    assert resp.status_code == 202, resp.text
    assert elapsed < 0.2, f"generate-competences took {elapsed:.3f}s — expected <0.2s"


async def test_generate_indicators_returns_fast(auth_client: AsyncClient):
    with patch("app.modules.ai.tasks.generate_indicators_task") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "ind-fast-id"
        mock_task.delay.return_value = mock_result

        t0 = time.monotonic()
        resp = await auth_client.post(
            "/api/ai/generate-indicators",
            json={"competence_title": "Problem Solving"},
        )
        elapsed = time.monotonic() - t0

    assert resp.status_code == 202, resp.text
    assert elapsed < 0.2, f"generate-indicators took {elapsed:.3f}s — expected <0.2s"
