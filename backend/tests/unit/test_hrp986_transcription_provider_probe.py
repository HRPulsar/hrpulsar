"""HRP-986 REDO: "Test connection" on the transcription providers page.

The LLM probe's twin: the row is resolved the way the transcription chain
resolves it (its own key, or its own Whisper server) and the provider's
cheapest authenticated call goes out - never audio, never the platform key.
A failure comes back as the LLM probe's codes, never the provider's text.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import httpx
import pytest
from app.config import settings
from app.main import app
from app.modules.company.models import Tenant
from app.modules.recruitment.models import TranscriptionProviderConfig

from tests.unit.test_recruitment_manager_scope import _headers, _user

BASE = "/api/recruitment/settings/transcription-providers"
RAW = "raw-provider-body"
_RealClient = httpx.AsyncClient


@pytest.fixture
def provider_api(monkeypatch):
    """Every outbound httpx call lands here; ``calls`` records them."""
    state: dict = {"calls": [], "respond": lambda request: httpx.Response(200)}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"].append(request)
        return state["respond"](request)

    def make(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealClient(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", make)
    return state


async def _row(auth_client, provider: str, api_key: str | None, row_settings=None):
    resp = await auth_client.post(
        BASE,
        json={"provider": provider, "api_key": api_key, "settings": row_settings},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.parametrize(
    ("provider", "api_key", "row_settings", "method", "url", "auth"),
    [
        (
            "assemblyai",
            "aai-key",
            None,
            "GET",
            "https://api.assemblyai.com/v2/transcript?limit=1",
            ("authorization", "aai-key"),
        ),
        (
            "deepgram",
            "dg-key",
            None,
            "GET",
            "https://api.deepgram.com/v1/projects",
            ("authorization", "Token dg-key"),
        ),
        (
            "whisper",
            "sk-key",
            None,
            "GET",
            "https://api.openai.com/v1/models",
            ("authorization", "Bearer sk-key"),
        ),
        (
            # The workspace's own server without a key: its address, no auth.
            "whisper",
            None,
            {"base_url": "http://192.168.1.60:8000/v1"},
            "GET",
            "http://192.168.1.60:8000/v1/models",
            ("authorization", None),
        ),
        (
            "yandex_speechkit",
            "ya-key",
            {"folder_id": "b1gfolder"},
            "POST",
            "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
            "?folderId=b1gfolder&format=lpcm&sampleRateHertz=8000",
            ("authorization", "Api-Key ya-key"),
        ),
    ],
)
async def test_each_provider_gets_its_cheapest_authenticated_call(
    auth_client,
    provider_api,
    monkeypatch,
    provider,
    api_key,
    row_settings,
    method,
    url,
    auth,
):
    monkeypatch.setattr(settings, "deployment_mode", "onprem")
    row_id = await _row(auth_client, provider, api_key, row_settings)

    resp = await auth_client.post(f"{BASE}/{row_id}/test")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok"}
    [request] = provider_api["calls"]
    assert request.method == method
    assert str(request.url) == url
    assert request.headers.get(auth[0]) == auth[1]
    # Never a recording: at most a tenth of a second of silence (SpeechKit).
    assert len(request.content) <= 1600


@pytest.mark.parametrize(
    ("respond", "code"),
    [
        (httpx.Response(401, text=RAW), "llm_provider_test_auth_failed"),
        (httpx.Response(403, text=RAW), "llm_provider_test_auth_failed"),
        (httpx.Response(404, text=RAW), "llm_provider_test_model_not_found"),
        (httpx.Response(500, text=RAW), "llm_provider_test_failed"),
        (httpx.ConnectError(RAW), "llm_provider_test_unreachable"),
    ],
)
async def test_a_failure_is_a_code_not_the_providers_text(
    auth_client, provider_api, respond, code
):
    row_id = await _row(auth_client, "deepgram", "dg-key")

    def _respond(request):
        if isinstance(respond, Exception):
            raise respond
        return respond

    provider_api["respond"] = _respond
    resp = await auth_client.post(f"{BASE}/{row_id}/test")

    assert resp.status_code == 502
    assert resp.json()["code"] == code
    assert RAW not in resp.text


async def test_a_row_on_the_platform_key_is_refused_unsent(auth_client, provider_api):
    row_id = await _row(auth_client, "deepgram", None)

    resp = await auth_client.post(f"{BASE}/{row_id}/test")

    assert resp.status_code == 422
    assert resp.json()["code"] == "llm_provider_test_not_dispatchable"
    assert provider_api["calls"] == []


async def test_speechkit_without_a_folder_says_so(
    auth_client, provider_api, monkeypatch
):
    monkeypatch.setattr(settings, "yandex_folder_id", "")
    row_id = await _row(auth_client, "yandex_speechkit", "ya-key")

    resp = await auth_client.post(f"{BASE}/{row_id}/test")

    assert resp.status_code == 422
    assert resp.json()["code"] == "transcription_provider_test_folder_missing"
    assert provider_api["calls"] == []


async def test_another_tenants_row_is_not_found(auth_client, db, provider_api):
    other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
    db.add(other)
    await db.commit()
    row = TranscriptionProviderConfig(tenant_id=other.id, provider="deepgram")
    db.add(row)
    await db.commit()

    resp = await auth_client.post(f"{BASE}/{row.id}/test")

    assert resp.status_code == 404
    assert provider_api["calls"] == []


async def test_only_admins_probe(auth_client, client, db, tenant, provider_api):
    row_id = await _row(auth_client, "deepgram", "dg-key")
    recruiter = await _user(db, tenant, "recruiter")

    resp = await client.post(f"{BASE}/{row_id}/test", headers=_headers(recruiter))

    assert resp.status_code == 403
    assert provider_api["calls"] == []


_PAGE = (
    Path(__file__).resolve().parents[3]
    / "frontend/src/app/(dashboard)/recruitment/settings/transcription-providers/page.tsx"
)


@pytest.mark.skipif(not _PAGE.exists(), reason="frontend tree not present")
def test_the_page_calls_urls_the_app_serves():
    urls = re.findall(
        r"/recruitment/settings/transcription-providers[^`\"']*",
        _PAGE.read_text("utf-8"),
    )
    referenced = {"/api" + re.sub(r"\$\{[^}]*\}", "{}", u) for u in urls}
    mounted = {
        re.sub(r"\{[^}]*\}", "{}", getattr(route, "path", "")) for route in app.routes
    }
    assert f"{BASE}/{{}}/test" in referenced
    assert referenced <= mounted, sorted(referenced - mounted)
