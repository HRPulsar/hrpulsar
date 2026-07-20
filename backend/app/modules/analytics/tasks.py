"""Celery tasks for the analytics module.

Moved out of ``app.core.tasks`` (project-review #30) so core no longer
imports domain models: the XLSX export reads ``assessment`` rows and is
enqueued from ``analytics/router.py``.
"""

import logging

from app.core.celery_app import celery

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# I3c: XLSX report export as async Celery task
# ---------------------------------------------------------------------------


@celery.task(bind=True, max_retries=1, default_retry_delay=30)
def export_assessments_task(self, tenant_id: str) -> dict:
    """Generate assessments XLSX report in background, upload to S3."""
    import io
    import uuid

    from openpyxl import Workbook
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.core.s3 import upload_file
    from app.database import make_sync_engine
    from app.modules.assessment.models import Assessment

    engine = make_sync_engine(settings.database_url)
    try:
        with Session(engine) as db:
            tid = uuid.UUID(tenant_id)
            assessments = (
                db.execute(
                    select(Assessment)
                    .where(Assessment.tenant_id == tid)
                    .order_by(Assessment.created_at.desc())
                )
                .scalars()
                .all()
            )

            wb = Workbook()
            ws = wb.active
            ws.title = "Assessments"
            ws.append(["ID", "Title", "Employee ID", "Status", "Created At"])

            for a in assessments:
                ws.append(
                    [
                        str(a.id),
                        a.title or "",
                        str(a.employee_id),
                        a.status.code if a.status else "",
                        a.created_at.isoformat() if a.created_at else "",
                    ]
                )

            output = io.BytesIO()
            wb.save(output)
            data = output.getvalue()

            # Upload to S3
            file_id = uuid.uuid4()
            path = f"{tenant_id}/exports/assessments-{file_id}.xlsx"
            content_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            url = upload_file(data, path, content_type)

            logger.info(
                "Export task completed: %d assessments, path=%s", len(assessments), path
            )
            return {"file_url": url, "file_path": path, "row_count": len(assessments)}

    except Exception as exc:
        logger.exception("export_assessments_task failed")
        raise self.retry(exc=exc)
    finally:
        engine.dispose()
