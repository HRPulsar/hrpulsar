"""Shared upload validation for the generic storage service.

The storage service (``POST /files/upload``, ``POST /auth/avatar``, PDP/exam
attachments, company logo) accepts arbitrary files and previously trusted the
client-supplied ``Content-Type`` and filename extension verbatim. That is a
stored-XSS + DoS foot-gun:

* an unbounded ``await file.read()`` lets a client OOM the worker;
* an SVG/HTML payload announced as ``image/png`` is served back inline from a
  presigned URL and executes in the victim's browser.

Defence, in one place:

* a hard size cap;
* a MIME allowlist that excludes active/inline-executable content
  (``image/svg+xml``, ``text/html``, ``application/xml``, JS);
* magic-byte sniffing for **image** types — the only category served inline —
  so bytes claiming ``image/png`` really are a PNG and cannot smuggle an SVG.

Document types (pdf, office) are download/inert and are gated by the allowlist
and size cap but not byte-sniffed (their signatures are unreliable across
producers). Domain-specific validators (resume, interview attachment) keep
their own stricter allowlists.
"""

from __future__ import annotations

from fastapi import status

from app.core.errors import AppError

# Raster images — served inline, therefore the security-critical category.
_IMAGE_MIME_TO_EXT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}

# Inert document types — download/preview only, never inline-executable.
_DOC_MIME_TO_EXT: dict[str, str] = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.ms-excel": "xls",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/plain": "txt",
    "text/csv": "csv",
}

_ALLOWED_MIME_TO_EXT: dict[str, str] = {**_IMAGE_MIME_TO_EXT, **_DOC_MIME_TO_EXT}

# Magic-byte prefixes for image types. WEBP is ``RIFF....WEBP``; the RIFF
# prefix plus the allowlisted MIME is enough to reject SVG/HTML smuggling.
_IMAGE_MAGIC: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}


def _sniff_image(payload: bytes, mime: str) -> bool:
    return any(payload[: len(p)] == p for p in _IMAGE_MAGIC[mime])


def validate_upload(
    *,
    data: bytes,
    claimed_mime: str | None,
    max_bytes: int,
    images_only: bool = False,
) -> tuple[str, str]:
    """Validate a fully-read upload and return ``(safe_mime, extension)``.

    Raises ``HTTPException`` (413/415/400) on any violation. The returned
    MIME/extension come from the allowlist + sniffed bytes, so callers must
    persist *these* values, not the client-supplied ones. ``images_only``
    restricts to raster images (avatars, logos) and forces the byte sniff.
    """
    if len(data) > max_bytes:
        # 413 Content Too Large. Literal avoids the starlette constant rename
        # churn (REQUEST_ENTITY_TOO_LARGE → CONTENT_TOO_LARGE).
        raise AppError("upload_file_too_large", 413, max_mb=max_bytes // (1024 * 1024))
    if not data:
        raise AppError("upload_empty_file", status.HTTP_400_BAD_REQUEST)

    mime = (claimed_mime or "").split(";", 1)[0].strip().lower()
    allowed = _IMAGE_MIME_TO_EXT if images_only else _ALLOWED_MIME_TO_EXT
    if mime not in allowed:
        raise AppError(
            "unsupported_file_type",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            mime=mime or "unknown",
        )
    # Sniff only images — the inline-served category. A mismatch here is how an
    # SVG/HTML payload would try to pass as image/png.
    if mime in _IMAGE_MAGIC and not _sniff_image(data, mime):
        raise AppError("file_content_type_mismatch", status.HTTP_400_BAD_REQUEST)
    return mime, allowed[mime]
