"""HRP-986: a self-hosted OpenAI-compatible model is connected from the
LLM providers page - base_url saved without a key - and the connection
check sends one tiny call through that row's own target, answering ``ok``
or a localized code, never the provider's text."""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from app.config import settings
from app.core import ai_usage_hooks
from app.core.errors import AppError
from app.main import app
from app.modules.ai import llm_client
from app.modules.company.models import Tenant
from app.modules.recruitment import settings_service
from app.modules.recruitment.models import LLMProviderConfig

from tests.unit.test_recruitment_manager_scope import _headers, _user

BASE = "/api/recruitment/settings/llm-providers"
LOCAL_URL = "http://192.168.1.50:11434/v1"
RAW = "raw-provider-body"


class _HttpError(Exception):
    """A provider SDK error: OpenAI/Anthropic name the HTTP status
    ``status_code``, Gemini ``code``."""

    def __init__(self, attr: str, value: int) -> None:
        super().__init__(f"{RAW} {value}")
        setattr(self, attr, value)


def _provider(**kwargs):
    kwargs.setdefault("return_value", ("OK", llm_client._Usage()))
    return patch.object(
        llm_client, "_generate_openai", new_callable=AsyncMock, **kwargs
    )


@pytest.fixture
async def local_row(auth_client, monkeypatch) -> str:
    monkeypatch.setattr(settings, "deployment_mode", "onprem")
    resp = await auth_client.post(
        BASE,
        json={
            "provider": "openai",
            "model": "llama3.1",
            "api_key": None,
            "settings": {"base_url": LOCAL_URL},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_a_keyless_local_row_is_probed_on_its_own_server(auth_client, local_row):
    [row] = (await auth_client.get(BASE)).json()
    assert row["settings"] == {"base_url": LOCAL_URL}
    assert row["key_status"] == "missing"

    with _provider() as call:
        resp = await auth_client.post(f"{BASE}/{local_row}/test")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    call.assert_awaited_once()
    args, kwargs = call.call_args
    assert args[2] == "llama3.1"
    assert args[4] == settings_service._PROBE_MAX_TOKENS
    assert kwargs["base_url"] == LOCAL_URL
    assert kwargs["api_key"] is None


async def test_an_answer_cut_by_the_tiny_budget_is_ok(auth_client, local_row):
    truncated = llm_client.LLMOutputTruncatedError("llama3.1", 16)
    with _provider(side_effect=truncated):
        resp = await auth_client.post(f"{BASE}/{local_row}/test")
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (httpx.ConnectError(RAW), "llm_provider_test_unreachable"),
        (_HttpError("status_code", 401), "llm_provider_test_auth_failed"),
        (_HttpError("status_code", 403), "llm_provider_test_auth_failed"),
        (_HttpError("code", 404), "llm_provider_test_model_not_found"),
        (_HttpError("status_code", 500), "llm_provider_test_failed"),
        (ValueError(RAW), "llm_provider_test_failed"),
    ],
)
async def test_a_failure_is_a_code_not_the_providers_text(
    auth_client, local_row, error, code
):
    with _provider(side_effect=error):
        resp = await auth_client.post(f"{BASE}/{local_row}/test")
    assert resp.status_code == 502
    assert resp.json()["code"] == code
    assert RAW not in resp.text


async def test_a_failure_is_logged_without_the_providers_text(
    auth_client, local_row, caplog
):
    """Review B5: the docstring's promise - the log keeps the details."""
    with (
        caplog.at_level("WARNING", logger=settings_service.log.name),
        _provider(side_effect=_HttpError("status_code", 500)),
    ):
        await auth_client.post(f"{BASE}/{local_row}/test")
    [record] = [r for r in caplog.records if "probe failed" in r.getMessage()]
    assert local_row in record.getMessage()
    assert "_HttpError" in record.getMessage()
    assert RAW not in record.getMessage()


async def test_a_server_that_never_answers_times_out(
    auth_client, local_row, monkeypatch
):
    monkeypatch.setattr(settings_service, "_PROBE_TIMEOUT_S", 0.05)

    async def _hang(*args, **kwargs):
        await asyncio.sleep(5)

    with _provider(side_effect=_hang):
        resp = await auth_client.post(f"{BASE}/{local_row}/test")
    assert resp.json()["code"] == "llm_provider_test_unreachable"


