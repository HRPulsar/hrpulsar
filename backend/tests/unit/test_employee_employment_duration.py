"""Unit tests for `compute_duration` (HRP-151).

Locks down the spec branches: days (<1 month), months+days (<1 year),
and years+months (≥1 year, days dropped). The reference `today` is
pinned per case so the "open-ended" path is deterministic.
"""

from datetime import date

import pytest
from app.modules.employee.duration import compute_duration


@pytest.mark.parametrize(
    "start, end, today, expected",
    [
        # Days bucket (< 1 month)
        (date(2024, 3, 1), date(2024, 3, 6), date(2024, 3, 10), "5 days"),
        # Months + days bucket
        (date(2024, 1, 1), date(2024, 2, 3), date(2024, 4, 1), "1 month 2 days"),
        (date(2024, 1, 1), date(2024, 4, 6), date(2024, 5, 1), "3 months 5 days"),
        # 11 months — under a year, still months+days
        (date(2024, 1, 15), date(2024, 12, 15), date(2025, 1, 1), "11 months"),
        # Exactly one year — days dropped, months zero → "1 year"
        (date(2024, 1, 15), date(2025, 1, 15), date(2025, 1, 16), "1 year"),
        # 1 year 15 days → "1 year" (Jira example)
        (date(2024, 1, 1), date(2025, 1, 17), date(2025, 1, 18), "1 year"),
        # 3 years 6 months — years + months, no days
        (date(2021, 1, 1), date(2024, 7, 1), date(2024, 8, 1), "3 years 6 months"),
    ],
)
def test_compute_duration_buckets(start, end, today, expected):
    assert compute_duration(start, end, today=today) == expected


def test_open_ended_uses_today():
    # end_date None → measure against `today`
    assert (
        compute_duration(date(2024, 1, 1), None, today=date(2024, 3, 15))
        == "2 months 14 days"
    )


def test_future_end_clamps_to_today():
    # end in the future → measure to today, not to end
    assert (
        compute_duration(date(2024, 1, 1), date(2026, 1, 1), today=date(2024, 6, 1))
        == "5 months"
    )


def test_same_day_returns_none():
    # No tenure accrued yet → don't render "0 days"
    assert compute_duration(date(2024, 1, 1), None, today=date(2024, 1, 1)) is None


def test_future_start_returns_none():
    assert compute_duration(date(2025, 1, 1), None, today=date(2024, 1, 1)) is None


def test_singular_units():
    assert (
        compute_duration(date(2024, 1, 1), date(2024, 1, 2), today=date(2024, 5, 1))
        == "1 day"
    )
