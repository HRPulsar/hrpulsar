"""Duration helpers for the Current Employment block (HRP-151).

The Jira spec models calendar-aware spells, not 30-day buckets:
- `start_date` is inclusive, `end_date` is exclusive
- A missing or future `end_date` means "still working" → measure against today
- Under one month → days only (`"5 days"`)
- Under one year → months and days (`"3 months 5 days"`)
- One year or more → years and months, days dropped (`"1 year 15 days"` → `"1 year"`)
"""

from __future__ import annotations

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta


def _pluralize(value: int, unit: str) -> str:
    return f"{value} {unit}" if value == 1 else f"{value} {unit}s"


def compute_duration(
    start: date, end: date | None, today: date | None = None
) -> str | None:
    """Format an employment spell length per the HRP-151 spec.

    Returns ``None`` only when the span is zero or negative — guarding
    callers from rendering `"0 days"` for rows that haven't actually
    started yet.
    """
    reference = today or date.today()
    effective_end = end if (end and end <= reference) else reference
    # end_date is exclusive: the last worked day is end_date - 1. Treat
    # `start == effective_end` as zero (the spell has not produced any
    # tenure yet) instead of "1 day", which would lie to the reader.
    if effective_end <= start:
        return None

    last_inclusive = effective_end - timedelta(days=1)
    delta = relativedelta(last_inclusive, start)
    # relativedelta counts inclusive days between two dates — bump by one
    # so a single-day spell reports `"1 day"` instead of `"0 days"`.
    days = delta.days + 1
    months = delta.months
    years = delta.years

    # Carry the remainder day into months when it lands on the next month
    # boundary (e.g. Jan 31 → Mar 1 should not read as "1 month 32 days").
    while days >= 28:
        # Adding one calendar month from `start + (years*12 + months) months`
        # tells us how long the "current" month actually is.
        anchor = start + relativedelta(years=years, months=months)
        next_anchor = anchor + relativedelta(months=1)
        month_length = (next_anchor - anchor).days
        if days < month_length:
            break
        days -= month_length
        months += 1
        if months >= 12:
            months -= 12
            years += 1

    if years >= 1:
        if months == 0:
            return _pluralize(years, "year")
        return f"{_pluralize(years, 'year')} {_pluralize(months, 'month')}"
    if months >= 1:
        if days == 0:
            return _pluralize(months, "month")
        return f"{_pluralize(months, 'month')} {_pluralize(days, 'day')}"
    return _pluralize(days, "day")
