"""Celery tasks for the assessment module.

Moved out of ``app.core.tasks`` (project-review #30) so core no longer
owns domain-specific periodic jobs. Beat schedule in
``app.core.celery_app`` references this task by its module path.
"""

import logging

from app.core.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task
def send_deadline_reminders() -> None:
    """Periodic task: check for upcoming deadlines and send reminders.

    Runs every hour via Celery Beat. Checks assessments and PDPs
    with deadlines approaching in the next 24 hours.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy.orm import Session

    from app.config import settings
    from app.database import make_sync_engine

    engine = make_sync_engine(settings.database_url)
    try:
        with Session(engine) as _db:  # noqa: F841
            now = datetime.now(timezone.utc)
            tomorrow = now + timedelta(hours=24)
            logger.info("Checking deadlines between %s and %s", now, tomorrow)
            # Future: query assessments/PDPs with deadline in range and send
            # reminders via render_deadline_reminder_email — its entity_type
            # must be one of "assessment" / "pdp" / "exam" (HRP-584: any
            # other value renders as a raw upper-cased code).
    finally:
        engine.dispose()
