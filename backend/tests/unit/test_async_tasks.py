"""Tests for async AI generation, export, and embedding endpoints.

After the POOL_HOLD_REDUCTION refactor (2026-04-30):
- POST /api/ai/generate-* default to async (202 + task_id) and pass
  tenant_id + user_id as the first two args to the Celery task.
- ?sync=true preserves the old synchronous flow for legacy clients.
- Tasks live in app.modules.ai.tasks (moved from app.core.tasks).

CR15 (2026-05-02): all enqueue sites now go through `enqueue_task`, which
calls `task.apply_async(args=[...], headers={tenant_id, user_id, module,
action})` instead of `task.delay(...)`. Tests assert against `apply_async`
kwargs accordingly.
"""

from unittest.mock import MagicMock, patch

from httpx import AsyncClient


class TestAsyncAIEndpoints:
    @patch("app.modules.ai.tasks.generate_competences_task")
    async def test_generate_competences_default_async(
        self, mock_task, auth_client: AsyncClient
    ):
        mock_result = MagicMock()
        mock_result.id = "test-task-id-123"
        mock_task.apply_async.return_value = mock_result

        resp = await auth_client.post(
            "/api/ai/generate-competences",
            json={
                "specialization": "Backend Developer",
                "company_description": "Tech startup",
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["task_id"] == "test-task-id-123"
        # First two positional args are tenant_id_str and user_id_str.
        kwargs = mock_task.apply_async.call_args.kwargs
        assert kwargs["args"][2] == "Backend Developer"
        assert kwargs["args"][3] == "Tech startup"
        assert kwargs["headers"]["module"] == "ai"
        assert kwargs["headers"]["action"] == "generate_competences"

    @patch("app.modules.ai.tasks.generate_indicators_task")
    async def test_generate_indicators_default_async(
        self, mock_task, auth_client: AsyncClient
    ):
        mock_result = MagicMock()
        mock_result.id = "test-task-id-456"
        mock_task.apply_async.return_value = mock_result

        resp = await auth_client.post(
            "/api/ai/generate-indicators",
            json={"competence_title": "Problem Solving"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["task_id"] == "test-task-id-456"

    @patch("app.modules.ai.tasks.generate_positions_task")
    async def test_generate_positions_default_async(
        self, mock_task, auth_client: AsyncClient
    ):
        mock_result = MagicMock()
        mock_result.id = "task-pos-1"
        mock_task.apply_async.return_value = mock_result

        resp = await auth_client.post("/api/ai/generate-positions")
        assert resp.status_code == 202
        assert resp.json()["task_id"] == "task-pos-1"

    @patch("app.modules.ai.tasks.suggest_pdp_task")
    async def test_suggest_pdp_default_async(self, mock_task, auth_client: AsyncClient):
        mock_result = MagicMock()
        mock_result.id = "task-pdp-1"
        mock_task.apply_async.return_value = mock_result

        resp = await auth_client.post(
            "/api/ai/suggest-pdp",
            json={"assessment_id": "00000000-0000-0000-0000-000000000099"},
        )
        assert resp.status_code == 202
        assert resp.json()["task_id"] == "task-pdp-1"


class TestAsyncExportEndpoint:
    @patch("app.modules.analytics.tasks.export_assessments_task")
    async def test_export_assessments_async(self, mock_task, auth_client: AsyncClient):
        mock_result = MagicMock()
        mock_result.id = "export-task-id-789"
        mock_task.apply_async.return_value = mock_result

        resp = await auth_client.post("/api/analytics/export/assessments/async")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "export-task-id-789"


class TestBatchEmbedEndpoint:
    @patch("app.modules.ai.tasks.batch_embed_task")
    async def test_batch_embed(self, mock_task, auth_client: AsyncClient):
        mock_result = MagicMock()
        mock_result.id = "embed-task-id-101"
        mock_task.apply_async.return_value = mock_result

        resp = await auth_client.post(
            "/api/ai/embed/batch",
            json={
                "items": [
                    {
                        "entity_type": "competence",
                        "entity_id": "00000000-0000-0000-0000-000000000001",
                        "text_content": "Leadership skills",
                    },
                    {
                        "entity_type": "competence",
                        "entity_id": "00000000-0000-0000-0000-000000000002",
                        "text_content": "Problem solving",
                    },
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "embed-task-id-101"
        mock_task.apply_async.assert_called_once()
        # Verify items were serialized correctly (single positional list arg)
        kwargs = mock_task.apply_async.call_args.kwargs
        items_arg = kwargs["args"][0]
        assert len(items_arg) == 2
        assert items_arg[0]["entity_type"] == "competence"

    @patch("app.modules.ai.tasks.batch_embed_task")
    async def test_batch_embed_empty_items(self, mock_task, auth_client: AsyncClient):
        resp = await auth_client.post("/api/ai/embed/batch", json={"items": []})
        assert resp.status_code == 422  # Validation error: min_length=1


class TestTaskStatusEndpoint:
    @patch("app.core.task_router.AsyncResult")
    async def test_task_pending(self, mock_async_result, auth_client: AsyncClient):
        mock_result = MagicMock()
        mock_result.status = "PENDING"
        mock_result.successful.return_value = False
        mock_result.failed.return_value = False
        mock_async_result.return_value = mock_result

        resp = await auth_client.get("/api/tasks/some-task-id")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "some-task-id"
        assert data["status"] == "PENDING"

    @patch("app.core.task_router.AsyncResult")
    async def test_task_success(self, mock_async_result, auth_client: AsyncClient):
        mock_result = MagicMock()
        mock_result.status = "SUCCESS"
        mock_result.successful.return_value = True
        mock_result.failed.return_value = False
        mock_result.result = [{"title": "Leadership", "level": "Senior"}]
        mock_async_result.return_value = mock_result

        resp = await auth_client.get("/api/tasks/completed-task-id")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert data["result"] == [{"title": "Leadership", "level": "Senior"}]

    @patch("app.core.task_router.AsyncResult")
    async def test_task_failure(self, mock_async_result, auth_client: AsyncClient):
        mock_result = MagicMock()
        mock_result.status = "FAILURE"
        mock_result.successful.return_value = False
        mock_result.failed.return_value = True
        mock_result.result = Exception("LLM API error")
        mock_async_result.return_value = mock_result

        resp = await auth_client.get("/api/tasks/failed-task-id")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "FAILURE"
        assert "LLM API error" in data["error"]
