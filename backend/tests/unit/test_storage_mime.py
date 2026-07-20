"""HRP-53: magic-byte MIME detection for image uploads.

Browsers occasionally send ``application/octet-stream`` for legitimate images
(macOS Preview drag/drop is the recurring offender). The sniff lets the
company logo upload keep the right ``Content-Type`` in S3 so the eventual
``<img src>`` actually renders.
"""

from __future__ import annotations

from app.modules.storage.mime import detect_image_mime

# Real magic bytes — taken from the wire format of each container.
PNG_SIG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_SIG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP_SIG = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8 " + b"\x00" * 16
SVG_TEXT = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
)
SVG_BARE = b"<svg xmlns='http://www.w3.org/2000/svg' />"


class TestDetectImageMime:
    def test_png(self) -> None:
        assert detect_image_mime(PNG_SIG) == "image/png"

    def test_jpeg(self) -> None:
        assert detect_image_mime(JPEG_SIG) == "image/jpeg"

    def test_webp(self) -> None:
        assert detect_image_mime(WEBP_SIG) == "image/webp"

    def test_svg_with_xml_preamble(self) -> None:
        assert detect_image_mime(SVG_TEXT) == "image/svg+xml"

    def test_svg_without_xml_preamble(self) -> None:
        assert detect_image_mime(SVG_BARE) == "image/svg+xml"

    def test_svg_with_leading_whitespace(self) -> None:
        # `xml.sax`-style files often ship with a BOM/whitespace
        assert detect_image_mime(b"\n  " + SVG_BARE) == "image/svg+xml"

    def test_empty(self) -> None:
        assert detect_image_mime(b"") is None

    def test_unknown_binary(self) -> None:
        assert detect_image_mime(b"PK\x03\x04zip-archive") is None

    def test_short_input_does_not_crash(self) -> None:
        assert detect_image_mime(b"\xff") is None
        assert detect_image_mime(b"\x89PNG") is None
