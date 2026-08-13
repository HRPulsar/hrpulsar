"""HRP-439: the installation's currency for HR money fields.

Salary and compensation defaults used to be currency literals baked into
models and schemas — ``RUB`` in the grade/specialization chain, ``USD`` in
compensations. That is wrong on every site at once: the flagship quotes
USD, the German white-label EUR, the Russian one RUB, and no single
literal can be right for all three.

The money layer is already parameterised per installation for billing
(``BILLING_CURRENCY`` in core settings, resolved by the enterprise
billing profile), so the HR domain reuses that value rather than growing
a second knob for operators to keep in sync. If the two ever need to
diverge, this module is the one place that has to change.

Read through the function, never captured at import time: settings are a
module-level singleton, and a captured value would freeze whatever the
first import saw.
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)

# Community default. Also the fallback for a malformed BILLING_CURRENCY —
# an unusable code must not reach the DB, where the column is NOT NULL and
# the schemas enforce exactly three characters.
FALLBACK_CURRENCY = "USD"


def _configured_currency() -> str:
    """The site's currency, preferring the effective billing profile.

    ``BILLING_CURRENCY`` is only the env-level input: on a white-label
    site the authority is the host-mounted ``billing_profile.yaml``
    (``BILLING_PROFILE_PATH``), which may say EUR while the env still
    carries the stock USD. Reading env alone would quietly write salaries
    in the wrong currency on exactly the sites this feature exists for.

    Sanctioned mechanism 3 (point-wise lazy soft-import, see CLAUDE.md):
    the import lives inside the function and community builds — which
    have no ``ee`` package at all — fall back to the env value.

    A profile that is configured but unreadable is deliberately *not*
    fatal here. Billing already refuses to serve on such a site, which is
    the loud signal for the operator; taking the HR write paths down as
    well would turn a pricing misconfiguration into an outage, so this
    logs and falls back to env.
    """
    try:
        from ee.billing_profile import get_effective_currency
    except ImportError:
        return settings.billing_currency

    try:
        return get_effective_currency()
    except Exception:  # noqa: BLE001 — see the docstring
        logger.warning(
            "billing profile unreadable; HR currency falls back to "
            "BILLING_CURRENCY=%s",
            settings.billing_currency,
            exc_info=True,
        )
        return settings.billing_currency


def installation_currency() -> str:
    """ISO 4217 code for this installation's HR money fields."""
    raw = (_configured_currency() or "").strip().upper()
    if len(raw) != 3 or not raw.isalpha():
        return FALLBACK_CURRENCY
    return raw
