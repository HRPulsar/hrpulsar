"""Trusted-proxy-aware client IP resolution, shared across routers.

Behind a load balancer (Cloudflare + DO), ``request.client.host`` is the LB's
IP, so a naive per-IP rate limit collapses every tenant into one bucket; and
if ``X-Forwarded-For`` is honoured unconditionally, a client hitting the origin
directly forges a fresh IP per request and bypasses the throttle entirely.

The fix (originally in the demo router, HRP-276/M5, now generalised): honour
``X-Forwarded-For`` only when the direct socket peer sits inside
``settings.trusted_proxies``. In dev / bare deploys the list is empty and XFF
is ignored.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request

from app.config import settings


def _parse_trusted_proxies(raw: str) -> list[ipaddress._BaseNetwork]:
    """Comma-separated CIDR / exact-IP list → parsed networks.

    Exact IPs are coerced into single-host networks so membership testing
    collapses to one ``ip in net`` check. Empty / malformed entries skipped.
    """
    nets: list[ipaddress._BaseNetwork] = []
    for raw_token in (raw or "").split(","):
        token = raw_token.strip()
        if not token:
            continue
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            continue
    return nets


def _peer_is_trusted(peer: str | None, trusted: list[ipaddress._BaseNetwork]) -> bool:
    if not peer or not trusted:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(addr in net for net in trusted)


def client_ip(request: Request) -> str | None:
    """Source IP for rate-limiting, with trusted-proxy XFF handling.

    Honours the first ``X-Forwarded-For`` hop only when the direct socket
    peer is a configured trusted proxy; otherwise returns the socket peer.
    """
    peer = request.client.host if request.client else None
    # Read the fallback at call time so a runtime override of either setting
    # (e.g. tests monkeypatching demo_trusted_proxies) is honoured, not just
    # the construction-time inheritance in Settings.
    raw = settings.trusted_proxies or settings.demo_trusted_proxies
    trusted = _parse_trusted_proxies(raw)
    if trusted and _peer_is_trusted(peer, trusted):
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            first_hop = fwd.split(",")[0].strip()
            if first_hop:
                return first_hop
    return peer