async def test_the_ssrf_guard_answers_with_its_own_code(auth_client, local_row):
    with _provider(side_effect=AppError("llm_base_url_not_public", 400)):
        resp = await auth_client.post(f"{BASE}/{local_row}/test")
    assert resp.status_code == 400
    assert resp.json()["code"] == "llm_base_url_not_public"


async def test_a_row_without_own_credentials_is_refused_unsent(auth_client):
    # It would fall back to the platform key - that is not a check of it.
    resp = await auth_client.post(
        BASE, json={"provider": "anthropic", "model": "claude-sonnet-5"}
    )
    with patch.object(
        llm_client, "_generate_anthropic", new_callable=AsyncMock
    ) as call:
        resp = await auth_client.post(f"{BASE}/{resp.json()['id']}/test")
    assert resp.status_code == 422
    assert resp.json()["code"] == "llm_provider_test_not_dispatchable"
    call.assert_not_awaited()


async def test_another_tenants_row_is_not_found(auth_client, db):
    other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
    db.add(other)
    await db.commit()
    row = LLMProviderConfig(
        tenant_id=other.id,
        provider="openai",
        model="llama3.1",
        settings={"base_url": LOCAL_URL},
    )
    db.add(row)
    await db.commit()

    with _provider() as call:
        resp = await auth_client.post(f"{BASE}/{row.id}/test")
    assert resp.status_code == 404
    call.assert_not_awaited()


async def test_only_admins_probe(client, db, tenant, local_row):
    recruiter = await _user(db, tenant, "recruiter")
    with _provider() as call:
        resp = await client.post(
            f"{BASE}/{local_row}/test", headers=_headers(recruiter)
        )
    assert resp.status_code == 403
    call.assert_not_awaited()


async def test_the_probe_call_is_attributed(
    auth_client, local_row, tenant, user, monkeypatch
):
    # The call spends the tenant's key: the AI call log must name who and
    # what, not file it as unattributed.
    seen: list[ai_usage_hooks.CallContext | None] = []

    async def _generate(*args, **kwargs):
        seen.append(ai_usage_hooks.current())
        return "OK"

    monkeypatch.setattr(llm_client, "generate", _generate)
    resp = await auth_client.post(f"{BASE}/{local_row}/test")

    assert resp.status_code == 200
    (ctx,) = seen
    assert ctx is not None
    assert ctx.action == "recruitment.llm_provider_probe"
    assert (ctx.tenant_id, ctx.user_id) == (tenant.id, user.id)
    assert (ctx.entity_type, str(ctx.entity_id)) == ("llm_provider", local_row)
    assert ai_usage_hooks.current() is None


@pytest.mark.parametrize(
    ("provider", "provider_settings"),
    [("azure", None), ("gigachat", {"base_url": "gigachat.local:8080/v1"})],
)
async def test_azure_and_gigachat_need_their_server_address(
    auth_client, provider, provider_settings
):
    # Served only through their own endpoint: without an http(s) base_url
    # the row is never dispatched, so it is not saved at all.
    resp = await auth_client.post(
        BASE,
        json={
            "provider": provider,
            "model": "gpt-4o",
            "api_key": "sk-x",
            "settings": provider_settings,
        },
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "llm_base_url_required"


async def test_an_update_may_not_drop_the_address(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "onprem")
    resp = await auth_client.post(
        BASE,
        json={
            "provider": "azure",
            "model": "gpt-4o",
            "settings": {"base_url": LOCAL_URL},
        },
    )
    assert resp.status_code == 201, resp.text
    resp = await auth_client.put(f"{BASE}/{resp.json()['id']}", json={"settings": {}})
    assert resp.status_code == 422
    assert resp.json()["code"] == "llm_base_url_required"


_PAGE = (
    Path(__file__).resolve().parents[3]
    / "frontend/src/app/(dashboard)/recruitment/settings/llm-providers/page.tsx"
)


@pytest.mark.skipif(not _PAGE.exists(), reason="frontend tree not present")
def test_the_page_calls_urls_the_app_serves():
    urls = re.findall(
        r"/recruitment/settings/llm-providers[^`\"']*", _PAGE.read_text("utf-8")
    )
    referenced = {"/api" + re.sub(r"\$\{[^}]*\}", "{}", u) for u in urls}
    mounted = {
        re.sub(r"\{[^}]*\}", "{}", getattr(route, "path", "")) for route in app.routes
    }
    assert f"{BASE}/{{}}/test" in referenced
    assert referenced <= mounted, sorted(referenced - mounted)
