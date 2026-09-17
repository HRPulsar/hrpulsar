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
