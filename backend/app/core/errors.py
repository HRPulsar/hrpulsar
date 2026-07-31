"""AppError — code-based user-facing errors (i18n F3).

Replaces bare ``HTTPException(status, "English string")`` on user-facing
paths. The exception carries a stable error *code*; the exception
handler in ``app/main.py`` resolves the request locale and renders the
message from the ``errors.<code>`` catalog entry
(``backend/app/i18n/{locale}.json``).

Response shape stays backward-compatible with the frontend API client
and the existing tests::

    {"detail": "<localized message>", "code": "<code>"}

``detail`` remains a plain string (the client's ``formatApiError`` and
hundreds of test assertions read it as such); ``code`` is additive for
programmatic handling.

Usage::

    raise AppError("employee_not_found", status.HTTP_404_NOT_FOUND)
    raise AppError("file_too_large", 400, max_mb=settings.max_upload_mb)

Params are interpolated into the catalog message with ``str.format``
placeholders (``{max_mb}``).

Structured detail (pre-F3 sites the frontend parses as an object —
``err.detail.code`` / ``err.detail.error_code`` / extra payload fields):
passing ``detail_extra`` (a dict, possibly empty) switches ``detail`` to
the legacy object shape while keeping the top-level ``code`` additive::

    raise AppError(
        "candidate_archived", 409,
        detail_extra={"existing_candidate_id": str(candidate.id)},
    )
    # {"detail": {"code": "candidate_archived", "message": "...",
    #             "existing_candidate_id": "..."}, "code": "candidate_archived"}

``detail_code_key`` renames the code field inside detail (legacy sites
use ``"error_code"``); ``detail_code`` overrides the wire code value when
one wire code fans out to several catalog messages (``insufficient_data``).

AppError subclasses ``HTTPException`` on purpose: ~530 existing tests do
``pytest.raises(HTTPException)`` around direct service calls, and a few
production paths catch ``except HTTPException`` to aggregate per-row
failures. ``self.detail`` is pre-rendered from the **en** catalog, so any
context without the locale-aware handler (direct service-call tests,
Celery tasks, FastAPI's stock handler) degrades to the exact pre-F3
English behavior. The locale-aware handler still wins for API responses:
Starlette resolves handlers along the exception's MRO, and the AppError
registration is more specific than HTTPException's.
"""

from typing import Any

from fastapi import HTTPException


class AppError(HTTPException):
    def __init__(
        self,
        code: str,
        status_code: int = 400,
        headers: dict[str, str] | None = None,
        detail_extra: dict[str, Any] | None = None,
        detail_code_key: str = "code",
        detail_code: str | None = None,
        **params: Any,
    ) -> None:
        self.code = code
        self.detail_extra = detail_extra
        self.detail_code_key = detail_code_key
        self.detail_code = detail_code
        self.params = params
        super().__init__(
            status_code=status_code,
            detail=self.localized_detail("en"),
            headers=headers,
        )

    def localized_detail(self, locale: str) -> str | dict[str, Any]:
        """Message (or legacy object-shaped detail) in the given locale."""
        # Lazy import: app.core.i18n pulls config/database/auth at module
        # load; errors.py must stay importable from anywhere.
        from app.core.i18n import translate

        message = translate(f"errors.{self.code}", locale, **self.params)
        if self.detail_extra is None:
            return message
        return {
            self.detail_code_key: self.detail_code or self.code,
            "message": message,
            **self.detail_extra,
        }


def exception_summary(exc: BaseException, limit: int = 200) -> str:
    """Compact, reflection-safe rendering of an upstream exception.

    Provider SDK errors stringify whole HTTP response bodies; those must
    not be echoed verbatim into client-facing error detail (the body of
    an internal host reached through a misconfigured endpoint would leak).
    First line only, capped.
    """
    text = str(exc)
    first_line = text.splitlines()[0].strip() if text.strip() else type(exc).__name__
    if len(first_line) > limit:
        first_line = first_line[: limit - 3] + "..."
    return first_line
