"""Shared pydantic validators used across modules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def not_past_deadline(value: datetime | None) -> datetime | None:
    """Reject deadlines that land before yesterday (UTC).

    The one-day slack is timezone-budget: the UI compares against the user's
    *local* date, so an operator in UTC-10 picking "today" can land on the
    server as "yesterday UTC". We absorb that with `now - 1d` rather than
    plumbing the user's tz through the schema (HRP-23 review fix).
    """
    if value is None:
        return value
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    if aware.date() < cutoff:
        raise ValueError("deadline cannot be in the past")
    return value
