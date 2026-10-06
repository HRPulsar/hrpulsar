"""Celery application configuration."""

import logging

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging as celery_setup_logging
from celery.signals import worker_init

from app.config import settings


@celery_setup_logging.connect
def on_celery_setup_logging(**kwargs):
    """Override Celery's default logging with JSON formatter."""
    from app.core.logging import setup_logging

    loglevel = kwargs.get("loglevel", "INFO")
    if isinstance(loglevel, int):
        loglevel = logging.getLevelName(loglevel)
    setup_logging(level=loglevel)


@worker_init.connect
def on_worker_init(**kwargs):
    """Import model + task modules so SQLAlchemy mappers resolve
    cross-module relationships and so beat-dispatched tasks are
    registered before the first job pulls off the queue.

    ``autodiscover_tasks`` is a deferred finalize hook; force-importing
    here closes the race where a cold worker pulls a beat-scheduled
    task before that hook fires.
    """
    import importlib
    from pathlib import Path

    from app.database import import_all_models

    import_all_models()

    modules_dir = Path(__file__).resolve().parent.parent / "modules"
    # `tasks` may be a single module (`tasks.py`) or a package
    # (`tasks/__init__.py`, e.g. recruitment after the #20 split — its
    # __init__ imports every task submodule).
    task_modules = {
        f"app.modules.{tasks_file.parent.name}.tasks"
        for tasks_file in modules_dir.glob("*/tasks.py")
    } | {
        f"app.modules.{init_file.parent.parent.name}.tasks"
        for init_file in modules_dir.glob("*/tasks/__init__.py")
    }
    for module_name in sorted(task_modules):
        try:
            importlib.import_module(module_name)
        except ImportError:
            # Some modules legitimately don't define tasks.py at the
            # canonical path (or import circular guards we don't want
            # to fight here). Skip silently — autodiscover still runs.
            continue

    # HRP-982: the upload -> transcribe -> analyze auto chain calls the same
    # recruitment service functions as the API, so it needs the same audit
    # wrappers. Installed here, after `extend_celery` put the billing ones
    # on at import time, so audit wraps outside billing as in the API.
    from app.modules.recruitment.audit_registry import register_audit_hooks

    register_audit_hooks()


celery = Celery(
    "hrpulsar",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # ``task_acks_late`` + Redis means an unacked task is redelivered once
    # the broker's visibility timeout elapses (default 1h). Transcription
    # with its fallback chain runs longer than that, so the old default
    # re-ran finished work and billed the tenant twice. Ceiling the task
    # below the window instead: soft limit raises SoftTimeLimitExceeded,
    # hard limit kills the worker process, both well inside 2h.
    broker_transport_options={"visibility_timeout": 7200},
    task_soft_time_limit=6600,
    task_time_limit=6900,
    # Beat schedule for periodic tasks. Anything daily or rarer is a UTC
    # wall-clock crontab, never an interval: beat keeps no schedule file
    # across deploys, so an 86400.0 entry restarts its 24 h wait on every
    # deploy and can skip a day outright (HRP-994). Times are spread so the
    # nightly jobs do not all start at once.
    beat_schedule={
        "send-assessment-reminders": {
            "task": "app.modules.assessment.tasks.send_deadline_reminders",
            "schedule": 3600.0,  # every hour
        },
        "check-certificate-expiry": {
            "task": "app.modules.employee.tasks.check_certificate_expiry",
            "schedule": crontab(hour=2, minute=10),
        },
        "refresh-model-catalog": {
            # HRP-466: daily AI model discovery — core on purpose, so
            # community installs with provider keys also pick up new
            # models without a redeploy.
            "task": "app.modules.ai.tasks.refresh_model_catalog_task",
            "schedule": crontab(hour=3, minute=20),
        },
        "write-celery-heartbeat": {
            "task": "app.core.tasks.write_celery_heartbeat",
            "schedule": 30.0,  # every 30s — feeds /health celery check + status page
        },
        "cleanup-stuck-recruitment-tasks": {
            # R3b H-3: catches workers killed mid-task (OOM / kill -9) where
            # task_failure never fires; the signal handler in
            # app.modules.recruitment.tasks covers the regular exception
            # path. Threshold inside the task is 15 minutes.
            "task": "app.modules.recruitment.tasks.cleanup_stuck_recruitment_tasks_task",
            "schedule": 600.0,  # every 10 minutes
        },
        "purge-archived-interviews": {
            # HRP-418: archived interviews are restorable for 90 days; after
            # that the recording is dropped from object storage while the
            # row stays for audit. Window enforced inside the task.
            "task": "app.modules.recruitment.tasks.purge_archived_interviews_task",
            "schedule": crontab(hour=1, minute=40),
        },
        "cleanup-detached-resume-files": {
            # HRP-181 REDO Stage 3: bulk-upload resumes the user never
            # finalised. 7-day retention window enforced inside the task.
            "task": "app.modules.recruitment.tasks.cleanup_detached_resume_files_task",
            "schedule": crontab(hour=4, minute=10),
        },
        "apply-recruitment-retention": {
            # HRP-983: each tenant's recruitment retention settings. A
            # wall-clock crontab in UTC (an interval restarts its wait on
            # every deploy); 02:40 is clear of the other nightly jobs.
            "task": "app.modules.recruitment.tasks.apply_recruitment_retention_task",
            "schedule": crontab(hour=2, minute=40),
        },
        "reap-stuck-compgen-sessions": {
            # HRP-163: counterpart for the AI competence-generation worker.
            # `_force_terminate_running` covers the in-process crash path;
            # this beat job covers OOM / SIGKILL / host reboot where the
            # row would otherwise stay in `running` and block the user's
            # partial unique index. Threshold inside the task is 15 min.
            "task": "ai_competence_generation.reap_stuck_sessions",
            "schedule": 300.0,  # every 5 minutes
        },
        "reap-stuck-work-decomposition-sessions": {
            # HRP-755: same safety net for the AI decomposition worker — a
            # row stuck in `running` holds the container's one-active-run
            # slot. Threshold inside the task is 30 min.
            "task": "work.reap_stuck_sessions",
            "schedule": 300.0,  # every 5 minutes
        },
        "purge-expired-public-checks": {
            # HRP-923: anonymous check results past their 10-day term go,
            # with their sandbox containers. A wall-clock crontab, not
            # 86400.0 (HRP-994); 04:20 UTC is clear of the other daily jobs.
            "task": "public_check.purge_expired",
            "schedule": crontab(hour=4, minute=20),
        },
    },
)

