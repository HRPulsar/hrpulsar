"""P0-4: generic upload validation — size cap, MIME allowlist, image sniff.

Guards the storage service against DoS (unbounded read) and stored XSS
(SVG/HTML served inline as image/png). See app.core.upload_validation.
"""

from __future__ import annotations

import uuid

import pytest
from app.core.upload_validation import validate_upload
from fastapi import HTTPException
from starlette.requests import Request

PNG = b"\x89PNG\r\n\x1a\n" + b"rest"
JPEG = b"\xff\xd8\xff\xe0" + b"rest"
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
PDF = b"%PDF-1.7\n..."

MB = 1024 * 1024


class TestSizeCap:
    def test_oversize_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc:
            validate_upload(
                data=b"x" * (2 * MB), claimed_mime="image/png", max_bytes=MB
            )
        assert exc.value.status_code == 413

    def test_empty_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc:
            validate_upload(data=b"", claimed_mime="image/png", max_bytes=MB)
        assert exc.value.status_code == 400


class TestMimeAllowlist:
    def test_svg_rejected(self) -> None:
        # Even when honestly declared, SVG is inline-executable → blocked.
        with pytest.raises(HTTPException) as exc:
            validate_upload(data=SVG, claimed_mime="image/svg+xml", max_bytes=MB)
        assert exc.value.status_code == 415

    def test_html_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc:
            validate_upload(data=b"<html>x", claimed_mime="text/html", max_bytes=MB)
        assert exc.value.status_code == 415

    def test_pdf_allowed_in_general(self) -> None:
        mime, ext = validate_upload(data=PDF, claimed_mime="application/pdf", max_bytes=MB)
        assert (mime, ext) == ("application/pdf", "pdf")

    def test_pdf_rejected_when_images_only(self) -> None:
        with pytest.raises(HTTPException) as exc:
            validate_upload(
                data=PDF, claimed_mime="application/pdf", max_bytes=MB, images_only=True
            )
        assert exc.value.status_code == 415


class TestImageSniff:
    def test_svg_smuggled_as_png_rejected(self) -> None:
        # The core attack: SVG bytes with a lying image/png Content-Type.
        with pytest.raises(HTTPException) as exc:
            validate_upload(data=SVG, claimed_mime="image/png", max_bytes=MB)
        assert exc.value.status_code == 400

    def test_real_png_accepted(self) -> None:
        mime, ext = validate_upload(data=PNG, claimed_mime="image/png", max_bytes=MB)
        assert (mime, ext) == ("image/png", "png")

    def test_jpeg_claimed_png_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc:
            validate_upload(data=JPEG, claimed_mime="image/png", max_bytes=MB)
        assert exc.value.status_code == 400

    def test_content_type_with_charset_normalised(self) -> None:
        mime, ext = validate_upload(
            data=PNG, claimed_mime="image/png; charset=binary", max_bytes=MB
        )
        assert mime == "image/png"


class TestEntityTypeAndEarlySizeCheck:
    """Review M13/M14 — both guards run in ``storage.service.upload`` before
    any I/O: ``entity_type`` goes straight into the S3 key, and the body used
    to be read in full before the size cap was consulted."""

    class _Tripwire:
        """An UploadFile stand-in whose bytes must never be read."""

        size = 50 * MB
        content_type = "image/png"
        filename = "big.png"

        async def read(self) -> bytes:  # pragma: no cover - must not run
            raise AssertionError("upload must be rejected before reading the body")

    @pytest.mark.parametrize(
        "entity_type",
        ["../../other-tenant", "a/b", "avatar/../x", "Avatar", "1avatar", "", "a" * 33],
    )
    async def test_entity_type_outside_the_shape_is_rejected(self, entity_type) -> None:
        from app.modules.storage import service

        with pytest.raises(HTTPException) as exc:
            await service.upload(
                None, uuid.uuid4(), uuid.uuid4(), self._Tripwire(), entity_type
            )
        assert exc.value.status_code == 400
        assert exc.value.code == "upload_invalid_entity_type"

    @pytest.mark.parametrize("entity_type", ["avatar", "logo", "vacancy_attachment"])
    async def test_known_entity_types_pass_the_shape_check(self, entity_type) -> None:
        """They get past the name check and fall to the size check below."""
        from app.modules.storage import service

        with pytest.raises(HTTPException) as exc:
            await service.upload(
                None, uuid.uuid4(), uuid.uuid4(), self._Tripwire(), entity_type
            )
        assert exc.value.status_code == 413

    async def test_oversize_is_rejected_without_reading_the_body(self) -> None:
        from app.modules.storage import service

        with pytest.raises(HTTPException) as exc:
            await service.upload(None, uuid.uuid4(), uuid.uuid4(), self._Tripwire())
        assert exc.value.status_code == 413


class TestDeclaredSizeGuard:
    def test_oversize_content_length_rejected(self) -> None:
        from app.config import settings
        from app.core.upload_validation import assert_declared_size_within_limit

        too_big = str(settings.max_upload_mb * MB * 4)
        with pytest.raises(HTTPException) as exc:
            assert_declared_size_within_limit(
                Request(
                    {
                        "type": "http",
                        "headers": [(b"content-length", too_big.encode())],
                    }
                )
            )
        assert exc.value.status_code == 413

    def test_missing_or_small_content_length_passes(self) -> None:
        from app.core.upload_validation import assert_declared_size_within_limit

        assert_declared_size_within_limit(Request({"type": "http", "headers": []}))
        assert_declared_size_within_limit(
            Request({"type": "http", "headers": [(b"content-length", b"1024")]})
        )
