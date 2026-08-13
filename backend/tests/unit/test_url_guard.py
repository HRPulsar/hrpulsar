"""SSRF guard for tenant-supplied endpoint URLs (``app/core/url_guard.py``).

HRP-505: two saas-only layers — save-time validation
(``ensure_public_base_url``) and the request-time pinning client
(``tenant_endpoint_http_client``). Deployment mode is monkeypatched in
every test: the suite env pins onprem (conftest) but CI matrices differ,
so nothing here may rely on the ambient value. Hostname tests stub the
DNS seam (``url_guard._getaddrinfo``); IP-literal tests need no DNS.
"""

import socket

import httpx
import pytest
from app.config import settings
from app.core import url_guard
from app.core.errors import AppError
from app.core.url_guard import (
    PinnedPublicIPTransport,
    ensure_public_base_url,
    tenant_endpoint_http_client,
)

ERR = "llm_base_url_not_public"

_PROXY_ENV = ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy",
              "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")


@pytest.fixture(autouse=True)
def _no_ambient_proxy(monkeypatch):
    """The pinning assertions below depend on there being no proxy — a
    corporate CI runner or dev box may export one. Clear them; the proxy
    tests set what they need explicitly."""
    for name in _PROXY_ENV:
        monkeypatch.delenv(name, raising=False)


PRIVATE_URLS = [
    # IPv4: loopback, RFC1918 (all three), link-local incl. cloud
    # metadata, CGNAT, "this network", multicast, reserved, unspecified
    "https://127.0.0.1:11434/v1",
    "https://10.0.0.5/v1",
    "https://172.16.0.1/v1",
    "https://192.168.1.20/v1",
    "https://169.254.169.254/latest/meta-data/",
    "https://100.64.0.1/v1",
    "https://0.1.2.3/v1",
    "https://224.0.0.1/v1",
    "https://240.0.0.1/v1",
    "https://0.0.0.0/v1",
    # IPv6: loopback, ULA fc00::/7, link-local fe80::/10, IPv4-mapped
    # (judged by the embedded IPv4), unspecified
    "https://[::1]/v1",
    "https://[fc00::1]/v1",
    "https://[fe80::1]/v1",
    "https://[::ffff:10.0.0.1]/v1",
    "https://[::]/v1",
]


def _stub_resolver(monkeypatch, batches):
    """Stub the DNS seam with successive per-call IP lists; returns the
    list of resolved hostnames for call-count assertions."""
    calls = []
    batches = list(batches)

    async def fake_getaddrinfo(host):
        calls.append(host)
        batch = batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in batch
        ]

    monkeypatch.setattr(url_guard, "_getaddrinfo", fake_getaddrinfo)
    return calls


# ─── Save-time layer ────────────────────────────────────────────────


