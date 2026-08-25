"""Trusted-proxy-aware client IP resolution, shared across routers.

Behind a load balancer (Cloudflare + DO), ``request.client.host`` is the LB's
IP, so a naive per-IP rate limit collapses every tenant into one bucket; and
if ``X-Forwarded-For`` is honoured unconditionally, a client hitting the origin
directly forges a fresh IP per request and bypasses the throttle entirely.

The fix (originally in the demo router, HRP-276/M5, now generalised): honour
``X-Forwarded-For`` only when the direct socket peer sits inside
``settings.trusted_proxies``, and read the chain from the right so a forged
prefix the client sent along is discarded.

``trusted_proxies`` unset falls back to the private ranges (HRP-645): in the
shipped bundle only Caddy publishes ports (``deploy/docker-compose.saas.yml``),
so a private socket peer IS our own proxy and a request that reached the app
from the public internet can never present one. Pinning the proxy's literal
address in the host ``.env`` instead would rot on the next Docker network
recreate — silently, back into a single global bucket.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request

from app.config import settings

# RFC 1918 / RFC 4193 / loopback. Fixed by standard, so unlike a container
# address this list cannot go stale.
_PRIVATE_PROXIES: list[ipaddress._BaseNetwork] = [
    ipaddress.ip_network(cidr)
    for cidr in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "::1/128",
        "fc00::/7",
    )
]


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

    Honours ``X-Forwarded-For`` only when the direct socket peer is a trusted
    proxy, and then takes the right-most hop that is not itself trusted.

    Right-most, not first: Caddy's ``reverse_proxy`` *appends* the peer it saw
    to whatever the client sent, so ``X-Forwarded-For: 203.0.113.7`` arrives as
    ``203.0.113.7, <real client>`` and reading the head hands every scripted
    caller a fresh, self-chosen throttle bucket. Walking from the right stops
    at the last hop a trusted proxy actually wrote.
    """
    peer = request.client.host if request.client else None
    # Read the fallback at call time so a runtime override of either setting
    # (e.g. tests monkeypatching demo_trusted_proxies) is honoured, not just
    # the construction-time inheritance in Settings.
    raw = settings.trusted_proxies or settings.demo_trusted_proxies
    trusted = _parse_trusted_proxies(raw) or _PRIVATE_PROXIES
    if not _peer_is_trusted(peer, trusted):
        return peer

    fwd = request.headers.get("x-forwarded-for") or ""
    for hop in reversed([token.strip() for token in fwd.split(",")]):
        if hop and not _peer_is_trusted(hop, trusted):
            return hop
    # Chain empty or trusted end to end — the peer is the best we have.
    return peer
