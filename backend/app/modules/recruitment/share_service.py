"""R4c report sharing service (FR-22, SCR-84).

Recruiters share consolidated XLSX reports with stakeholders who
don't have a tenant account. We generate a tokenised public link
(``/reports/share/{token}``), email it to the recipients via Resend
and audit both the issuance and every subsequent open.

The share row stores recipients as a JSONB list of email addresses so
revoking a share is a single ``DELETE`` and we don't have to track
fan-out delivery per recipient.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AppError
from app.modules.recruitment import audit_service
from app.modules.recruitment.models import (
    ConsolidatedReport,
    RecruitmentReportShare,
    Vacancy,
)
from app.modules.storage.models import File

_SHARE_URL_WARNED = False


def _share_url(token: str) -> str:
    """Build the public share URL for a token.

    In production ``frontend_url`` must be set explicitly. The fallback
    is a heuristic over ``cors_origins`` — we prefer an ``app.`` host
    over a marketing root domain, because tokenised report sharing is
    served by the Next.js app, not the landing page.
    """

    base = (settings.frontend_url or "").rstrip("/")
    if not base:
        origins = [
            o.strip().rstrip("/")
            for o in (settings.cors_origins or "").split(",")
            if o.strip()
        ]
        app_origin = next((o for o in origins if "://app." in o), None)
        base = app_origin or (origins[0] if origins else "https://app.hrpulsar.com")
        global _SHARE_URL_WARNED
        if settings.deployment_mode == "saas" and not _SHARE_URL_WARNED:
            import logging

            logging.getLogger(__name__).warning(
                "frontend_url is empty in SaaS mode — report share links "
                "will fall back to %s. Set FRONTEND_URL to the canonical "
                "app host (e.g. https://app.hrpulsar.com).",
                base,
            )
            _SHARE_URL_WARNED = True
    return f"{base}/reports/share/{token}"


def _share_to_read(row: RecruitmentReportShare) -> dict:
    return {
        "id": row.id,
        "report_id": row.report_id,
        "token": row.token,
        "share_url": _share_url(row.token),
        "expires_at": row.expires_at,
        "recipients": list(row.recipients or []),
        "message": row.message,
        "open_count": row.open_count,
        "last_opened_at": row.last_opened_at,
        "revoked_at": row.revoked_at,
        "created_at": row.created_at,
        "created_by": row.created_by,
    }


async def _get_report(
    db: AsyncSession, tenant_id: uuid.UUID, report_id: uuid.UUID
) -> ConsolidatedReport:
    report = (
        await db.execute(
            select(ConsolidatedReport).where(
                ConsolidatedReport.id == report_id,
                ConsolidatedReport.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if report is None:
        raise AppError("report_not_found", status.HTTP_404_NOT_FOUND)
    return report


async def create_share(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    report_id: uuid.UUID,
    *,
    recipients: list[str],
    expires_in_days: int,
    message: str | None,
) -> dict:
    """Create a share row, email recipients, write audit log."""
    report = await _get_report(db, tenant_id, report_id)
    if report.status != "completed" or report.file_id is None:
        raise AppError(
            "share_report_not_ready",
            status.HTTP_409_CONFLICT,
        )

    token = secrets.token_urlsafe(32)
    share = RecruitmentReportShare(
        tenant_id=tenant_id,
        report_id=report_id,
        token=token,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=expires_in_days),
        recipients=list(recipients),
        message=message,
        created_by=user_id,
        open_count=0,
    )
    db.add(share)
    await db.commit()
    await db.refresh(share)

    vacancy = (
        await db.execute(
            select(Vacancy).where(Vacancy.id == report.vacancy_id)
        )
    ).scalar_one_or_none()
    vacancy_title = vacancy.title if vacancy else None

    # Email each recipient via the existing Resend pipeline. Failures are
    # logged but never block the share creation — the token is already
    # usable and visible to the recruiter.
    if recipients:
        from app.core.email import enqueue_email
        from app.core.i18n import resolve_locale, translate
        from app.modules.company.models import Tenant

        # Recipients are bare email addresses of people without an
        # account (i18n F4), so the tenant default is the only locale
        # signal available — never the sharing recruiter's own locale.
        tenant = await db.get(Tenant, tenant_id)
        locale = resolve_locale(
            tenant_default=tenant.default_locale if tenant else None
        )
        vacancy_line = (
            translate(
                "email.report_share.vacancy_line",
                locale,
                vacancy_title=vacancy_title,
            )
            if vacancy_title
            else ""
        )
        message_block = (
            translate("email.report_share.message_block", locale, message=message)
            if message
            else ""
        )
        subject = translate(
            "email.report_share.subject",
            locale,
            shared_by_name=f"{settings.brand_name} Recruiting",
        )
        body = translate(
            "email.report_share.body",
            locale,
            vacancy_line=vacancy_line,
            share_url=_share_url(token),
            expires_at=share.expires_at.isoformat(),
            message_block=message_block,
        )
        for email in recipients:
            try:
                enqueue_email(
                    email,
                    subject,
                    body,
                    tenant_id=str(tenant_id),
                    template_code="recruitment.report_shared",
                )
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger(__name__).exception(
                    "report_shared email failed for %s", email
                )

    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="report.shared",
        entity_type="report_share",
        entity_id=share.id,
        payload_diff={
            "report_id": str(report_id),
            "recipients": list(recipients),
            "expires_in_days": expires_in_days,
        },
    )
    return _share_to_read(share)


async def list_shares(
    db: AsyncSession, tenant_id: uuid.UUID, report_id: uuid.UUID
) -> list[dict]:
    await _get_report(db, tenant_id, report_id)
    rows = (
        await db.execute(
            select(RecruitmentReportShare)
            .where(
                RecruitmentReportShare.tenant_id == tenant_id,
                RecruitmentReportShare.report_id == report_id,
            )
            .order_by(RecruitmentReportShare.created_at.desc())
        )
    ).scalars().all()
    return [_share_to_read(r) for r in rows]


async def revoke_share(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    report_id: uuid.UUID,
    share_id: uuid.UUID,
) -> None:
    share = (
        await db.execute(
            select(RecruitmentReportShare).where(
                RecruitmentReportShare.id == share_id,
                RecruitmentReportShare.tenant_id == tenant_id,
                RecruitmentReportShare.report_id == report_id,
            )
        )
    ).scalar_one_or_none()
    if share is None:
        raise AppError("share_link_not_found", status.HTTP_404_NOT_FOUND)
    if share.revoked_at is not None:
        return
    share.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await audit_service.record_event(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="report.share_revoked",
        entity_type="report_share",
        entity_id=share.id,
        payload_diff={"report_id": str(report_id)},
    )


async def open_share(db: AsyncSession, token: str) -> dict:
    """Public endpoint helper. Increments open counter and returns view."""
    share = (
        await db.execute(
            select(RecruitmentReportShare).where(
                RecruitmentReportShare.token == token
            )
        )
    ).scalar_one_or_none()
    if share is None:
        raise AppError("share_link_not_found", status.HTTP_404_NOT_FOUND)
    if share.revoked_at is not None:
        raise AppError("share_link_revoked", status.HTTP_404_NOT_FOUND)
    if share.expires_at < datetime.now(timezone.utc):
        raise AppError("share_link_expired", status.HTTP_410_GONE)

    report = (
        await db.execute(
            select(ConsolidatedReport).where(
                ConsolidatedReport.id == share.report_id
            )
        )
    ).scalar_one_or_none()
    if report is None or report.status != "completed" or not report.file_id:
        raise AppError("share_report_unavailable", status.HTTP_404_NOT_FOUND)

    vacancy = (
        await db.execute(
            select(Vacancy).where(Vacancy.id == report.vacancy_id)
        )
    ).scalar_one_or_none()

    download_url: str | None = None
    file_row = (
        await db.execute(select(File).where(File.id == report.file_id))
    ).scalar_one_or_none()
    if file_row:
        from app.core.s3 import get_presigned_url

        download_url = get_presigned_url(file_row.path, expires_in=900)

    share.open_count = (share.open_count or 0) + 1
    share.last_opened_at = datetime.now(timezone.utc)
    await db.commit()

    await audit_service.record_event(
        db,
        tenant_id=share.tenant_id,
        user_id=None,
        action="report.share_opened",
        entity_type="report_share",
        entity_id=share.id,
        payload_diff={"open_count": share.open_count},
    )

    return {
        "report_id": report.id,
        "vacancy_title": vacancy.title if vacancy else None,
        "generated_at": report.completed_at,
        "expires_at": share.expires_at,
        "download_url": download_url,
    }
