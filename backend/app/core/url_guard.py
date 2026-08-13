"""Outbound-URL guard for tenant-supplied endpoints (SSRF, HRP-505).

On saas deployments a tenant-configured URL turns into a server-side
request from inside the platform perimeter, so its host must resolve to
public addresses only. On self-hosted installs private endpoints are the
point (a LAN Ollama, an in-rack vLLM) — the guard is a no-op there.

Two layers (both saas-only):

- Save time: :func:`ensure_public_base_url` rejects a URL whose scheme is
  not https or whose host resolves to any non-public address.
- Request time: :func:`tenant_endpoint_http_client` builds the httpx
  client the SDK talks through. Its transport re-resolves the host on
  every request, re-validates every address, and connects to the
  validated IP itself (the URL host is rewritten to the IP literal, TLS
  keeps the original hostname via SNI) — so a DNS record flipped to a
  private address after save time cannot redirect the connection
  (anti-rebinding), and httpx never performs a second, unchecked resolve.
  Redirects are not followed: a 3xx from the tenant's endpoint surfaces
  as an error instead of steering the request elsewhere.

Escape hatches:

- ``AI_BASE_URL_ALLOWED_HOSTS`` (operator env, comma-separated hostnames)
  skips IP validation for listed hosts even on saas; the request-time
  client still forbids redirects (the redirect ban is unconditional for
  provider calls).
- An egress proxy (``HTTPS_PROXY``/``ALL_PROXY``, HRP-565) makes the
  target connection itself, so the platform does not resolve or pin the
  proxied host (it may not even have direct DNS/egress there). Hosts that
  *bypass* the proxy via ``NO_PROXY`` are direct connections, so they are
  still resolved, validated and pinned. Save-time DNS validation applies
  regardless of proxy configuration.
"""

import asyncio
import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import status

from app.config import settings
from app.core.errors import AppError

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# Ranges ``ipaddress.is_global`` still reports as global but which are not
# reachable public unicast on a modern cloud — deny them explicitly
# (HRP-505 review). 6to4 relay anycast (RFC 7526) and deprecated IPv6
# site-local (RFC 3879).
_EXTRA_BLOCKED_NETS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("192.88.99.0/24"),
    ipaddress.ip_network("fec0::/10"),
)


def _operator_allowed_hosts() -> frozenset[str]:
    raw = settings.ai_base_url_allowed_hosts or ""
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


def host_is_operator_allowed(host: str | None) -> bool:
    """True when the operator allowlisted this exact hostname via env."""
    return host is not None and host.lower() in _operator_allowed_hosts()


def _ip_is_public(ip: _IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        # ::ffff:10.0.0.1 reaches the embedded IPv4 host — judge that.
        ip = ip.ipv4_mapped
    for net in _EXTRA_BLOCKED_NETS:
        if ip.version == net.version and ip in net:
            return False
    # ``is_global`` follows the IANA special-purpose registries (covers
    # RFC1918, loopback, link-local incl. 169.254.169.254, CGNAT
    # 100.64.0.0/10, 0.0.0.0/8, fc00::/7, fe80::/10, …) but reports
    # multicast ranges as global — keep the explicit flags as well.
    return ip.is_global and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _getaddrinfo(host: str) -> list[Any]:
    """DNS seam — tests stub this out; production always resolves live."""
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)


async def _resolve_ips(host: str, *, error_code: str) -> list[_IPAddress]:
    try:
        infos = await _getaddrinfo(host)
    except (socket.gaierror, UnicodeError) as exc:
        # gaierror: no such host. UnicodeError: an over-long label the IDNA
        # codec refuses — a tenant string, not a server fault, so 400.
        raise AppError(error_code, status.HTTP_400_BAD_REQUEST) from exc
    ips: list[_IPAddress] = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise AppError(error_code, status.HTTP_400_BAD_REQUEST)
    return ips


async def _resolve_public_ips(host: str, *, error_code: str) -> list[_IPAddress]:
    """Every resolved address must be public — one private A/AAAA record
    among public ones is exactly how a rebinding payload looks."""
    ips = await _resolve_ips(host, error_code=error_code)
    for ip in ips:
        if not _ip_is_public(ip):
            raise AppError(error_code, status.HTTP_400_BAD_REQUEST)
    return ips


def _parse_hostname(url: str, *, error_code: str) -> tuple[str, str]:
    """``(scheme, hostname)`` for a tenant URL, or a 400 AppError.

    ``urlparse``/``.hostname`` raise ``ValueError`` on a malformed IPv6
    literal (``[::1``, ``[oops]``) — that is tenant input, not a server
    fault, so it must not surface as a 500."""
    try:
        parsed = urlparse(url)
        scheme, hostname = parsed.scheme, parsed.hostname
    except ValueError as exc:
        raise AppError(error_code, status.HTTP_400_BAD_REQUEST) from exc
    if scheme not in ("http", "https") or not hostname:
        raise AppError(error_code, status.HTTP_400_BAD_REQUEST)
    return scheme, hostname