async def test_saas_rejects_every_private_range(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    for url in PRIVATE_URLS:
        with pytest.raises(AppError) as err:
            await ensure_public_base_url(url, error_code=ERR)
        assert err.value.code == ERR, url


async def test_saas_rejects_malformed(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    for url in ("ftp://example.com/", "http://", "not-a-url"):
        with pytest.raises(AppError) as err:
            await ensure_public_base_url(url, error_code=ERR)
        assert err.value.code == ERR, url


async def test_saas_requires_https(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    with pytest.raises(AppError) as err:
        await ensure_public_base_url("http://8.8.8.8/v1", error_code=ERR)
    assert err.value.code == "llm_base_url_https_required"


async def test_saas_allows_public_ip_literal(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    await ensure_public_base_url("https://8.8.8.8/v1", error_code=ERR)


async def test_saas_allows_public_hostname(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    calls = _stub_resolver(monkeypatch, [["93.184.216.34"]])
    await ensure_public_base_url("https://llm.example.com/v1", error_code=ERR)
    assert calls == ["llm.example.com"]


async def test_saas_rejects_mixed_public_private_records(monkeypatch):
    """One private A record among public ones is the rebinding shape —
    every resolved address must be public."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    _stub_resolver(monkeypatch, [["93.184.216.34", "10.0.0.5"]])
    with pytest.raises(AppError) as err:
        await ensure_public_base_url("https://llm.example.com/v1", error_code=ERR)
    assert err.value.code == ERR


async def test_saas_rejects_unresolvable_host(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    _stub_resolver(monkeypatch, [socket.gaierror("NXDOMAIN")])
    with pytest.raises(AppError) as err:
        await ensure_public_base_url("https://nx.example.com/v1", error_code=ERR)
    assert err.value.code == ERR


async def test_onprem_is_noop(monkeypatch):
    """Self-hosted keeps private endpoints working (LAN Ollama, HRP-465)."""
    monkeypatch.setattr(settings, "deployment_mode", "onprem")
    await ensure_public_base_url("http://127.0.0.1:11434/v1", error_code=ERR)
    assert tenant_endpoint_http_client("http://127.0.0.1:11434/v1", error_code=ERR) is (
        None
    )


async def test_operator_allowlist_skips_ip_validation(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(
        settings, "ai_base_url_allowed_hosts", "corp-gw.example.com, other.host"
    )
    # Skips even the https requirement and DNS validation — operator's call.
    await ensure_public_base_url("http://CORP-GW.example.COM:8080/v1", error_code=ERR)
    # A host that is not listed still goes through the full guard.
    with pytest.raises(AppError):
        await ensure_public_base_url("http://10.0.0.5/v1", error_code=ERR)


async def test_operator_allowlist_client_still_forbids_redirects(monkeypatch):
    """The allowlist waives IP validation, not the redirect ban — a vetted
    gateway with an open redirect must not be followed onto the metadata
    service (HRP-505 review)."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "ai_base_url_allowed_hosts", "corp-gw.example.com")
    client = tenant_endpoint_http_client(
        "https://corp-gw.example.com:8080/v1", error_code=ERR
    )
    assert client is not None
    assert client.follow_redirects is False
    # No IP validation: not a pinning transport.
    assert not isinstance(client._transport, PinnedPublicIPTransport)
    await client.aclose()


# ─── Request-time layer (pinning transport) ─────────────────────────


def _capture_inner_transport(monkeypatch, responses=None):
    """Intercept the connection-pool layer under PinnedPublicIPTransport;
    the guard's own logic (resolve → validate → rewrite) runs unmodified."""
    seen = []
    responses = list(responses or [])

    async def fake_inner(self, request):
        seen.append(request)
        return responses.pop(0) if responses else httpx.Response(200, json={})

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_inner)
    return seen


async def test_pinned_transport_connects_to_validated_ip(monkeypatch):
    """Anti-rebinding: the validated IP is what the connection targets —
    the URL host becomes the IP literal (no second resolve inside httpx),
    while Host header and TLS SNI keep the original hostname."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    _stub_resolver(monkeypatch, [["93.184.216.34"], ["10.0.0.5"]])
    seen = _capture_inner_transport(monkeypatch)

    client = tenant_endpoint_http_client("https://llm.example.com/v1", error_code=ERR)
    assert isinstance(client._transport, PinnedPublicIPTransport)

    resp = await client.post("https://llm.example.com/v1/chat/completions")
    assert resp.status_code == 200
    sent = seen[0]
    assert sent.url.host == "93.184.216.34"
    assert sent.headers["host"] == "llm.example.com"
    assert sent.extensions["sni_hostname"] == "llm.example.com"

    # DNS flipped to a private address after save time (second stub
    # batch) — the next request re-validates and refuses to connect.
    with pytest.raises(AppError) as err:
        await client.post("https://llm.example.com/v1/chat/completions")
    assert err.value.code == ERR
    assert len(seen) == 1
    await client.aclose()


async def test_pinned_transport_rejects_pre_guard_http_row(monkeypatch):
    """A row saved before the https requirement still cannot go out over
    plain http on saas."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    seen = _capture_inner_transport(monkeypatch)
    client = tenant_endpoint_http_client("http://ollama.internal/v1", error_code=ERR)
    with pytest.raises(AppError) as err:
        await client.post("http://ollama.internal/v1/chat/completions")
    assert err.value.code == "llm_base_url_https_required"
    assert seen == []
    await client.aclose()


async def test_redirects_are_not_followed(monkeypatch):
    """A 3xx from the tenant's endpoint surfaces instead of steering the
    request (e.g. onto the metadata service)."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    _stub_resolver(monkeypatch, [["93.184.216.34"]])
    seen = _capture_inner_transport(
        monkeypatch,
        [httpx.Response(302, headers={"location": "http://169.254.169.254/"})],
    )
    client = tenant_endpoint_http_client("https://llm.example.com/v1", error_code=ERR)
    assert client.follow_redirects is False
    resp = await client.post("https://llm.example.com/v1/chat/completions")
    assert resp.status_code == 302
    assert len(seen) == 1
    await client.aclose()


async def test_ipv6_pin_is_bracketed(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    _stub_resolver(monkeypatch, [["2606:4700::1111"]])
    seen = _capture_inner_transport(monkeypatch)
    client = tenant_endpoint_http_client("https://llm.example.com/v1", error_code=ERR)
    await client.post("https://llm.example.com/v1/chat/completions")
    assert seen[0].url.host == "2606:4700::1111"
    assert str(seen[0].url).startswith("https://[2606:4700::1111]/")
    await client.aclose()


# ─── Egress-proxy mode (HRP-565) ────────────────────────────────────


async def test_proxy_mode_pins_only_direct_hosts(monkeypatch):
    """With an egress proxy (HRP-565) the proxy makes and controls the
    proxied connection, so those hosts are not pinned. A host that bypasses
    the proxy via NO_PROXY is a direct connection — it is still validated
    and pinned, so it cannot be the rebinding hole. Save-time DNS
    validation is proxy-independent."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setenv("HTTPS_PROXY", "http://egress.local:3128")
    monkeypatch.setenv("NO_PROXY", "internal.svc")

    client = tenant_endpoint_http_client("https://llm.example.com/v1", error_code=ERR)
    assert client.follow_redirects is False
    proxied = client._transport_for_url(httpx.URL("https://api.openai.com/v1"))
    direct = client._transport_for_url(httpx.URL("https://internal.svc/v1"))
    assert not isinstance(proxied, PinnedPublicIPTransport)
    assert isinstance(direct, PinnedPublicIPTransport)
    await client.aclose()

    # Save-time validation applies whether or not a proxy is configured.
    with pytest.raises(AppError):
        await ensure_public_base_url("https://10.0.0.5/v1", error_code=ERR)


async def test_no_proxy_env_means_pinning(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    client = tenant_endpoint_http_client("https://llm.example.com/v1", error_code=ERR)
    assert isinstance(client._transport, PinnedPublicIPTransport)
    await client.aclose()


# ─── llm_client wiring ──────────────────────────────────────────────


async def test_get_openai_uses_guarded_client_on_saas(monkeypatch):
    from app.modules.ai import llm_client

    monkeypatch.setattr(settings, "deployment_mode", "saas")
    llm_client._client_cache.clear()
    sdk = llm_client._get_openai("k", "https://tenant-llm.example.com/v1")
    assert isinstance(sdk._client._transport, PinnedPublicIPTransport)
    # A guarded client must not retry a deterministic guard rejection.
    assert sdk.max_retries == 0
    await sdk.close()
    llm_client._client_cache.clear()


async def test_get_openai_keeps_default_client_on_onprem(monkeypatch):
    from app.modules.ai import llm_client

    monkeypatch.setattr(settings, "deployment_mode", "onprem")
    llm_client._client_cache.clear()
    sdk = llm_client._get_openai("k", "http://ollama.internal:11434/v1")
    assert not isinstance(sdk._client._transport, PinnedPublicIPTransport)
    assert sdk.max_retries == 3
    await sdk.close()
    llm_client._client_cache.clear()


async def test_generate_openai_surfaces_guard_apperror(monkeypatch):
    """The guard's AppError must reach the caller, not the SDK's opaque
    APIConnectionError wrapper (HRP-505 review)."""
    from app.modules.ai import llm_client

    monkeypatch.setattr(settings, "deployment_mode", "saas")
    # DNS flips to a private address after save time — the pinning
    # transport refuses to connect on the request path.
    _stub_resolver(monkeypatch, [["10.0.0.5"]])
    llm_client._client_cache.clear()
    with pytest.raises(AppError) as err:
        await llm_client._generate_openai(
            "hi", None, "llama3", 0.3, 256,
            api_key="k", base_url="https://rebind.example.com/v1",
        )
    assert err.value.code == ERR
    llm_client._client_cache.clear()


async def test_extra_blocked_nets_rejected(monkeypatch):
    """6to4 relay anycast and deprecated IPv6 site-local classify as public
    by ipaddress.is_global but are not reachable public unicast."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    for host_ip in ("192.88.99.1", "fec0::1"):
        _stub_resolver(monkeypatch, [[host_ip]])
        with pytest.raises(AppError) as err:
            await ensure_public_base_url("https://x.example.com/v1", error_code=ERR)
        assert err.value.code == ERR, host_ip


async def test_saas_wraps_parse_errors_as_apperror(monkeypatch):
    """A malformed URL is tenant input — 400, not a 500 (HRP-505 review)."""
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    long_label = "a" * 70
    for url in ("https://[::1/v1", "https://[oops]/v1", f"https://{long_label}.example/v1"):
        with pytest.raises(AppError) as err:
            await ensure_public_base_url(url, error_code=ERR)
        assert err.value.code == ERR, url


# ─── API integration (save-time layer over HTTP) ────────────────────


async def test_create_llm_provider_api_rejects_private_on_saas(
    auth_client, monkeypatch
):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    resp = await auth_client.post(
        "/api/recruitment/settings/llm-providers",
        json={
            "provider": "azure",
            "model": "llama3",
            "settings": {"base_url": "https://10.0.0.5/v1"},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == ERR

    resp = await auth_client.post(
        "/api/recruitment/settings/llm-providers",
        json={
            "provider": "azure",
            "model": "llama3",
            "settings": {"base_url": "http://8.8.8.8/v1"},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "llm_base_url_https_required"


async def test_llm_provider_api_allows_private_on_onprem_and_guards_update(
    auth_client, monkeypatch
):
    monkeypatch.setattr(settings, "deployment_mode", "onprem")
    resp = await auth_client.post(
        "/api/recruitment/settings/llm-providers",
        json={
            "provider": "azure",
            "model": "llama3",
            "settings": {"base_url": "http://192.168.1.50:11434/v1"},
        },
    )
    assert resp.status_code == 201
    config_id = resp.json()["id"]

    # The same row updated on a saas deployment (mode flipped mid-test =
    # the migration scenario) may not point back inside the perimeter.
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    resp = await auth_client.put(
        f"/api/recruitment/settings/llm-providers/{config_id}",
        json={"settings": {"base_url": "https://169.254.169.254/v1"}},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == ERR
