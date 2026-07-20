"""PII redaction for free-form text (resumes, transcripts).

Redacts a multi-locale set of personally identifiable identifiers before
the text is persisted to the structured store or sent to an external
LLM. Raw text is still kept on encrypted S3 — see ``RECRUITING_MODULE.md``
§9.1.

Coverage (conservative regex patterns, order matters):

* Universal: credit card numbers, IBAN account numbers.
* US: Social Security Number (SSN).
* EU: UK National Insurance Number (NIN), Spanish DNI, Italian Codice
  Fiscale.
* RU: SNILS, INN (legal entity + individual), internal passport.

The regexes are intentionally conservative: false negatives (a number
that slips through) are preferred over false positives (an unrelated
number that happens to match by digit count getting masked). Adjust the
per-tenant policy on top of this baseline if stricter redaction is
required.
"""

from __future__ import annotations

import re
from typing import Literal

# ---------------------------------------------------------------------------
# Patterns — ordered from most-specific to most-broad. Earlier matches are
# substituted first, so an IBAN that contains a 12-digit run is not
# subsequently mis-tagged as a Russian INN.
# ---------------------------------------------------------------------------

# 16-digit card number written as four groups of four with optional spaces
# or dashes. Conservative: rejects 13/15/19-digit Amex/Diners variants.
_CREDIT_CARD = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")

# ISO 13616 IBAN: 2-letter country, 2 check digits, 11-30 alphanumerics.
# Detects the compact (no-space) form commonly stored in databases.
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")

# Italian Codice Fiscale — 16 chars, fixed letter/digit positions.
_IT_CODICE_FISCALE = re.compile(
    r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b"
)

# UK National Insurance Number — 2 letters + 6 digits + 1 trailing letter,
# optionally split into groups of two with spaces (e.g. "AB 12 34 56 C").
_UK_NIN = re.compile(r"\b[A-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-Z]\b")

# Spanish DNI / NIE — 8 digits followed by a single capital letter.
_ES_DNI = re.compile(r"\b\d{8}[A-Z]\b")

# US Social Security Number — XXX-XX-XXXX.
_US_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Russian SNILS insurance number — "123-456-789 12" or "123-456-789-12".
_RU_SNILS = re.compile(r"\b\d{3}-\d{3}-\d{3}[\s-]\d{2}\b")

# Russian INN — 10 digits (legal entity) or 12 digits (individual). This
# regex is the most aggressive: any bare 10/12-digit run is claimed here,
# so it must run AFTER more-specific patterns above.
_RU_INN = re.compile(r"\b\d{12}\b|\b\d{10}\b")

# Russian internal passport — 4-digit series, space, 6-digit number. The
# 10-digit INN above already swallows the space-less form, which is the
# documented trade-off (see test_redact_pii_passport_no_space_is_treated_as_inn).
_RU_PASSPORT = re.compile(r"\b\d{4}\s\d{6}\b")


_REPLACEMENTS_TAG: list[tuple[re.Pattern[str], str]] = [
    (_CREDIT_CARD, "[REDACTED:credit_card]"),
    (_IBAN, "[REDACTED:iban]"),
    (_IT_CODICE_FISCALE, "[REDACTED:codice_fiscale]"),
    (_UK_NIN, "[REDACTED:nin]"),
    (_ES_DNI, "[REDACTED:dni]"),
    (_US_SSN, "[REDACTED:ssn]"),
    (_RU_SNILS, "[REDACTED:snils]"),
    (_RU_INN, "[REDACTED:inn]"),
    (_RU_PASSPORT, "[REDACTED:passport]"),
]

_MASK = "***"


def redact_pii(
    text: str | None,
    *,
    mode: Literal["mask", "tag"] = "tag",
) -> str:
    """Return ``text`` with known PII sequences redacted.

    ``mode='tag'`` replaces matches with ``[REDACTED:<kind>]`` markers so
    a human reading the transcript can see *what* was scrubbed.
    ``mode='mask'`` uses a uniform ``***``.
    """

    if not text:
        return ""

    out = text
    for pattern, replacement in _REPLACEMENTS_TAG:
        out = pattern.sub(replacement if mode == "tag" else _MASK, out)
    return out


__all__ = ["redact_pii"]
