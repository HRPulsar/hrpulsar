"""HRP-53: upload-from-URL endpoint rejects SSRF-y targets up-front.

The download path grants admins free egress, so the host check has to refuse
loopback / private / link-local addresses before httpx ever opens a socket.
These tests only exercise the pre-flight validator — the download itself is
covered by the existing integration suite once a real public URL is in play.
"""

from __future__ import annotations

import pytest
from app.modules.company import service
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/logo.png",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "",
        "not-a-url",
    ],
)
async def test_rejects_non_http_schemes(url: str) -> None:
    with pytest.raises(HTTPException) as exc:
        await service.upload_logo_from_url(None, None, None, url)  # type: ignore[arg-type]
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/logo.png",
        "http://localhost/logo.png",
        "http://10.0.0.5/logo.png",
        "http://192.168.1.1/logo.png",
        "http://169.254.169.254/latest/meta-data/",  # AWS IMDS
    ],
)
async def test_rejects_private_or_loopback_hosts(url: str) -> None:
    with pytest.raises(HTTPException) as exc:
        await service.upload_logo_from_url(None, None, None, url)  # type: ignore[arg-type]
    assert exc.value.status_code == 400
    assert "public" in exc.value.detail.lower()


async def test_rejects_unresolvable_host() -> None:
    # ".invalid" is reserved per RFC 6761 and will never resolve.
    with pytest.raises(HTTPException) as exc:
        await service.upload_logo_from_url(
            None, None, None, "https://no-such-host.invalid/logo.png"  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 400


async def test_redirect_to_loopback_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect-based SSRF: first hop is public, server sends 302 to 127.0.0.1.

    Without per-hop validation httpx would happily follow the redirect. The
    manual redirect loop in `upload_logo_from_url` must re-run `_assert_safe_url`
    on the new Location before issuing the next GET.
    """
    import socket as real_socket

    import httpx
    from app.modules.company import service as company_service

    public_ip = "198.51.100.10"  # TEST-NET-2, definitely "public"

    def fake_getaddrinfo(host: str, _port: object, *_a: object, **_kw: object) -> list:
        if host == "redir.example.com":
            return [(2, 1, 6, "", (public_ip, 0))]
        # Fall back to whatever ipaddress.ip_address would parse for literals.
        return real_socket.getaddrinfo(host, 0)

    monkeypatch.setattr(real_socket, "getaddrinfo", fake_getaddrinfo)

    def handler(request: httpx.Request) -> httpx.Response:
        # Every request to the mock client returns a redirect into loopback.
        return httpx.Response(302, headers={"location": "http://127.0.0.1/logo.png"})

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    class _PatchedClient(original_client):
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(company_service.httpx, "AsyncClient", _PatchedClient)

    with pytest.raises(HTTPException) as exc:
        await service.upload_logo_from_url(
            None, None, None, "http://redir.example.com/x.png"  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 400
    assert "public" in exc.value.detail.lower()
