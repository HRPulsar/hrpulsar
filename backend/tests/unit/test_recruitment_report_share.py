"""R4c — report sharing (FR-22, SCR-84)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from app.modules.recruitment import service, share_service
from app.modules.recruitment.models import (
    ConsolidatedReport,
    RecruitmentAuditLog,
    RecruitmentReportShare,
)
from app.modules.recruitment.schemas import VacancyCreate
from app.modules.storage.models import File
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _completed_report(
    db: AsyncSession, tenant, user, *, status: str = "completed"
) -> ConsolidatedReport:
    vac = await service.create_vacancy(
        db,
        tenant.id,
        user.id,
        VacancyCreate(title=f"Vac-{uuid.uuid4().hex[:4]}"),
    )
    file_row = File(
        tenant_id=tenant.id,
        name="report.xlsx",
        original_name="report.xlsx",
        path=f"reports/{uuid.uuid4().hex}.xlsx",
        size=1024,
        mime_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        uploaded_by=user.id,
        entity_type="recruitment.report",
    )
    db.add(file_row)
    await db.flush()
    report = ConsolidatedReport(
        tenant_id=tenant.id,
        vacancy_id=uuid.UUID(str(vac["id"])),
        sections=["vacancy_summary"],
        status=status,
        generated_by=user.id,
        file_id=file_row.id if status == "completed" else None,
        completed_at=datetime.now(timezone.utc) if status == "completed" else None,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


class TestReportShare:
    async def test_create_share_returns_token(
        self, db: AsyncSession, tenant, user
    ):
        report = await _completed_report(db, tenant, user)
        with patch("app.core.email.enqueue_email"):
            share = await share_service.create_share(
                db,
                tenant.id,
                user.id,
                report.id,
                recipients=["a@example.com"],
                expires_in_days=7,
                message="Have a look",
            )
        assert share["token"]
        assert share["expires_at"] > datetime.now(timezone.utc)
        assert share["recipients"] == ["a@example.com"]
        assert share["share_url"].endswith(share["token"])

    async def test_pending_report_cannot_be_shared(
        self, db: AsyncSession, tenant, user
    ):
        report = await _completed_report(db, tenant, user, status="pending")
        with pytest.raises(HTTPException) as exc:
            await share_service.create_share(
                db,
                tenant.id,
                user.id,
                report.id,
                recipients=[],
                expires_in_days=7,
                message=None,
            )
        assert exc.value.status_code == 409

    async def test_open_share_increments_counter(
        self, db: AsyncSession, tenant, user
    ):
        report = await _completed_report(db, tenant, user)
        with patch("app.core.email.enqueue_email"):
            share = await share_service.create_share(
                db,
                tenant.id,
                user.id,
                report.id,
                recipients=[],
                expires_in_days=7,
                message=None,
            )
        with patch(
            "app.core.s3.get_presigned_url",
            return_value="https://example/file.xlsx",
        ):
            view1 = await share_service.open_share(db, share["token"])
            view2 = await share_service.open_share(db, share["token"])

        assert view1["report_id"] == report.id
        assert view2["report_id"] == report.id

        row = (
            await db.execute(
                select(RecruitmentReportShare).where(
                    RecruitmentReportShare.id == share["id"]
                )
            )
        ).scalar_one()
        assert row.open_count == 2
        assert row.last_opened_at is not None

    async def test_expired_share_returns_410(
        self, db: AsyncSession, tenant, user
    ):
        report = await _completed_report(db, tenant, user)
        with patch("app.core.email.enqueue_email"):
            share = await share_service.create_share(
                db,
                tenant.id,
                user.id,
                report.id,
                recipients=[],
                expires_in_days=7,
                message=None,
            )
        # Force expiry.
        row = (
            await db.execute(
                select(RecruitmentReportShare).where(
                    RecruitmentReportShare.id == share["id"]
                )
            )
        ).scalar_one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await share_service.open_share(db, share["token"])
        assert exc.value.status_code == 410

    async def test_revoked_share_is_404(self, db: AsyncSession, tenant, user):
        report = await _completed_report(db, tenant, user)
        with patch("app.core.email.enqueue_email"):
            share = await share_service.create_share(
                db,
                tenant.id,
                user.id,
                report.id,
                recipients=[],
                expires_in_days=7,
                message=None,
            )
        await share_service.revoke_share(
            db, tenant.id, user.id, report.id, share["id"]
        )

        with pytest.raises(HTTPException) as exc:
            await share_service.open_share(db, share["token"])
        assert exc.value.status_code == 404

    async def test_audit_rows_written(
        self, db: AsyncSession, tenant, user
    ):
        report = await _completed_report(db, tenant, user)
        with patch("app.core.email.enqueue_email"):
            share = await share_service.create_share(
                db,
                tenant.id,
                user.id,
                report.id,
                recipients=["a@example.com"],
                expires_in_days=7,
                message=None,
            )
        with patch(
            "app.core.s3.get_presigned_url",
            return_value="https://example/file.xlsx",
        ):
            await share_service.open_share(db, share["token"])
        await share_service.revoke_share(
            db, tenant.id, user.id, report.id, share["id"]
        )

        actions = [
            row.action
            for row in (
                await db.execute(
                    select(RecruitmentAuditLog).where(
                        RecruitmentAuditLog.entity_id == uuid.UUID(str(share["id"]))
                    )
                )
            ).scalars().all()
        ]
        assert "report.shared" in actions
        assert "report.share_opened" in actions
        assert "report.share_revoked" in actions

    async def test_cross_tenant_share_isolation(
        self, db: AsyncSession, tenant, user
    ):
        report = await _completed_report(db, tenant, user)
        with patch("app.core.email.enqueue_email"):
            await share_service.create_share(
                db,
                tenant.id,
                user.id,
                report.id,
                recipients=[],
                expires_in_days=7,
                message=None,
            )

        other_tenant_id = uuid.uuid4()
        # list_shares with the wrong tenant returns 404 because the
        # report itself isn't visible to the foreign tenant.
        with pytest.raises(HTTPException) as exc:
            await share_service.list_shares(db, other_tenant_id, report.id)
        assert exc.value.status_code == 404


class TestShareUrl:
    """Fallback heuristic prefers ``app.`` origin over the first cors entry."""

    def test_frontend_url_wins(self, monkeypatch):
        from app.config import settings as app_settings
        from app.modules.recruitment import share_service as ss

        monkeypatch.setattr(app_settings, "frontend_url", "https://hub.example.com")
        url = ss._share_url("tok123")
        assert url == "https://hub.example.com/reports/share/tok123"

    def test_cors_app_subdomain_preferred(self, monkeypatch):
        from app.config import settings as app_settings
        from app.modules.recruitment import share_service as ss

        monkeypatch.setattr(app_settings, "frontend_url", "")
        monkeypatch.setattr(
            app_settings,
            "cors_origins",
            "https://hrpulsar.com,https://app.hrpulsar.com",
        )
        ss._SHARE_URL_WARNED = False
        url = ss._share_url("tok456")
        assert url == "https://app.hrpulsar.com/reports/share/tok456"

    def test_cors_first_origin_when_no_app_subdomain(self, monkeypatch):
        from app.config import settings as app_settings
        from app.modules.recruitment import share_service as ss

        monkeypatch.setattr(app_settings, "frontend_url", "")
        monkeypatch.setattr(app_settings, "cors_origins", "http://localhost:3100")
        ss._SHARE_URL_WARNED = False
        url = ss._share_url("tok789")
        assert url == "http://localhost:3100/reports/share/tok789"
