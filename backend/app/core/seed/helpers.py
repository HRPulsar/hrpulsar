"""Tiny shared helpers for the seed steps."""

import uuid
from datetime import date, datetime, timedelta, timezone

now = datetime.now(timezone.utc)


def uid() -> uuid.UUID:
    return uuid.uuid4()


def past_date(days_ago: int) -> date:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).date()


def past_dt(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)
