"""HRP-445 — startup gate for internal-only S3 endpoints.

The ``_s3_internal_requires_public_endpoint`` model validator must refuse
to instantiate Settings when ``s3_endpoint`` is a bare container-network
hostname (no dots, e.g. ``minio:9000``) and ``s3_public_endpoint`` is
empty: presigned URLs are host-bound (SigV4), so they would point at a
host browsers cannot reach — the broken-logo failure of the 2026-07-20
self-hosted smoke.
"""

from __future__ import annotations

import pytest
from app.config import Settings


def _settings(**overrides):
    base = {
        "s3_endpoint": "",
        "s3_public_endpoint": "",
        # Explicit: an ambient FRONTEND_URL would otherwise be adopted as
        # the public endpoint (HRP-496) and change what these cases assert.
        "frontend_url": "",
    }
    base.update(overrides)
    return Settings(**base)


def test_internal_endpoint_without_public_is_rejected():
    with pytest.raises(ValueError, match="S3_PUBLIC_ENDPOINT"):
        _settings(s3_endpoint="http://minio:9000")


def test_internal_endpoint_falls_back_to_frontend_url():
    """HRP-496: the stock self-hosted compose pins S3_ENDPOINT to the
    bundled MinIO; hard-failing there crash-looped the whole stack. The
    instance origin the operator already declared is what the bundled
    Caddy proxies /<S3_BUCKET>/* from — adopt it instead of refusing."""
    s = _settings(
        s3_endpoint="http://minio:9000",
        frontend_url="https://hr.example.com/",
    )
    assert s.s3_public_endpoint == "https://hr.example.com"


def test_explicit_public_endpoint_wins_over_frontend_url():
    s = _settings(
        s3_endpoint="http://minio:9000",
        s3_public_endpoint="https://files.example.com",
        frontend_url="https://hr.example.com",
    )
    assert s.s3_public_endpoint == "https://files.example.com"


def test_non_url_frontend_url_still_rejected():
    """A relative/garbage FRONTEND_URL is not a signable origin."""
    with pytest.raises(ValueError, match="S3_PUBLIC_ENDPOINT"):
        _settings(s3_endpoint="http://minio:9000", frontend_url="hr.example.com")


def test_internal_endpoint_with_public_is_accepted():
    s = _settings(
        s3_endpoint="http://minio:9000",
        s3_public_endpoint="https://hr.example.com",
    )
    assert s.s3_public_endpoint == "https://hr.example.com"


def test_public_endpoint_alone_is_accepted():
    """A dotted hostname (R2, Yandex Object Storage, any FQDN) is treated
    as browser-reachable — no public override required."""
    s = _settings(s3_endpoint="https://abc123.r2.cloudflarestorage.com")
    assert s.s3_public_endpoint == ""


def test_localhost_endpoint_is_accepted():
    """Single-machine dev: the browser and backend share localhost."""
    s = _settings(s3_endpoint="http://localhost:9000")
    assert s.s3_endpoint == "http://localhost:9000"


def test_loopback_ip_endpoint_is_accepted():
    s = _settings(s3_endpoint="http://127.0.0.1:9000")
    assert s.s3_endpoint == "http://127.0.0.1:9000"


def test_ipv6_loopback_endpoint_is_accepted():
    s = _settings(s3_endpoint="http://[::1]:9000")
    assert s.s3_endpoint == "http://[::1]:9000"


def test_schemeless_internal_endpoint_is_rejected():
    """ "minio:9000" without a scheme must not slip past the validator
    (urlsplit would otherwise parse "minio" as the scheme)."""
    with pytest.raises(ValueError, match="S3_PUBLIC_ENDPOINT"):
        _settings(s3_endpoint="minio:9000")


def test_storage_disabled_is_accepted():
    s = _settings(s3_endpoint="")
    assert s.s3_endpoint == ""
