"""Release-2.0 review M19: acks_late needs a matching visibility timeout.

With ``task_acks_late`` on a Redis broker an unacked task is redelivered
once the visibility timeout passes. Transcription (httpx timeout 600s plus
a provider fallback chain) outlived the 1h default, so a still-running task
was handed to a second worker and the tenant paid for it twice.
"""

from __future__ import annotations

from app.core.celery_app import celery


def test_visibility_timeout_outlives_the_longest_task() -> None:
    conf = celery.conf
    assert conf.task_acks_late is True
    visibility = conf.broker_transport_options["visibility_timeout"]
    assert conf.task_soft_time_limit < conf.task_time_limit < visibility


def test_nothing_daily_or_rarer_runs_on_an_interval() -> None:
    """HRP-994: beat keeps no schedule file across deploys, so an interval
    entry restarts its wait on every deploy — a daily one can skip a day.
    Daily-or-rarer entries must be UTC crontabs. Checks the assembled
    schedule (core, the SaaS block, and the EE extension when present)."""
    from datetime import timedelta

    from app.core.celery_app import SAAS_BEAT_SCHEDULE
    from celery.schedules import schedule

    def interval(value: object) -> timedelta | None:
        if isinstance(value, int | float):
            return timedelta(seconds=value)
        if isinstance(value, timedelta):
            return value
        if isinstance(value, schedule):
            return value.run_every
        return None  # crontab / solar: wall clock

    assert celery.conf.timezone == "UTC"
    entries = {**celery.conf.beat_schedule, **SAAS_BEAT_SCHEDULE}
    offenders = sorted(
        name
        for name, entry in entries.items()
        if (every := interval(entry["schedule"])) is not None
        and every >= timedelta(days=1)
    )
    assert not offenders, f"use crontab(hour=..., minute=...) for: {offenders}"
