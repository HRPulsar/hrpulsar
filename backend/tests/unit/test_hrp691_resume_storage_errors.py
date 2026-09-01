"""HRP-691: resume import must not fail silently on S3-compatible storage.

Two regressions guarded here:

- boto3 >= 1.36 injects CRC32 flexible checksums by default; providers that
  predate the extension (Ceph RGW, older MinIO) reject every PutObject with
  XAmzContentSHA256Mismatch. The client must opt out via
  ``request_checksum_calculation="when_required"``.
- ``_extract_text_from_s3`` used to swallow every storage failure into an
  empty string, surfacing as an unexplained "no files recognized" with
  nothing in the logs. It must raise with the actual reason instead.
"""

import pytest
from app.config import settings
from app.core.s3 import get_s3_client, upload_file
from app.modules.recruitment.tasks.parsing import (
    PermanentParseError,
    _extract_text_from_s3,
)


def test_s3_client_opts_out_of_flexible_checksums(monkeypatch) -> None:
    monkeypatch.setattr(settings, "s3_endpoint", "http://localhost:9000")
    client = get_s3_client()
    assert client.meta.config.request_checksum_calculation == "when_required"
    assert client.meta.config.response_checksum_validation == "when_required"


def test_extract_raises_when_storage_not_configured(monkeypatch) -> None:
    monkeypatch.setattr("app.core.s3.get_s3_client", lambda: None)

    class _Resume:
        file_id = "00000000-0000-0000-0000-000000000000"
        mime_type = "application/pdf"

    # PermanentParseError, not a bare RuntimeError: the task marks the row
    # ``failed`` once and stops, instead of burning its retry budget
    # flapping failed → processing → failed (HRP-654 review).
    with pytest.raises(PermanentParseError, match="not configured"):
        _extract_text_from_s3(_Resume(), settings)


def test_malformed_endpoint_degrades_to_storage_disabled(monkeypatch) -> None:
    """A schemeless S3_ENDPOINT raises ValueError at boto3 client
    construction — outside every caller's (BotoCoreError, ClientError)
    net. It must degrade to the "storage not configured" path instead of
    500ing the request that touched storage (HRP-654 review)."""
    monkeypatch.setattr(settings, "s3_endpoint", "minio:9000")
    assert get_s3_client() is None
    assert upload_file(b"resume-bytes", "t/resumes/x.pdf", "application/pdf") is None
