"""HRP-412: presigned URLs must be signed against the public endpoint.

On self-hosted deployments ``S3_ENDPOINT`` is the internal Docker address
(``http://minio:9000``), which the browser cannot reach — presigned links
built from it render as broken images. When ``S3_PUBLIC_ENDPOINT`` is set,
browser-facing URLs (downloads and multipart part uploads) must be signed
against it up front: SigV4 signatures are host-bound, so rewriting the host
after signing would invalidate them.
"""

from __future__ import annotations

import contextlib
from unittest.mock import patch

from app.core import s3

INTERNAL = "http://minio:9000"
PUBLIC = "https://hr.example.com"


@contextlib.contextmanager
def _s3_settings(public_endpoint: str):
    with (
        patch.object(s3.settings, "s3_endpoint", INTERNAL),
        patch.object(s3.settings, "s3_public_endpoint", public_endpoint),
        patch.object(s3.settings, "s3_access_key", "test-key"),
        patch.object(s3.settings, "s3_secret_key", "test-secret"),
    ):
        yield


def test_presigned_url_uses_public_endpoint() -> None:
    with _s3_settings(PUBLIC):
        url = s3.get_presigned_url("tenant/logo/x.png")

    assert url is not None
    assert url.startswith(f"{PUBLIC}/{s3.settings.s3_bucket}/tenant/logo/x.png?")
    assert INTERNAL not in url
    assert "X-Amz-Signature=" in url


def test_presigned_url_falls_back_to_internal_endpoint() -> None:
    with _s3_settings(""):
        url = s3.get_presigned_url("tenant/logo/x.png")

    assert url is not None
    assert url.startswith(f"{INTERNAL}/{s3.settings.s3_bucket}/tenant/logo/x.png?")


def test_presigned_url_internal_flag_bypasses_public_endpoint() -> None:
    """Server-side consumers (e.g. the transcription worker) must keep
    getting internally-reachable URLs even when a public endpoint is set."""
    with _s3_settings(PUBLIC):
        url = s3.get_presigned_url("tenant/media/x.mp4", internal=True)

    assert url is not None
    assert url.startswith(f"{INTERNAL}/{s3.settings.s3_bucket}/tenant/media/x.mp4?")


def test_part_upload_url_uses_public_endpoint() -> None:
    with _s3_settings(PUBLIC):
        url = s3.get_part_presigned_url("tenant/media/x.mp4", "upload-1", 2)

    assert url is not None
    assert url.startswith(f"{PUBLIC}/{s3.settings.s3_bucket}/tenant/media/x.mp4?")
    assert INTERNAL not in url


def test_presign_client_disabled_without_endpoint() -> None:
    with patch.object(s3.settings, "s3_endpoint", ""):
        assert s3.get_s3_presign_client() is None


def test_presign_client_keeps_sigv4() -> None:
    with _s3_settings(PUBLIC):
        client = s3.get_s3_presign_client()

    assert client is not None
    assert client.meta.config.signature_version == "s3v4"
