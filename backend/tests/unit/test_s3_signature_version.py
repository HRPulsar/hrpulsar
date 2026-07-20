"""HRP-14: S3 presigned URLs must use SigV4.

AWS regions created after 2014 and MinIO reject ``GET`` requests with SigV2
``Signature`` query strings ("SigV2 authorization is not supported. Please use
SigV4 instead."). The boto3 client therefore needs an explicit
``signature_version="s3v4"`` override — the global default is still SigV2 on
older botocore builds.
"""

from __future__ import annotations

from unittest.mock import patch

from app.core import s3


def test_s3_client_uses_sigv4() -> None:
    with patch.object(s3.settings, "s3_endpoint", "http://minio.local:9000"):
        client = s3.get_s3_client()

    assert client is not None
    assert client.meta.config.signature_version == "s3v4"


def test_s3_client_disabled_without_endpoint() -> None:
    with patch.object(s3.settings, "s3_endpoint", ""):
        assert s3.get_s3_client() is None
