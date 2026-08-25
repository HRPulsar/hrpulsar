"""HRP-645 — trusted-proxy resolution of the caller's source IP.

Two regressions this pins, both observed on the GF fleet site:

* ``TRUSTED_PROXIES`` unset made every request key on Caddy's container
  address, so ``/api/demo/start`` throttled the whole internet into one
  5/hour bucket and the demo stopped starting for everybody;
* reading the first ``X-Forwarded-For`` hop let a caller pick its own
  bucket, because Caddy appends to the header instead of replacing it.
"""

from __future__ import annotations

import pytest
from app.config import settings
from app.core.client_ip import client_ip
from starlette.requests import Request


@pytest.fixture(autouse=True)
def _no_configured_proxies(monkeypatch):
    """Default posture: nothing configured in the environment."""
    monkeypatch.setattr(settings, "trusted_proxies", "")
    monkeypatch.setattr(settings, "demo_trusted_proxies", "")


def _request(peer: str | None, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request(
        {
            "type": "http",
            "headers": headers,
            "client": (peer, 51234) if peer else None,
        }
    )


def test_docker_bridge_peer_is_trusted_without_configuration():
    """The incident itself: Caddy reaches the backend from the compose
    bridge network, and its address changes whenever that network is
    recreated. Nothing may need pinning in the host ``.env`` for the
    real caller to come through."""
    assert client_ip(_request("172.20.0.8", "203.0.113.7")) == "203.0.113.7"


@pytest.mark.parametrize("peer", ["10.1.2.3", "172.20.0.8", "192.168.5.4", "127.0.0.1"])
def test_every_private_range_is_trusted_by_default(peer):
    assert client_ip(_request(peer, "203.0.113.7")) == "203.0.113.7"


def test_public_peer_never_gets_to_forge_its_ip():
    """A caller reaching the app without passing our proxy is not one —
    its header is ignored and it keeps its own bucket."""
    assert client_ip(_request("198.51.100.9", "203.0.113.7")) == "198.51.100.9"


def test_client_supplied_prefix_is_discarded():
    """Caddy *appends*, so a caller sending ``X-Forwarded-For:
    203.0.113.7`` has the real address land to the right of its own
    value. Reading the head would hand every scripted caller a fresh
    throttle bucket per request."""
    forged = "203.0.113.7, 198.51.100.9"
    assert client_ip(_request("172.20.0.8", forged)) == "198.51.100.9"


def test_explicit_setting_overrides_the_private_default(monkeypatch):
    """An operator narrowing the list must be able to narrow it — the
    default applies only when nothing is configured."""
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/8")
    assert client_ip(_request("172.20.0.8", "203.0.113.7")) == "172.20.0.8"
    assert client_ip(_request("10.0.0.4", "203.0.113.7")) == "203.0.113.7"


def test_blank_hops_are_skipped_not_returned():
    """A leading comma used to make the helper return ``None``, which
    disables the throttle outright."""
    assert client_ip(_request("172.20.0.8", ", 203.0.113.7")) == "203.0.113.7"
    assert client_ip(_request("172.20.0.8", " , ")) == "172.20.0.8"


def test_chain_of_only_trusted_hops_falls_back_to_peer():
    assert client_ip(_request("172.20.0.8", "10.0.0.4, 192.168.1.1")) == "172.20.0.8"


def test_missing_client_yields_none():
    """ASGI servers may omit ``client``; the throttle then skips rather
    than keying everyone on a literal ``\"None\"``."""
    assert client_ip(_request(None, "203.0.113.7")) is None
