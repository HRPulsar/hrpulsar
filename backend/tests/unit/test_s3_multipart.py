"""Unit tests for app.core.s3 multipart helpers."""

from unittest.mock import MagicMock

from app.core import s3 as s3_module


def _patch_client(monkeypatch, fake_client):
    monkeypatch.setattr(s3_module, "get_s3_client", lambda: fake_client)
    # Browser-facing part-upload URLs are signed by the presign client
    # (HRP-412); in these tests both resolve to the same fake.
    monkeypatch.setattr(s3_module, "get_s3_presign_client", lambda: fake_client)


def test_init_multipart_upload_returns_upload_id(monkeypatch):
    fake = MagicMock()
    fake.create_multipart_upload.return_value = {"UploadId": "u-123"}
    _patch_client(monkeypatch, fake)

    upload_id = s3_module.init_multipart_upload(
        "tenants/x/interviews/file.mp4", "video/mp4"
    )

    assert upload_id == "u-123"
    fake.create_multipart_upload.assert_called_once()


def test_init_multipart_upload_returns_none_when_no_client(monkeypatch):
    _patch_client(monkeypatch, None)
    assert s3_module.init_multipart_upload("path", "video/mp4") is None


def test_get_part_presigned_url_uses_upload_part_op(monkeypatch):
    fake = MagicMock()
    fake.generate_presigned_url.return_value = "https://signed/part1"
    _patch_client(monkeypatch, fake)

    url = s3_module.get_part_presigned_url("path", "u-123", part_number=1)

    assert url == "https://signed/part1"
    args, kwargs = fake.generate_presigned_url.call_args
    assert args[0] == "upload_part"
    assert kwargs["Params"]["UploadId"] == "u-123"
    assert kwargs["Params"]["PartNumber"] == 1


def test_complete_multipart_upload_sorts_parts(monkeypatch):
    fake = MagicMock()
    _patch_client(monkeypatch, fake)

    parts_unsorted = [
        {"PartNumber": 2, "ETag": "etag-2"},
        {"PartNumber": 1, "ETag": "etag-1"},
    ]
    s3_module.complete_multipart_upload("path", "u-123", parts_unsorted)

    args, kwargs = fake.complete_multipart_upload.call_args
    sent = kwargs["MultipartUpload"]["Parts"]
    assert [p["PartNumber"] for p in sent] == [1, 2]


def test_abort_multipart_upload_returns_true_on_success(monkeypatch):
    fake = MagicMock()
    _patch_client(monkeypatch, fake)
    assert s3_module.abort_multipart_upload("path", "u-123") is True
    fake.abort_multipart_upload.assert_called_once()


def test_max_object_bytes_is_500_mb():
    assert s3_module.MAX_OBJECT_BYTES == 500 * 1024 * 1024


def test_default_part_size_is_8_mb():
    assert s3_module.DEFAULT_PART_SIZE == 8 * 1024 * 1024
