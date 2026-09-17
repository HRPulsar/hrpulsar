"""Celery tasks for the data-import module.

Moved out of ``app.core.tasks`` (project-review #30) so core no longer
imports domain models: the bulk employee/dictionary import reads and
writes ``auth``, ``employee`` and ``dictionary`` rows and is enqueued
from ``data_import/service.py``.
"""

import logging

from app.core.celery_app import celery

logger = logging.getLogger(__name__)

SET_PASSWORD_EMAIL_PACE_SECONDS = 0.5
# Links per email task. A redelivered task (a worker lost mid-batch, Redis's
# one-hour visibility timeout) repeats at most one batch of sends.
SET_PASSWORD_EMAIL_BATCH = 50
# A demo sandbox emails only the first few people its visitor adds: the
# visitor is anonymous, and the addresses in the file are theirs to choose.
# Mirrored in the import page hint (demo-email-limit-parity.test.ts).
DEMO_IMPORT_EMAIL_LIMIT = 5


@celery.task(bind=True, max_retries=1, default_retry_delay=30)
def run_import_task(
    self,
    job_id: str,
    tenant_id: str,
    user_id: str,
    import_type: str,
    b64_file_data: str,
) -> None:
    """Process data import in background. Updates ImportJob status as it runs."""
    import base64
    import secrets
    import uuid
    from datetime import date as date_type
    from datetime import datetime, timezone

    from pydantic import EmailStr, TypeAdapter, ValidationError
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.core.i18n import resolve_locale
    from app.core.security import hash_password
    from app.database import make_sync_engine
    from app.modules.auth.models import User
    from app.modules.auth.roles import ensure_baseline_employee_role_sync
    from app.modules.auth.service import can_send_set_password_link
    from app.modules.company.models import Tenant
    from app.modules.data_import.models import ImportJob
    from app.modules.data_import.service import read_rows
    from app.modules.demo.utils import is_demo_cast_email
    from app.modules.dictionary.models import DictionaryItem
    from app.modules.employee.models import Course, Education, Employee, WorkExperience
    from app.modules.position.models import Position

    engine = make_sync_engine(settings.database_url)
    email_adapter = TypeAdapter(EmailStr)
    # Ids of the new accounts to email a set-password link.
    recipients: list[str] = []
    locale = "en"

    def _parse_date(value) -> date_type | None:
        if value is None:
            return None
        if isinstance(value, date_type):
            return value if not isinstance(value, datetime) else value.date()
        raw = str(value).strip()
        # ISO from the template; DD.MM.YYYY is how a German Excel writes a
        # date into CSV.
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                pass
        return None

    try:
        with Session(engine) as db:
            job = db.get(ImportJob, uuid.UUID(job_id))
            if not job:
                logger.error("Import job %s not found", job_id)
                return
            # task_acks_late: a worker lost after the commit below gets this
            # message redelivered. The file is in already, and a second pass
            # would add every row's experience, education and courses again.
            if job.status == "completed":
                logger.warning("Import job %s already completed, skipped", job_id)
                return

            job.status = "processing"
            job.started_at = datetime.now(timezone.utc)
            db.commit()

            rows = read_rows(job.file_name, base64.b64decode(b64_file_data))

            tid = uuid.UUID(tenant_id)
            tenant = db.get(Tenant, tid)
            locale = resolve_locale(
                tenant_default=tenant.default_locale if tenant else None
            )
            email_budget: int | None = None
            if tenant is not None and tenant.is_demo:
                # The session-wide budget, not per file: another import must
                # not buy another five emails. Held until the job commits, so
                # a second import in the session counts this one's users.
                db.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                    {"key": f"demo-import-emails:{tenant_id}"},
                )
                added_before = sum(
                    not is_demo_cast_email(email)
                    for email in db.scalars(
                        select(User.email).where(User.tenant_id == tid)
                    )
                )
                email_budget = max(0, DEMO_IMPORT_EMAIL_LIMIT - added_before)
            processed = 0
            error_count = 0
            errors: dict[str, list] = {"rows": []}

            if import_type == "employees":
                for i, row in rows:
                    try:
                        if len(row) < 5 or not all(row[:5]):
                            errors["rows"].append(
                                {"row": i, "error": "Missing required fields"}
                            )
                            error_count += 1
                            continue
                        hire_date = _parse_date(row[4])
                        if hire_date is None:
                            errors["rows"].append(
                                {
                                    "row": i,
                                    "error": "hire_date must be YYYY-MM-DD"
                                    " or DD.MM.YYYY",
                                }
                            )
                            error_count += 1
                            continue

                        try:
                            # Normalized the way login and invitations store
                            # it, or the person could never sign in.
                            email = email_adapter.validate_python(str(row[0]))
                        except ValidationError:
                            errors["rows"].append({"row": i, "error": "Invalid email"})
                            error_count += 1
                            continue
                        first_name, last_name = str(row[1]), str(row[2])
                        position_title = str(row[3])

                        # A savepoint per row: a row that fails in the
                        # database must not roll back the rows before it.
                        with db.begin_nested():
                            user = db.execute(
                                select(User).where(
                                    User.email == email, User.tenant_id == tid
                                )
                            ).scalar_one_or_none()

                            created_user = user is None
                            if user is None:
                                user = User(
                                    email=email,
                                    # HRP-806: nobody knows this password; the
                                    # set-password link sent below is the way in.
                                    password_hash=hash_password(
                                        secrets.token_urlsafe(32)
                                    ),
                                    first_name=first_name,
                                    last_name=last_name,
                                    tenant_id=tid,
                                )
                                db.add(user)
                                db.flush()
                                # HRP-619: an imported account with no role at
                                # all renders a blank role everywhere and
                                # confuses every role gate.
                                ensure_baseline_employee_role_sync(db, user.id)

                            emp = db.execute(
                                select(Employee).where(
                                    Employee.user_id == user.id,
                                    Employee.tenant_id == tid,
                                )
                            ).scalar_one_or_none()

                            if not emp:
                                pos = db.execute(
                                    select(Position).where(
                                        Position.tenant_id == tid,
                                        Position.title == position_title,
                                    )
                                ).scalar_one_or_none()
                                if not pos:
                                    pos = Position(
                                        tenant_id=tid,
                                        title=position_title,
                                        source="manual",
                                    )
                                    db.add(pos)
                                    db.flush()
                                emp = Employee(
                                    user_id=user.id,
                                    tenant_id=tid,
                                    position_id=pos.id,
                                    position_title=position_title,
                                    hire_date=hire_date,
                                    status_changed_at=datetime.now(timezone.utc),
                                )
                                db.add(emp)
                                db.flush()

                            # GF1: Work experience (columns 5-8)
                            work_title = row[5] if len(row) > 5 and row[5] else None
                            if work_title:
                                work_role = (
                                    str(row[6]) if len(row) > 6 and row[6] else None
                                )
                                work_start = _parse_date(
                                    row[7] if len(row) > 7 else None
                                )
                                work_end = _parse_date(row[8] if len(row) > 8 else None)
                                if work_start:
                                    db.add(
                                        WorkExperience(
                                            employee_id=emp.id,
                                            tenant_id=tid,
                                            title=str(work_title),
                                            role=work_role,
                                            start_date=work_start,
                                            end_date=work_end,
                                        )
                                    )

                            # GF2: Education (columns 9-13)
                            edu_institution = (
                                row[9] if len(row) > 9 and row[9] else None
                            )
                            if edu_institution:
                                edu_degree = (
                                    str(row[10])
                                    if len(row) > 10 and row[10]
                                    else "Bachelor"
                                )
                                edu_field = (
                                    str(row[11]) if len(row) > 11 and row[11] else ""
                                )
                                edu_start = _parse_date(
                                    row[12] if len(row) > 12 else None
                                )
                                edu_end = _parse_date(
                                    row[13] if len(row) > 13 else None
                                )
                                if edu_start:
                                    db.add(
                                        Education(
                                            employee_id=emp.id,
                                            tenant_id=tid,
                                            institution=str(edu_institution),
                                            degree=edu_degree,
                                            field_of_study=edu_field,
                                            start_date=edu_start,
                                            end_date=edu_end,
                                        )
                                    )

                            # GF2: Courses (columns 14-16)
                            course_title = (
                                row[14] if len(row) > 14 and row[14] else None
                            )
                            if course_title:
                                course_provider = (
                                    str(row[15]) if len(row) > 15 and row[15] else None
                                )
                                course_date = _parse_date(
                                    row[16] if len(row) > 16 else None
                                )
                                db.add(
                                    Course(
                                        employee_id=emp.id,
                                        tenant_id=tid,
                                        title=str(course_title),
                                        provider=course_provider,
                                        completed_date=course_date,
                                    )
                                )

                        if created_user and can_send_set_password_link(
                            user, emp.status
                        ):
                            recipients.append(str(user.id))
                        processed += 1
                    except Exception as e:  # noqa: BLE001 - per-row isolation
                        errors["rows"].append({"row": i, "error": str(e)})
                        error_count += 1

            elif import_type == "dictionaries":
                for i, row in rows:
                    try:
                        if len(row) < 2 or not row[0] or not row[1]:
                            errors["rows"].append(
                                {"row": i, "error": "Missing type or title"}
                            )
                            error_count += 1
                            continue

                        item_type, title = str(row[0]), str(row[1])
                        description = str(row[2]) if len(row) > 2 and row[2] else None

                        # A savepoint per row, as for employees.
                        with db.begin_nested():
                            existing_item = db.execute(
                                select(DictionaryItem).where(
                                    DictionaryItem.type == item_type,
                                    DictionaryItem.title == title,
                                    DictionaryItem.tenant_id == tid,
                                )
                            ).scalar_one_or_none()

                            if not existing_item:
                                db.add(
                                    DictionaryItem(
                                        type=item_type,
                                        title=title,
                                        description=description,
                                        tenant_id=tid,
                                    )
                                )
                        processed += 1
                    except Exception as e:  # noqa: BLE001 - per-row isolation
                        errors["rows"].append({"row": i, "error": str(e)})
                        error_count += 1

            if email_budget is not None:
                recipients = recipients[:email_budget]
            job.processed_rows = processed
            job.error_rows = error_count
            job.errors = errors if error_count > 0 else None
            job.status = "completed"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(
                "Import job %s completed: %d processed, %d errors",
                job_id,
                processed,
                error_count,
            )

    except Exception as exc:
        logger.exception("Import job %s failed: %s", job_id, exc)
        try:
            with Session(engine) as db:
                job = db.get(ImportJob, uuid.UUID(job_id))
                if job:
                    job.status = "failed"
                    job.errors = {"rows": [], "fatal": str(exc)}
                    job.finished_at = datetime.now(timezone.utc)
                    db.commit()
        except Exception:
            logger.exception("Failed to update import job status to failed")
        raise self.retry(exc=exc)
    finally:
        engine.dispose()

    # Outside the job's try on purpose: the import is committed, so a failure
    # here must neither mark it failed nor trigger a retry that imports the
    # file a second time.
    if recipients:
        try:
            send_set_password_links_task.delay(recipients, locale, job_id)
        except Exception:  # noqa: BLE001 - a broker hiccup must not fail the import
            logger.exception("Queueing set-password links for job %s failed", job_id)


