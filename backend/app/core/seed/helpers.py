"""Tiny shared helpers for the seed steps."""

import uuid
from datetime import UTC, date, datetime, timedelta

now = datetime.now(UTC)


def uid() -> uuid.UUID:
    return uuid.uuid4()


def past_date(days_ago: int) -> date:
    return (datetime.now(UTC) - timedelta(days=days_ago)).date()


def past_dt(days_ago: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days_ago)