async def ensure_public_base_url(url: str, *, error_code: str) -> None:
    """Save-time layer: validate a tenant-supplied endpoint URL (saas only).

    Besides ``error_code`` this can raise ``llm_base_url_https_required``
    — the scheme rule has its own message. Operator-allowlisted hosts skip
    the whole guard including the https requirement (a perimeter gateway
    may be plain http): that is the operator's explicit call, pinned by
    ``test_operator_allowlist_skips_ip_validation``.
    """
    if settings.deployment_mode != "saas":
        return
    scheme, hostname = _parse_hostname(url, error_code=error_code)
    if host_is_operator_allowed(hostname):
        return
    if scheme != "https":
        raise AppError("llm_base_url_https_required", status.HTTP_400_BAD_REQUEST)
    await _resolve_public_ips(hostname, error_code=error_code)


def _egress_proxy_active() -> bool:
    return any(
        os.environ.get(name)
        for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")
    )


class PinnedPublicIPTransport(httpx.AsyncHTTPTransport):
    """Direct-connection transport that resolves, validates, and pins.

    Per request: resolve the URL host, require every address to be
    public, rewrite the URL host to the first validated IP (the Host
    header was already built from the original URL, and ``sni_hostname``
    keeps TLS handshaking — SNI and certificate check — against the
    hostname), then hand off to the regular connection pool. The pool
    sees an IP literal, so no second resolve can pick a different,
    unvalidated address.
    """

    def __init__(self, *, error_code: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._error_code = error_code

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if not host:
            raise AppError(self._error_code, status.HTTP_400_BAD_REQUEST)
        if request.url.scheme != "https":
            # A row saved before the https requirement still reaches this
            # transport — reject it here too.
            raise AppError(
                "llm_base_url_https_required", status.HTTP_400_BAD_REQUEST
            )
        ips = await _resolve_public_ips(host, error_code=self._error_code)
        pinned = next(
            (ip for ip in ips if isinstance(ip, ipaddress.IPv4Address)), ips[0]
        )
        if str(pinned) != host:
            request.url = request.url.copy_with(host=str(pinned))
            request.extensions["sni_hostname"] = host
        return await super().handle_async_request(request)


def _proxy_aware_mounts(
    error_code: str,
) -> dict[str, httpx.AsyncBaseTransport | None]:
    """httpx transport mounts derived from the egress-proxy env.

    Proxied patterns get an ordinary proxy transport (the proxy makes and
    controls the connection — HRP-565). ``NO_PROXY`` patterns are direct
    connections, so they get the pinning transport: a tenant host that
    bypasses the proxy is still resolved, validated and pinned.
    """
    # Imported at call time but *not* guarded: this is a security control,
    # and quietly handing back an unpinned client when an httpx upgrade
    # moves the helper would remove the SSRF layer with no trace. Let the
    # ImportError surface (review fix); the version is pinned in
    # requirements.txt.
    from httpx._utils import get_environment_proxies

    mounts: dict[str, httpx.AsyncBaseTransport | None] = {}
    for pattern, proxy_url in get_environment_proxies().items():
        if proxy_url is None:
            mounts[pattern] = PinnedPublicIPTransport(error_code=error_code)
        else:
            mounts[pattern] = httpx.AsyncHTTPTransport(proxy=proxy_url)
    return mounts


def tenant_endpoint_http_client(
    base_url: str, *, error_code: str, timeout: httpx.Timeout | None = None
) -> httpx.AsyncClient | None:
    """Request-time layer: the httpx client for a tenant-supplied endpoint.

    Returns None only when the guard does not apply at all (onprem) — the
    caller keeps its default SDK client. On saas the returned client never
    follows redirects, and:

    - operator-allowlisted host → no IP validation (vetted), redirects off;
    - egress proxy configured → proxied hosts go through the proxy
      unpinned, ``NO_PROXY`` (direct) hosts are validated and pinned;
    - otherwise → every request is validated and pinned to a public IP.
    """
    if settings.deployment_mode != "saas":
        return None
    try:
        hostname = urlparse(base_url).hostname
    except ValueError:
        # Malformed URL — let the pinning transport reject it per request
        # rather than deciding the allowlist off a parse that already failed.
        hostname = None
    if host_is_operator_allowed(hostname):
        return httpx.AsyncClient(follow_redirects=False, timeout=timeout)
    if _egress_proxy_active():
        return httpx.AsyncClient(
            mounts=_proxy_aware_mounts(error_code),
            transport=PinnedPublicIPTransport(error_code=error_code),
            follow_redirects=False,
            timeout=timeout,
        )
    return httpx.AsyncClient(
        transport=PinnedPublicIPTransport(error_code=error_code),
        follow_redirects=False,
        timeout=timeout,
    )