@celery.task
def send_set_password_links_task(
    user_ids: list[str], locale: str, job_id: str | None = None
) -> None:
    """Email imported accounts their set-password link (HRP-806).

    One batch per task, the rest queued behind it, so a redelivered task
    repeats a batch of sends and never outlives the visibility timeout. Each
    account is read again right before its send: an admin may have re-sent
    the link from the card since the import, and a link pinned to the version
    the import saw would arrive dead. Someone who has set a password or been
    blocked in the meantime gets nothing.

    Links that did not go out are counted on the import job, so a batch lost
    to a rate-limited provider is visible instead of silently completed.
    """
    import time
    import uuid

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.core.email import email_provider_configured
    from app.database import make_sync_engine
    from app.modules.auth.models import User
    from app.modules.auth.service import (
        can_send_set_password_link,
        send_set_password_link,
    )
    from app.modules.employee.models import Employee

    # ponytail: fixed pace under Resend's per-second rate limit, on every
    # attempt (a rejected send is often the limit itself); a rate-limited
    # email queue if imports outgrow it. No provider, nothing to pace.
    provider = email_provider_configured()
    pace = SET_PASSWORD_EMAIL_PACE_SECONDS if provider else 0
    engine = make_sync_engine(settings.database_url)
    failed = 0
    try:
        for user_id in user_ids[:SET_PASSWORD_EMAIL_BATCH]:
            with Session(engine) as db:
                found = db.execute(
                    select(User, Employee.status)
                    .join(Employee, Employee.user_id == User.id)
                    .where(User.id == uuid.UUID(user_id))
                ).first()
            if found is None or not can_send_set_password_link(*found):
                continue
            user = found[0]
            try:
                sent = send_set_password_link(
                    user.id, user.email, user.first_name, user.token_version, locale
                )
            except Exception:  # noqa: BLE001 - one address must not stop the rest
                logger.exception("Set-password link for %s failed", user.email)
                sent = False
            if not sent and provider:
                # send_email swallows the provider's error and answers False:
                # without this the whole batch can be lost to one 429 while
                # the job still reads "completed". No provider is not a
                # failure: the link went to the operator's log by design.
                logger.warning("Set-password link for %s did not go out", user.email)
                failed += 1
            time.sleep(pace)
        _record_unsent_links(engine, job_id, failed)
    finally:
        engine.dispose()
        # In ``finally``: a batch that broke halfway must still hand the rest
        # of the list on, or those accounts never get a link at all.
        if len(user_ids) > SET_PASSWORD_EMAIL_BATCH:
            try:
                send_set_password_links_task.delay(
                    user_ids[SET_PASSWORD_EMAIL_BATCH:], locale, job_id
                )
            except Exception:  # noqa: BLE001 - logged; the sent batch stands
                logger.exception("Queueing the next set-password batch failed")


def _record_unsent_links(engine, job_id: str | None, failed: int) -> None:
    """Count set-password links that never went out on the import job.

    There is no column for it: the job's JSON ``errors`` is what the API and
    the admin already read, so the counter lives there and needs no migration.
    Batches are chained one after another, so the read-modify-write is safe.
    """
    if not failed or not job_id:
        return
    import uuid

    from sqlalchemy.orm import Session

    from app.modules.data_import.models import ImportJob

    try:
        with Session(engine) as db:
            job = db.get(ImportJob, uuid.UUID(job_id))
            if job is None:
                return
            errors = dict(job.errors or {"rows": []})
            errors["emails_failed"] = errors.get("emails_failed", 0) + failed
            job.errors = errors
            db.commit()
    except Exception:  # noqa: BLE001 - bookkeeping must not lose the sends
        logger.exception("Recording %d unsent set-password links failed", failed)
