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
    }
    base.update(overrides)
    return Settings(**base)


def test_internal_endpoint_without_public_is_rejected():
    with pytest.raises(ValueError, match="S3_PUBLIC_ENDPOINT"):
        _settings(s3_endpoint="http://minio:9000")


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
