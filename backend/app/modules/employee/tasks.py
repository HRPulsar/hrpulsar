"""Celery tasks for the employee module.

Moved out of ``app.core.tasks`` (project-review #30) so core no longer
imports domain models: the daily certificate-expiry check reads
``employee`` (Course/Employee) and ``auth`` (User) rows. Beat schedule
in ``app.core.celery_app`` references this task by its module path.
"""

import logging

from app.core.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task
def check_certificate_expiry() -> None:
    """GF2 Improve: Check for certificates expiring within 30 days and send alerts.

    Runs daily via Celery Beat.
    """
    from datetime import date, timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.core.email import send_email
    from app.core.i18n import resolve_locale
    from app.core.tasks import _tenant_is_demo_sync, send_email_task
    from app.database import make_sync_engine
    from app.modules.auth.models import User
    from app.modules.company.models import Tenant
    from app.modules.employee.models import Course, Employee

    engine = make_sync_engine(settings.database_url)
    try:
        with Session(engine) as db:
            today = date.today()
            threshold = today + timedelta(days=30)

            # Find courses with expiry_date between today and 30 days from now
            courses = db.execute(
                select(Course, Employee, User)
                .join(Employee, Employee.id == Course.employee_id)
                .join(User, User.id == Employee.user_id)
                .where(
                    Course.expiry_date.isnot(None),
                    Course.expiry_date >= today,
                    Course.expiry_date <= threshold,
                )
            ).all()

            from app.core.email_templates import render_certificate_expiry_email

            # i18n F4: one Tenant row per tenant per run — the batch can
            # span many employees of the same company.
            tenant_defaults: dict[object, str | None] = {}

            for course, _employee, user in courses:
                days_left = (course.expiry_date - today).days
                employee_name = f"{user.first_name} {user.last_name}"
                tenant_default: str | None = None
                if user.tenant_id is not None:
                    if user.tenant_id not in tenant_defaults:
                        tenant = db.get(Tenant, user.tenant_id)
                        tenant_defaults[user.tenant_id] = (
                            tenant.default_locale if tenant else None
                        )
                    tenant_default = tenant_defaults[user.tenant_id]
                subject, body = render_certificate_expiry_email(
                    course_title=course.title,
                    expiry_date=course.expiry_date.isoformat(),
                    days_left=days_left,
                    employee_name=employee_name,
                    locale=resolve_locale(
                        user_language=user.language,
                        tenant_default=tenant_default,
                    ),
                )
                # HRP-253 (D5): tenant_id keeps the demo gate effective when
                # a demo seed grows a Course row — the in-task guard only
                # fires when the call-site forwards tenant context.
                tenant_id = (
                    str(user.tenant_id) if user.tenant_id is not None else None
                )
                try:
                    send_email_task.delay(
                        user.email, subject, body, tenant_id=tenant_id
                    )
                except Exception:  # noqa: BLE001 - falls back to inline send
                    if tenant_id is not None and _tenant_is_demo_sync(tenant_id):
                        logger.info(
                            "demo email skipped (cert-expiry inline): tenant=%s",
                            tenant_id,
                        )
                        continue
                    send_email(user.email, subject, body)

            logger.info(
                "Certificate expiry check: found %d expiring certificates", len(courses)
            )
    finally:
        engine.dispose()
