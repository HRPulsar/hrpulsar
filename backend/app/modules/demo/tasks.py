"""Celery beat tasks for the public demo sandbox (HRP-249 — D1).

Currently exposes a single periodic job, ``purge_expired_demo_tenants``,
which walks the demo tenants whose hard TTL or sliding inactivity
window has elapsed and removes them. The actual data wipe is delegated
to Postgres ``ON DELETE CASCADE`` on every ``TenantMixin``-bearing
table: deleting the row in ``tenants`` is enough to clear out the
employees, vacancies, interviews, AI assessments and any other
tenant-scoped state.

Loop shape:

* one short read-only transaction collects candidate tenant ids;
* per-tenant: DELETE in its own short transaction, commit, then nuke
  the tenant's S3 prefix best-effort — so a slow S3 call never holds
  Postgres in ``idle in transaction``, a single failing row never
  poisons the rest of the batch, and the failure mode is orphan blobs
  (recoverable via a sweeper) rather than orphan DB rows.

The task uses a synchronous SQLAlchemy session (``psycopg2``) because
Celery workers don't run an event loop. The engine is cached at module
scope so we don't leak a fresh pool on every 5-minute tick.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, delete, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import settings
from app.core.celery_app import celery
from app.models import Person
from app.modules.company.models import Tenant
from app.modules.recruitment.models import Candidate

logger = logging.getLogger(__name__)

_engine: Engine | None = None


def _sync_engine() -> Engine:
    """Module-cached sync engine.

    Re-creating the engine on every beat tick would leak a fresh
    connection pool every 5 minutes for the lifetime of the worker.
    """
    global _engine
    if _engine is None:
        sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
        _engine = create_engine(sync_url, pool_pre_ping=True)
    return _engine


def _purge_tenant_s3_assets(tenant_id: str) -> None:
    """Best-effort: delete every S3 object prefixed by ``tenants/{id}/``.

    Demo uploads are pinned under this prefix (see D5 — file-upload
    enforcement). HRP-276 / M6 moves the try/except *inside* the page
    loop so a transient failure on one page does not skip the rest —
    pre-fix a single failing page would orphan every later page's blobs.
    """
    from app.core.s3 import get_s3_client

    client = get_s3_client()
    if client is None:
        return

    prefix = f"tenants/{tenant_id}/"
    try:
        paginator = client.get_paginator("list_objects_v2")
    except Exception:  # noqa: BLE001
        logger.exception("demo: failed to open paginator for prefix %s", prefix)
        return

    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
        try:
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if not keys:
                continue
            client.delete_objects(
                Bucket=settings.s3_bucket,
                Delete={"Objects": keys, "Quiet": True},
            )
        except Exception:  # noqa: BLE001 — per-page best-effort cleanup
            logger.exception(
                "demo: failed to purge S3 page for prefix %s; continuing", prefix
            )
            continue


def _expired_demo_tenant_ids(db: Session, now: datetime) -> list:
    inactivity_cutoff = now - timedelta(
        seconds=settings.demo_inactivity_ttl_seconds
    )
    # NULL-safe predicate. ``expires_at`` may legitimately be NULL on a
    # tenant that was flagged demo but never given a hard TTL — in that
    # case we still want the sliding-inactivity branch to catch it via
    # ``COALESCE(last_active_at, created_at)``, which never evaluates to
    # NULL (``created_at`` is NOT NULL on every row).
    stmt = select(Tenant.id).where(
        Tenant.is_demo.is_(True),
        or_(
            Tenant.expires_at < now,
            func.coalesce(Tenant.last_active_at, Tenant.created_at)
            < inactivity_cutoff,
        ),
    )
    return list(db.execute(stmt).scalars().all())


@celery.task(
    bind=True,
    name="app.modules.demo.tasks.purge_expired_demo_tenants",
    max_retries=0,
)
def purge_expired_demo_tenants(self: Any) -> dict[str, int]:
    """Drop demo tenants whose TTL or inactivity window has elapsed."""

    now = datetime.now(timezone.utc)
    summary = {"scanned": 0, "deleted": 0}

    engine = _sync_engine()

    # 1. Pull the candidate ids in one read-only transaction so any slow
    #    S3 call later never strands a Postgres transaction in
    #    ``idle in transaction``.
    with Session(engine) as db:
        tenant_ids = _expired_demo_tenant_ids(db, now)
        summary["scanned"] = len(tenant_ids)

    # 2. Per-tenant: DELETE in its own short tx, commit, then purge S3.
    #    A failure on any one tenant gets logged and skipped — the rest
    #    of the batch still completes, and the offender will be retried
    #    on the next tick (5 min). DB-first ordering means a transient
    #    S3 failure only orphans blobs, not rows.
    for tenant_id in tenant_ids:
        try:
            with Session(engine) as db, db.begin():
                # HRP-276 / H2: pre-fix demo seed wrote Person rows for
                # every candidate. Person has no tenant_id and CASCADE
                # runs Person → Candidate, not the other way round, so
                # tenant deletion alone would leave 8 orphan rows per
                # purged demo session. The seed no longer creates them,
                # but we still need to clean up the backlog from older
                # demos so the global Person registry doesn't accrete.
                # Person rows that any non-demo tenant still references
                # are preserved (NOT EXISTS guard) — the dedup branch
                # in create_candidate could theoretically have linked a
                # paid candidate onto a seed Person before C1 landed.
                person_ids = db.execute(
                    select(Candidate.person_id).where(
                        Candidate.tenant_id == tenant_id,
                        Candidate.person_id.is_not(None),
                    )
                ).scalars().all()
                # HRP-249 review (HIGH): the candidate id list comes from
                # an earlier read-only transaction, so a tenant that
                # flipped from demo to paid between the SELECT and this
                # DELETE must not be wiped. ``Tenant.is_demo.is_(True)``
                # turns the DELETE into a no-op for any non-demo tenant
                # even if a concurrent UPDATE landed in the window, and
                # the rowcount below lets us skip the S3 purge for a row
                # that wasn't actually deleted.
                deleted_rows: int = db.execute(
                    delete(Tenant).where(
                        Tenant.id == tenant_id,
                        Tenant.is_demo.is_(True),
                    )
                ).rowcount  # type: ignore[attr-defined]
                if person_ids:
                    db.execute(
                        delete(Person).where(
                            Person.id.in_(person_ids),
                            ~select(Candidate.id)
                            .where(Candidate.person_id == Person.id)
                            .exists(),
                        )
                    )
        except Exception:  # noqa: BLE001
            logger.exception(
                "demo: failed to delete tenant %s", tenant_id
            )
            continue
        if deleted_rows == 0:
            # Tenant flipped to non-demo (or vanished) between the
            # candidate scan and the DELETE. The is_demo guard above
            # blocked the row from being wiped — also skip the S3 purge
            # since those objects may now belong to the upgraded tenant.
            logger.info(
                "demo: skipping purge of tenant %s — no longer is_demo",
                tenant_id,
            )
            continue
        summary["deleted"] += 1
        _purge_tenant_s3_assets(str(tenant_id))

    if summary["deleted"]:
        logger.info(
            "demo: purged %d expired tenant(s)", summary["deleted"]
        )
    return summary


_TENANT_PREFIX_PATTERN = "tenants/"


@celery.task(
    bind=True,
    name="app.modules.demo.tasks.purge_orphan_demo_blobs",
    max_retries=0,
)
def purge_orphan_demo_blobs(self: Any) -> dict[str, int]:
    """Nightly reconciler — drop S3 prefixes whose tenant row is gone.

    HRP-276 / M6: ``_purge_tenant_s3_assets`` is best-effort and can
    leave behind a partially-cleaned prefix when S3 is flaky. This
    sweeper lists every ``tenants/<uuid>/`` top-level prefix, checks
    each against the ``tenants`` table, and deletes the prefix if no
    matching tenant row exists. Idempotent — skipping the run on a bad
    day is fine, it just defers the reconciliation by 24 h.
    """
    summary = {"scanned": 0, "deleted_prefixes": 0}

    from app.core.s3 import get_s3_client

    s3 = get_s3_client()
    if s3 is None:
        return summary

    try:
        paginator = s3.get_paginator("list_objects_v2")
        prefix_ids: set[str] = set()
        for page in paginator.paginate(
            Bucket=settings.s3_bucket,
            Prefix=_TENANT_PREFIX_PATTERN,
            Delimiter="/",
        ):
            for entry in page.get("CommonPrefixes", []) or []:
                key = entry.get("Prefix", "")
                if not key.startswith(_TENANT_PREFIX_PATTERN):
                    continue
                trimmed = key[len(_TENANT_PREFIX_PATTERN) :].rstrip("/")
                if not trimmed:
                    continue
                prefix_ids.add(trimmed)
    except Exception:  # noqa: BLE001
        logger.exception("demo: orphan-blob sweeper failed to list prefixes")
        return summary

    summary["scanned"] = len(prefix_ids)
    if not prefix_ids:
        return summary

    # Filter against tenants table — anything still alive stays.
    import uuid as _uuid

    candidate_uuids: set[_uuid.UUID] = set()
    for prefix in prefix_ids:
        try:
            candidate_uuids.add(_uuid.UUID(prefix))
        except ValueError:
            # Non-UUID prefixes are foreign objects; leave them alone.
            continue
    if not candidate_uuids:
        return summary

    engine = _sync_engine()
    with Session(engine) as db:
        live_ids = set(
            db.execute(
                select(Tenant.id).where(Tenant.id.in_(candidate_uuids))
            ).scalars().all()
        )
    orphan_ids = candidate_uuids - live_ids

    for orphan_id in orphan_ids:
        _purge_tenant_s3_assets(str(orphan_id))
        summary["deleted_prefixes"] += 1

    if summary["deleted_prefixes"]:
        logger.info(
            "demo: orphan-blob sweep deleted %d prefix(es)",
            summary["deleted_prefixes"],
        )
    return summary