# HRP-391: the public-demo sandbox is enterprise-only — its purge/reconcile
# beat entries are scheduled only in SaaS. Community deployments have no
# demo tenants to reap, and the tasks stay importable either way. Named so
# the schedule tests can see the SaaS entries in an on-prem test run.
SAAS_BEAT_SCHEDULE = {
    "purge-expired-demo-tenants": {
        # HRP-249 (D1): drop public-demo sandboxes whose hard TTL or
        # sliding inactivity window has elapsed. The tenant row's
        # cascade FKs do the rest of the data wipe.
        "task": "app.modules.demo.tasks.purge_expired_demo_tenants",
        "schedule": 300.0,  # every 5 minutes
    },
    "purge-orphan-demo-blobs": {
        # HRP-276 / M6: nightly reconciler — drop S3 prefixes whose
        # tenants table row is gone (transient S3 failures during
        # the per-tenant purge can leave blobs behind).
        "task": "app.modules.demo.tasks.purge_orphan_demo_blobs",
        "schedule": crontab(hour=4, minute=40),
    },
}
if settings.deployment_mode == "saas":
    celery.conf.beat_schedule.update(SAAS_BEAT_SCHEDULE)

# Auto-discover tasks across core + module-level task packages.
# `on_worker_init` also glob-imports every `app/modules/*/tasks.py`, but the
# beat-scheduled tasks below (assessment / employee) are listed explicitly so
# a beat dispatcher registers them by name even outside a worker process.
celery.autodiscover_tasks(
    [
        "app.core",
        "app.modules.ai",
        "app.modules.ai_competence_generation",
        "app.modules.analytics",
        "app.modules.assessment",
        "app.modules.data_import",
        "app.modules.demo",
        "app.modules.employee",
        "app.modules.primitives",
        "app.modules.public_check",
        "app.modules.recruitment",
        "app.modules.talent_market",
        "app.modules.work",
    ]
)

# CR15: Celery → WebSocket bridge. Importing the module registers the
# task_prerun / task_postrun / task_failure signal handlers that PUBLISH
# `task.updated` events to the per-user Redis channel.
from app.core import celery_signals  # noqa: E402, F401

# Optional enterprise extension. Mirrors the try-import in app.main where
# `ee.register_enterprise(app)` plugs in. Community builds strip `ee/`, so
# the import fails and we simply run with the core schedule. Keeping the
# hook here means new core periodic tasks no longer need an overlay copy
# of this file — the EE delta lives only in `ee/celery_extras.py`.
try:
    from ee.celery_extras import extend_celery

    extend_celery(celery)
except ImportError:
    pass
