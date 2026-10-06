"""HRP-1010: an embedding provider failure is a localized 502 with an error
code on /ai/embed and /ai/search - not a raw 500, and never the provider's
own text. The batch task keeps going and records the failed item."""

from __future__ import annotations

import contextvars
import logging
import uuid

import httpx
import openai
import pytest
from app.config import settings
from app.core.i18n import translate
from app.modules.ai import llm_client
from app.modules.ai import service as ai_service

RAW = "Error code: 403 - unsupported_country_region_territory internal-body"


def _provider_403() -> openai.PermissionDeniedError:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    return openai.PermissionDeniedError(
        RAW, response=httpx.Response(403, request=request), body=None
    )


@pytest.fixture
def failing_provider(monkeypatch):
    monkeypatch.setattr(settings, "ai_processors_default", "openai")

    async def _boom(*args, **kwargs):
        raise _provider_403()

    monkeypatch.setattr(llm_client, "get_embedding", _boom)


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/api/ai/embed",
            {
                "entity_type": "competence",
                "entity_id": str(uuid.uuid4()),
                "text_content": "Leadership",
            },
        ),
        ("/api/ai/search", {"query": "python"}),
    ],
)
async def test_provider_failure_is_a_localized_502(
    auth_client, failing_provider, path, body
):
    resp = await auth_client.post(path, json=body)

    assert resp.status_code == 502
    assert resp.json() == {
        "code": "ai_embedding_failed",
        "detail": translate("errors.ai_embedding_failed", "en"),
    }
    assert "unsupported_country" not in resp.text


def test_batch_task_records_the_failed_item(failing_provider, caplog):
    from app.modules.ai.tasks import batch_embed_task

    entity_id = str(uuid.uuid4())
    items = [{"entity_type": "competence", "entity_id": entity_id, "text_content": "x"}]
    # A copied context: the task binds the call-journal tenant into it.
    with caplog.at_level(logging.WARNING):
        result = contextvars.copy_context().run(
            batch_embed_task.run, items, str(uuid.uuid4())
        )

    assert result["processed"] == 0
    assert result["total"] == 1
    assert [e["entity_id"] for e in result["errors"]] == [entity_id]
    assert f"Embedding failed for {entity_id}" in caplog.text


async def test_a_bug_is_not_dressed_up_as_a_provider_failure(monkeypatch):
    async def _bug(*args, **kwargs):
        raise TypeError("a programming error")

    monkeypatch.setattr(llm_client, "get_embedding", _bug)
    with pytest.raises(TypeError):
        await ai_service._embed("x")
