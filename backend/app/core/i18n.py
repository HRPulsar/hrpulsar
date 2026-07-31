"""Interface-locale resolution (i18n F0).

One resolution chain for everything user-facing (UI copy is resolved by
the frontend; the backend uses this for error messages and emails):

    User.language > Tenant.default_locale > Accept-Language
        > settings.default_locale

Every candidate is validated against the deployment's AVAILABLE_LOCALES —
an unsupported value falls through to the next level, so a stale DB value
(e.g. a locale later removed from the deployment) can never select a
catalog that does not exist. F3 layers ``translate()`` and the
``app/i18n/{locale}.json`` catalogs on top of this module.
"""

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import Request

from app.config import settings

_QVALUE_RE = re.compile(r"^q=(0(\.\d{0,3})?|1(\.0{0,3})?)$")

# Message catalogs (F3): backend/app/i18n/{locale}.json — errors.* now,
# email.* in F4. Kept next to the code so a deployment ships exactly the
# catalogs its build supports.
_I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"


@lru_cache(maxsize=8)
def _load_catalog(locale: str) -> dict:
    path = _I18N_DIR / f"{locale}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _lookup(catalog: dict, dotted_key: str) -> str | None:
    node: object = catalog
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def translate(key: str, locale: str, /, **params: object) -> str:
    """Catalog lookup with graceful degradation: locale → en → the key.

    Params are interpolated with ``str.format`` placeholders; a message
    with a missing/mismatched placeholder is returned un-interpolated
    rather than raising (an error path must never crash on rendering).
    """
    for candidate in (locale, "en"):
        value = _lookup(_load_catalog(candidate), key)
        if value is not None:
            if params:
                try:
                    return value.format(**params)
                except (KeyError, IndexError, ValueError):
                    return value
            return value
    return key


def format_date(value: date, locale: str) -> str:
    """Long human date for emails: "July 05, 2026" / "05. Juli 2026".

    Month names and their arrangement live in the catalog
    (``email.date.long`` + ``email.date.month_N``) so adding a language
    stays a catalog-only change. The en pattern reproduces the historic
    ``strftime("%B %d, %Y")`` byte-for-byte — the en email snapshots pin
    that exact shape.
    """
    return translate(
        "email.date.long",
        locale,
        month=translate(f"email.date.month_{value.month}", locale),
        day=f"{value.day:02d}",
        year=str(value.year),
    )


@lru_cache(maxsize=1)
def _validation_message_keys() -> dict[str, str]:
    """Reverse index: exact English message → ``errors.validation.*`` key.

    Lets the RequestValidationError handler localize custom ``ValueError``
    messages raised inside pydantic validators without touching the
    schemas — the raises keep their plain English strings (and the stock
    wire output: the handler only rewrites for non-en locales)."""
    subtree = _load_catalog("en").get("errors", {}).get("validation", {})
    reverse: dict[str, str] = {}
    for key in sorted(subtree):
        value = subtree[key]
        if isinstance(value, str):
            reverse.setdefault(value, f"errors.validation.{key}")
    return reverse


def validation_key_for_message(message: str) -> str | None:
    return _validation_message_keys().get(message)


def resolve_locale_from_request(request: Request) -> str:
    """DB-free resolution for exception handlers and middleware.

    NEXT_LOCALE cookie → Accept-Language → deployment default. The
    cookie is kept in sync with the account-level preference by the
    frontend (proxy first-visit write + AuthProvider locale-sync), so
    on product traffic it already reflects User.language /
    Tenant.default_locale without a DB round-trip.
    """
    from_cookie = normalize_locale(request.cookies.get("NEXT_LOCALE"))
    if from_cookie:
        return from_cookie
    return resolve_locale(accept_language=request.headers.get("accept-language"))


def normalize_locale(value: str | None) -> str | None:
    """Map a locale tag onto a supported locale, or None.

    Accepts full BCP 47 tags ("de-DE", "de_AT") and matches on the
    primary subtag against AVAILABLE_LOCALES.
    """
    if not value:
        return None
    primary = re.split(r"[-_]", value.strip().lower(), maxsplit=1)[0]
    if primary in settings.available_locales_list:
        return primary
    return None


def parse_accept_language(header: str | None) -> list[str]:
    """Accept-Language → language tags ordered by descending q-value.

    Wildcards are dropped. A malformed q-value drops its tag (treating
    it as rejected) rather than promoting it to top preference.
    Parameter names are case-insensitive (RFC 9110); ties keep header
    order.
    """
    if not header:
        return []
    weighted: list[tuple[float, str]] = []
    for part in header.split(","):
        segments = [s.strip() for s in part.strip().split(";")]
        tag = segments[0]
        if not tag or tag == "*":
            continue
        quality = 1.0
        for param in segments[1:]:
            lowered = param.lower()
            if lowered.startswith("q="):
                quality = float(lowered[2:]) if _QVALUE_RE.match(lowered) else 0.0
                break
        if quality > 0:
            weighted.append((quality, tag))
    weighted.sort(key=lambda item: -item[0])
    return [tag for _, tag in weighted]


def resolve_locale(
    *,
    user_language: str | None = None,
    tenant_default: str | None = None,
    accept_language: str | None = None,
) -> str:
    """Resolve the effective interface locale for a request/recipient."""
    for candidate in (user_language, tenant_default):
        normalized = normalize_locale(candidate)
        if normalized:
            return normalized
    for tag in parse_accept_language(accept_language):
        normalized = normalize_locale(tag)
        if normalized:
            return normalized
    # Guaranteed to be in AVAILABLE_LOCALES by the config validator.
    return settings.default_locale
