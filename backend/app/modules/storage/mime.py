"""HRP-53: magic-byte MIME detection so a wrong client-supplied header
doesn't poison the S3 Content-Type."""

from __future__ import annotations


def detect_image_mime(data: bytes) -> str | None:
    """Return the canonical image MIME for known signatures, else None."""
    if not data:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    head = data[:512].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        return "image/svg+xml"
    return None
