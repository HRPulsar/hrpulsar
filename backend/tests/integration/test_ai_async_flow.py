"""End-to-end coverage of the new async AI flow.

POST /api/ai/generate-* without ?sync=true must return 202 + task_id, and the
Celery task body must produce the same shape of result the legacy sync path
returned. The DB and LLM layers are stubbed so this test can run anywhere
without a broker, Redis, or model credentials.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from httpx import AsyncClient


class TestAsyncAIFlow:
    """POST → 202 + task_id; task body produces sync-compatible payload."""

    @patch("app.modules.ai.tasks.generate_positions_task")
    async def test_generate_positions_async_handoff(
        self, mock_task, auth_client: AsyncClient
    ):
        mock_task.apply_async.return_value = MagicMock(id="task-pos-uuid-1")

        resp = await auth_client.post("/api/ai/generate-positions")

        assert resp.status_code == 202
        assert resp.json() == {"task_id": "task-pos-uuid-1"}
        mock_task.apply_async.assert_called_once()
        # enqueue_task forwards (tenant_id_str, user_id_str, cost) via the `args`
        # kwarg; the first two must be valid UUID strings.
        forwarded = mock_task.apply_async.call_args.kwargs["args"]
        uuid.UUID(forwarded[0])
        uuid.UUID(forwarded[1])

    def test_generate_positions_task_body_runs(self):
        """Run the task body in-process (apply) with DB + LLM stubbed.

        Validates that the Celery task wrapper:
          - calls _run_with_async_session
          - returns whatever the inner coroutine produced
          - doesn't accidentally swallow the return value
        """
        from app.modules.ai.tasks import generate_positions_task

        fake_drafts = [{"id": "p1", "title": "Backend Engineer", "source": "ai_draft"}]
        with patch("app.modules.ai.tasks._run_with_async_session") as mock_run:
            mock_run.return_value = fake_drafts
            result = generate_positions_task.apply(
                args=("00000000-0000-0000-0000-000000000001", None)
            ).get()

        assert result == fake_drafts
        # The wrapper invoked our async session helper exactly once.
        assert mock_run.call_count == 1

    def test_generate_competences_task_body_runs(self):
        from app.modules.ai.tasks import generate_competences_task

        fake_items = [{"title": "Communication", "type": "soft"}]
        with patch("app.modules.ai.tasks._run_with_async_session") as mock_run:
            mock_run.return_value = fake_items
            result = generate_competences_task.apply(
                args=(
                    "00000000-0000-0000-0000-000000000001",
                    "00000000-0000-0000-0000-000000000002",
                    "Backend Developer",
                    "",
                    "",
                )
            ).get()

        assert result == fake_items

    @patch("app.core.task_router.AsyncResult")
    async def test_get_task_status_returns_done(
        self, mock_async_result, auth_client: AsyncClient
    ):
        """Once the worker finishes, GET /api/tasks/{id} surfaces the result."""
        result_mock = MagicMock()
        result_mock.status = "SUCCESS"
        result_mock.successful.return_value = True
        result_mock.failed.return_value = False
        result_mock.result = [{"id": "p1", "title": "Backend Engineer"}]
        mock_async_result.return_value = result_mock

        resp = await auth_client.get("/api/tasks/task-pos-uuid-1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "SUCCESS"
        assert body["result"] == [{"id": "p1", "title": "Backend Engineer"}]
