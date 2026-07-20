"""Core infrastructure Celery tasks.

Only cross-cutting infrastructure lives here — outbound email delivery
(with the demo-tenant gate + delivery logging) and the worker heartbeat.
Domain-specific background jobs live in their own module's ``tasks.py``
(project-review #30): ``employee`` (certificate expiry), ``assessment``
(deadline reminders), ``analytics`` (XLSX export), ``data_import`` (bulk
import) and ``ai`` (batch embeddings). Keeping this file free of domain
model imports stops core from structurally knowing every domain.
"""

import logging

from app.core.celery_app import celery
from app.core.email import send_email

logger = logging.getLogger(__name__)


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_task(
    self,
    to: str,
    subject: str,
    html_body: str,
    tenant_id: str | None = None,
    template_code: str | None = None,
) -> tuple[bool, str | None]:
    """Send email in background with delivery tracking.

    Retries up to 3 times on failure. Creates EmailLog entry for tracking.

    HRP-253 (D5): demo tenants must not generate outbound mail. The check
    runs here (the single mass-call entry point for tenant-scoped emails)
    rather than at every call-site, so adding a new ``enqueue_email``
    caller can't accidentally bypass the gate.
    """
    if tenant_id is not None and _tenant_is_demo_sync(tenant_id):
        logger.info(
            "demo email skipped: tenant=%s recipient=%s template=%s",
            tenant_id,
            to,
            template_code,
        )
        return False, None
    try:
        ok, message_id = send_email(to, subject, html_body)
        if not ok:
            raise RuntimeError(f"Email delivery failed to {to}")
        # Log successful delivery
        _log_email(
            tenant_id=tenant_id,
            recipient=to,
            subject=subject,
            template_code=template_code,
            status="sent",
            message_id=message_id,
            attempts=self.request.retries + 1,
        )
        return ok, message_id
    except Exception as exc:  # noqa: BLE001 - task boundary: logged, then retried
        if self.request.retries >= self.max_retries:
            # Final failure — log as failed
            _log_email(
                tenant_id=tenant_id,
                recipient=to,
                subject=subject,
                template_code=template_code,
                status="failed",
                error=str(exc),
                attempts=self.request.retries + 1,
            )
            logger.error(
                "Email task permanently failed after %d retries: %s",
                self.max_retries,
                exc,
            )
            return False, None
        logger.warning(
            "Email task failed (attempt %d), retrying: %s",
            self.request.retries + 1,
            exc,
        )
        raise self.retry(exc=exc)


_demo_gate_engine = None  # cached module-level engine, built lazily


def _tenant_is_demo_sync(tenant_id: str | None) -> bool:
    """One-shot ``Tenant.is_demo`` lookup over a cached sync engine.

    Used from Celery and from the synchronous inline-fallback in
    :func:`app.core.email.enqueue_email`. Returns False on any error so
    a broken DB never silently drops legitimate paid-tenant email.

    The engine is module-cached because the gate is called once per
    outbound email — a per-call ``make_sync_engine + dispose`` cycle
    cost minutes of pool-hold under invitation batches. The shared
    engine keeps the SELECT to a single pre-warmed connection.
    """
    if tenant_id is None:
        return False
    global _demo_gate_engine
    try:
        from sqlalchemy.orm import Session

        from app.config import settings
        from app.database import make_sync_engine
        from app.modules.demo.utils import is_demo_tenant_sync

        if _demo_gate_engine is None:
            _demo_gate_engine = make_sync_engine(settings.database_url)
        with Session(_demo_gate_engine) as db:
            return is_demo_tenant_sync(db, tenant_id)
    except Exception as exc:  # noqa: BLE001
        # logger.warning, not exception — the gate is intentionally
        # fail-open and a transient DB blip shouldn't flood logs with
        # full tracebacks for every queued email.
        logger.warning(
            "demo email gate: tenant lookup failed for %s (%s)", tenant_id, exc
        )
        return False


def _log_email(
    *,
    tenant_id: str | None,
    recipient: str,
    subject: str,
    template_code: str | None = None,
    status: str = "sent",
    message_id: str | None = None,
    error: str | None = None,
    attempts: int = 1,
) -> None:
    """Create EmailLog entry using a sync DB session (Celery context)."""
    try:
        import uuid

        from sqlalchemy.orm import Session

        from app.config import settings
        from app.database import make_sync_engine
        from app.modules.notification.models import EmailLog

        engine = make_sync_engine(settings.database_url)
        try:
            with Session(engine) as db:
                log = EmailLog(
                    tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
                    recipient=recipient,
                    subject=subject[:500],
                    template_code=template_code,
                    status=status,
                    message_id=message_id,
                    error=error[:2000] if error else None,
                    attempts=attempts,
                )
                db.add(log)
                db.commit()
        finally:
            engine.dispose()
    except Exception:
        logger.exception("Failed to create email log entry")


@celery.task
def write_celery_heartbeat() -> None:
    """Write a timestamp to Redis so /health can prove the worker is alive.

    Key: status:celery:heartbeat. TTL 90s — if the beat task or worker stalls,
    /health flips celery to error within 90s and the public status page picks
    that up on its next probe (~60s later).
    """
    from datetime import datetime, timezone

    import redis

    from app.config import settings

    client = redis.Redis.from_url(settings.redis_url)
    try:
        client.set(
            "status:celery:heartbeat",
            datetime.now(timezone.utc).isoformat(),
            ex=90,
        )
    finally:
        client.close()
