"""P0-4: generic upload validation — size cap, MIME allowlist, image sniff.

Guards the storage service against DoS (unbounded read) and stored XSS
(SVG/HTML served inline as image/png). See app.core.upload_validation.
"""

from __future__ import annotations

import pytest
from app.core.upload_validation import validate_upload
from fastapi import HTTPException

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
