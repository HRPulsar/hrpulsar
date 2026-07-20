"""Shared infrastructure for the recruitment sub-routers."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address


def resolve_page_params(
    skip: int,
    limit: int,
    page: int | None,
    page_size: int | None,
) -> tuple[int, int]:
    """Resolve the two pagination dialects into (skip, limit).

    The frontend list pages send ``page``/``page_size`` while the original
    API contract (and scripted clients) speak ``skip``/``limit``. When both
    are given, ``page``/``page_size`` win (HRP-363).
    """
    if page_size is not None:
        limit = page_size
    if page is not None:
        skip = (page - 1) * limit
    return skip, limit


# Per-IP rate limiter for public token-based endpoints (R4d security audit).
# Magic-link consent, invited-evaluator canvas, and shared-report views all
# accept opaque 256-bit tokens — high entropy by themselves, but without a
# rate limit an attacker could grind through tokens or replay a stale link
# at high QPS. 60/minute is generous for a real recruiter clicking
# through their inbox, tight for a botnet.
# key_style="endpoint" is load-bearing: slowapi's default ("url") buckets by
# the FULL request path, so every distinct {token} value would get its own
# fresh bucket and token grinding would never be throttled (review [26]).
recruitment_public_limiter = Limiter(key_func=get_remote_address, key_style="endpoint")
