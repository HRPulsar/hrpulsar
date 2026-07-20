"""Unit tests for R4a — XLSX reports + report templates."""

from __future__ import annotations

import io
import uuid
from unittest.mock import patch

import pytest
from app.modules.recruitment import service
from app.modules.recruitment.models import ConsolidatedReport
from app.modules.recruitment.report_xlsx import render_report_xlsx
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    ReportGenerateRequest,
    ReportTemplateCreate,
    ReportTemplateUpdate,
    VacancyCreate,
)
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_vacancy(db: AsyncSession, tenant, user, title: str = "V"):
    vac = await service.create_vacancy(
        db,
        tenant.id,
        user.id,
        VacancyCreate(title=f"{title}-{uuid.uuid4().hex[:5]}"),
    )
    return vac


async def _make_candidate(db: AsyncSession, tenant, user):
    return await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name=f"Cand{uuid.uuid4().hex[:4]}",
            last_name=f"Last{uuid.uuid4().hex[:4]}",
            email=f"{uuid.uuid4().hex[:6]}@example.com",
        ),
    )


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TestReportTemplates:
    async def test_create_and_list(
        self, db: AsyncSession, tenant, user
    ) -> None:
        created = await service.create_report_template(
            db,
            tenant.id,
            ReportTemplateCreate(
                name="Default",
                sections=["vacancy_summary", "competence_profile"],
                is_default=True,
            ),
        )
        assert created["name"] == "Default"
        assert created["sections"] == [
            "vacancy_summary",
            "competence_profile",
        ]
        assert created["is_default"] is True
        assert created["is_active"] is True

        items = await service.list_report_templates(db, tenant.id)
        assert any(item["id"] == created["id"] for item in items)

    async def test_only_one_default_per_tenant(
        self, db: AsyncSession, tenant, user
    ) -> None:
        first = await service.create_report_template(
            db,
            tenant.id,
            ReportTemplateCreate(
                name="A", sections=["vacancy_summary"], is_default=True
            ),
        )
        second = await service.create_report_template(
            db,
            tenant.id,
            ReportTemplateCreate(
                name="B", sections=["vacancy_summary"], is_default=True
            ),
        )
        # The first one should be flipped off when the second one becomes default.
        items = {t["id"]: t for t in await service.list_report_templates(db, tenant.id)}
        assert items[second["id"]]["is_default"] is True
        assert items[first["id"]]["is_default"] is False

    async def test_update_template_filters_duplicate_sections(
        self, db: AsyncSession, tenant, user
    ) -> None:
        tpl = await service.create_report_template(
            db, tenant.id, ReportTemplateCreate(name="X", sections=["vacancy_summary"])
        )
        updated = await service.update_report_template(
            db,
            tenant.id,
            uuid.UUID(str(tpl["id"])),
            ReportTemplateUpdate(
                # Pydantic enforces the literal but a duplicate is allowed
                # in the request — service deduplicates and preserves order.
                sections=[
                    "interview_analysis",
                    "vacancy_summary",
                    "interview_analysis",
                ]
            ),
        )
        assert updated["sections"] == ["interview_analysis", "vacancy_summary"]

    async def test_delete_template(
        self, db: AsyncSession, tenant, user
    ) -> None:
        tpl = await service.create_report_template(
            db, tenant.id, ReportTemplateCreate(name="Y", sections=["vacancy_summary"])
        )
        await service.delete_report_template(
            db, tenant.id, uuid.UUID(str(tpl["id"]))
        )
        items = await service.list_report_templates(db, tenant.id)
        assert all(item["id"] != tpl["id"] for item in items)

    async def test_update_unknown_template_404(
        self, db: AsyncSession, tenant, user
    ) -> None:
        with pytest.raises(HTTPException) as exc:
            await service.update_report_template(
                db, tenant.id, uuid.uuid4(), ReportTemplateUpdate(name="z")
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Enqueue / list / get / delete
# ---------------------------------------------------------------------------


class TestReportEnqueue:
    async def test_enqueue_creates_pending_export_and_dispatches_task(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vac = await _make_vacancy(db, tenant, user)

        with patch(
            "app.modules.recruitment.tasks.generate_report_task.delay"
        ) as mock_delay:
            mock_delay.return_value.id = "fake-task-id"
            result = await service.enqueue_report(
                db,
                tenant.id,
                user.id,
                uuid.UUID(str(vac["id"])),
                ReportGenerateRequest(sections=["vacancy_summary"]),
            )

        assert result["task_id"] == "fake-task-id"
        export = (
            await db.execute(
                select(ConsolidatedReport).where(
                    ConsolidatedReport.id == result["export_id"]
                )
            )
        ).scalar_one()
        assert export.status == "pending"
        assert export.sections == ["vacancy_summary"]
        assert export.generated_by == user.id
        mock_delay.assert_called_once_with(
            str(result["export_id"]), str(tenant.id)
        )

    async def test_enqueue_uses_default_sections_when_none_given(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vac = await _make_vacancy(db, tenant, user)
        with patch(
            "app.modules.recruitment.tasks.generate_report_task.delay"
        ) as mock_delay:
            mock_delay.return_value.id = "tid"
            result = await service.enqueue_report(
                db,
                tenant.id,
                user.id,
                uuid.UUID(str(vac["id"])),
                ReportGenerateRequest(),
            )
        export = (
            await db.execute(
                select(ConsolidatedReport).where(
                    ConsolidatedReport.id == result["export_id"]
                )
            )
        ).scalar_one()
        assert "vacancy_summary" in (export.sections or [])
        assert "comparison_grid" in (export.sections or [])

    async def test_enqueue_unknown_vacancy_returns_404(
        self, db: AsyncSession, tenant, user
    ) -> None:
        with pytest.raises(HTTPException) as exc:
            await service.enqueue_report(
                db,
                tenant.id,
                user.id,
                uuid.uuid4(),
                ReportGenerateRequest(),
            )
        assert exc.value.status_code == 404

    async def test_enqueue_inactive_template_returns_409(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vac = await _make_vacancy(db, tenant, user)
        tpl = await service.create_report_template(
            db,
            tenant.id,
            ReportTemplateCreate(
                name="Off",
                sections=["vacancy_summary"],
                is_active=False,
            ),
        )
        with pytest.raises(HTTPException) as exc:
            await service.enqueue_report(
                db,
                tenant.id,
                user.id,
                uuid.UUID(str(vac["id"])),
                ReportGenerateRequest(template_id=uuid.UUID(str(tpl["id"]))),
            )
        assert exc.value.status_code == 409


class TestReportListAndGet:
    async def test_list_and_get(self, db: AsyncSession, tenant, user) -> None:
        vac = await _make_vacancy(db, tenant, user)
        with patch(
            "app.modules.recruitment.tasks.generate_report_task.delay"
        ) as mock_delay:
            mock_delay.return_value.id = "tid"
            res = await service.enqueue_report(
                db,
                tenant.id,
                user.id,
                uuid.UUID(str(vac["id"])),
                ReportGenerateRequest(sections=["vacancy_summary"]),
            )

        items, total = await service.list_reports(
            db, tenant.id, vacancy_id=uuid.UUID(str(vac["id"]))
        )
        assert total == 1
        assert items[0]["status"] == "pending"
        assert items[0]["sections"] == ["vacancy_summary"]
        assert items[0]["requested_by_name"]

        single = await service.get_report(
            db, tenant.id, uuid.UUID(str(res["export_id"]))
        )
        assert single["id"] == res["export_id"]
        assert single["download_url"] is None  # still pending

    async def test_get_unknown_returns_404(
        self, db: AsyncSession, tenant
    ) -> None:
        with pytest.raises(HTTPException) as exc:
            await service.get_report(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404

    async def test_cross_tenant_access_returns_404(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vac = await _make_vacancy(db, tenant, user)
        with patch(
            "app.modules.recruitment.tasks.generate_report_task.delay"
        ) as mock_delay:
            mock_delay.return_value.id = "tid"
            res = await service.enqueue_report(
                db,
                tenant.id,
                user.id,
                uuid.UUID(str(vac["id"])),
                ReportGenerateRequest(),
            )
        other_tenant_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            await service.get_report(
                db, other_tenant_id, uuid.UUID(str(res["export_id"]))
            )
        assert exc.value.status_code == 404

    async def test_delete_report_clears_row(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vac = await _make_vacancy(db, tenant, user)
        with patch(
            "app.modules.recruitment.tasks.generate_report_task.delay"
        ) as mock_delay:
            mock_delay.return_value.id = "tid"
            res = await service.enqueue_report(
                db,
                tenant.id,
                user.id,
                uuid.UUID(str(vac["id"])),
                ReportGenerateRequest(),
            )
        await service.delete_report(
            db, tenant.id, uuid.UUID(str(res["export_id"]))
        )
        items, total = await service.list_reports(
            db, tenant.id, vacancy_id=uuid.UUID(str(vac["id"]))
        )
        assert total == 0


# ---------------------------------------------------------------------------
# XLSX renderer
# ---------------------------------------------------------------------------


class TestReportXlsxRenderer:
    def _vacancy_payload(self) -> dict:
        return {
            "title": "Senior Backend Engineer",
            "status": "open",
            "specialization_title": "Engineering",
            "grade_title": "Senior",
            "division_name": "Platform",
            "location": "Remote",
            "employment_type": "full_time",
            "salary_min": 100000,
            "salary_max": 140000,
            "salary_currency": "USD",
            "owner_name": "Alice Recruiter",
            "created_at": "2026-05-09T10:00:00",
            "description": "Hires only",
        }

    def test_render_emits_four_sheet_layout(self) -> None:
        """HRP-268 — always 4 sheets: Summary, Matrix, one Detail per
        candidate, and the Incomplete-data tail. Recruiter audience
        keeps the raw process-findings text on the Detail sheet."""
        cand_ids = [uuid.uuid4(), uuid.uuid4()]
        summary_rows = [
            {
                "candidate_name": "John Doe",
                "profile_summary": "10y backend, async stack",
                "manager_score_text": "8/10 (80%)",
                "ai_score_text": "9/10 (90%)",
                "data_readiness": "Complete",
                "recommendation": "Recommended",
            },
            {
                "candidate_name": "Mary Smith",
                "profile_summary": "5y Python + DS",
                "manager_score_text": "6/10 (60%)",
                "ai_score_text": "—",
                "data_readiness": "AI missing",
                "recommendation": "Additional check",
            },
        ]
        matrix = {
            "candidates": [
                {"id": cand_ids[0], "name": "John Doe"},
                {"id": cand_ids[1], "name": "Mary Smith"},
            ],
            "competences": [
                {
                    "id": uuid.uuid4(),
                    "name": "Python",
                    "group": "Hard",
                    "criticality": "critical",
                    "cells": [
                        {
                            "candidate_id": cand_ids[0],
                            "manager_score": 4.0,
                            "ai_score": 4.5,
                            "ai_status": "ready",
                            "divergence": False,
                        },
                        {
                            "candidate_id": cand_ids[1],
                            "manager_score": 3.0,
                            "ai_score": None,
                            "ai_status": "missing",
                            "divergence": False,
                        },
                    ],
                },
            ],
            "max_score": 5.0,
        }
        details = [
            {
                "candidate_name": "John Doe",
                "position": "Senior",
                "status": "interview",
                "resume_summary": "Worked on async services",
                "scores": [
                    {
                        "competence_name": "Python",
                        "manager_score": 4.0,
                        "ai_score": 4.5,
                        "citations": ["I built async services"],
                        "reasoning": "Strong async background",
                    }
                ],
                "blind_spots": [],
                "process_findings": [
                    {
                        "finding_type": "leading_question",
                        "severity": "low",
                        "description": "Leading question on architecture.",
                        "positive_reframe": "Try open-ended architecture probe.",
                    }
                ],
                "red_flags": [],
                "verdict": {"verdict_summary": "Strong"},
            }
        ]
        incomplete = [
            {
                "candidate_name": "Mary Smith",
                "missing": "AI analysis missing",
                "action": "Launch the AI analysis (resume-only or full).",
            }
        ]

        xlsx_bytes = render_report_xlsx(
            vacancy=self._vacancy_payload(),
            summary_rows=summary_rows,
            matrix=matrix,
            details=details,
            incomplete=incomplete,
            branding={"tenant_name": "Acme"},
        )
        wb = load_workbook(io.BytesIO(xlsx_bytes))
        assert wb.sheetnames == [
            "Summary",
            "Matrix",
            "Detail · John Doe",
            "Incomplete data",
        ]

        ws_summary = wb["Summary"]
        # Header row sits at row 4 — title + subtitle take rows 1-2.
        assert ws_summary.cell(row=4, column=1).value == "Candidate"
        assert ws_summary.cell(row=5, column=1).value == "John Doe"

        ws_matrix = wb["Matrix"]
        # Total row carries a SUM formula on each Manager / AI column.
        total_row = ws_matrix.max_row
        manager_total = ws_matrix.cell(row=total_row, column=4).value
        assert isinstance(manager_total, str) and manager_total.startswith("=SUM(")

        ws_detail = wb["Detail · John Doe"]
        flat = [
            ws_detail.cell(row=r, column=1).value
            for r in range(1, ws_detail.max_row + 1)
        ]
        # Recruiter audience keeps the raw process-findings header.
        assert "Process findings" in flat

        ws_incomplete = wb["Incomplete data"]
        assert ws_incomplete.cell(row=4, column=1).value == "Mary Smith"

    def test_render_hides_process_findings_for_hiring_manager(self) -> None:
        """Hiring-manager audience swaps the raw process-findings
        section for a positive reframe of the same payload."""
        details = [
            {
                "candidate_name": "John Doe",
                "scores": [],
                "process_findings": [
                    {
                        "finding_type": "leading_question",
                        "severity": "low",
                        "description": "Leading question on architecture.",
                        "positive_reframe": "Try open-ended architecture probe.",
                    }
                ],
            }
        ]
        xlsx_bytes = render_report_xlsx(
            vacancy=self._vacancy_payload(),
            summary_rows=[],
            matrix={"candidates": [], "competences": []},
            details=details,
            audience="hiring_manager",
        )
        wb = load_workbook(io.BytesIO(xlsx_bytes))
        ws_detail = wb["Detail · John Doe"]
        flat = [
            ws_detail.cell(row=r, column=1).value
            for r in range(1, ws_detail.max_row + 1)
        ]
        # The HM-side header replaces "Process findings" with a neutral
        # "Recommendations for the next interview" title.
        assert "Recommendations for the next interview" in flat
        assert "Process findings" not in flat
        # Raw process-findings description must NOT leak into the
        # workbook for the HM audience — only the reframe.
        sheet_dump = " ".join(
            str(ws_detail.cell(row=r, column=c).value or "")
            for r in range(1, ws_detail.max_row + 1)
            for c in range(1, ws_detail.max_column + 1)
        )
        assert "Leading question on architecture" not in sheet_dump
        assert "Try open-ended architecture probe" in sheet_dump

    def test_render_emits_incomplete_sheet_even_when_empty(self) -> None:
        xlsx_bytes = render_report_xlsx(
            vacancy={"title": "x"},
            summary_rows=[],
            matrix={"candidates": [], "competences": []},
            details=[],
            incomplete=[],
        )
        wb = load_workbook(io.BytesIO(xlsx_bytes))
        assert wb.sheetnames == ["Summary", "Matrix", "Incomplete data"]
        ws = wb["Incomplete data"]
        assert "All candidates have complete data" in str(
            ws.cell(row=4, column=1).value
        )


# ---------------------------------------------------------------------------
# Celery task end-to-end (with mocked S3)
# ---------------------------------------------------------------------------


class TestGenerateReportTask:
    async def test_task_writes_xlsx_and_marks_completed(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        # The Celery task spins up its own *sync* SQLAlchemy engine via
        # ``settings.database_url``. In tests we run against
        # ``hrpulsar_test`` (see tests/conftest.py), so we point the task
        # at the same DB before triggering it; otherwise the export row
        # written via ``enqueue_report`` is invisible to the worker.
        from app.config import settings as app_settings

        from tests.conftest import TEST_DB_URL

        monkeypatch.setattr(app_settings, "database_url", TEST_DB_URL)

        from app.modules.recruitment.tasks import generate_report_task

        vac = await _make_vacancy(db, tenant, user, title="ReportVac")
        cand = await _make_candidate(db, tenant, user)
        await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=uuid.UUID(str(cand["id"])),
                vacancy_id=uuid.UUID(str(vac["id"])),
            ),
        )
        with patch(
            "app.modules.recruitment.tasks.generate_report_task.delay"
        ) as mock_delay:
            mock_delay.return_value.id = "tid"
            res = await service.enqueue_report(
                db,
                tenant.id,
                user.id,
                uuid.UUID(str(vac["id"])),
                ReportGenerateRequest(
                    sections=["vacancy_summary", "candidates_summary"],
                ),
            )
        export_id = res["export_id"]
        # Force the test session to flush so the sync engine sees the row.
        await db.commit()

        captured: dict[str, bytes] = {}

        def _fake_upload(data: bytes, path: str, content_type: str) -> str:
            captured["bytes"] = data
            captured["path"] = path
            return f"http://example/{path}"

        # Patch the symbol the task imports lazily.
        monkeypatch.setattr(
            "app.core.s3.upload_file", _fake_upload, raising=True
        )
        monkeypatch.setattr(
            "app.core.s3.get_s3_client", lambda: None, raising=True
        )

        # Run the task synchronously (bypass the broker).
        result = generate_report_task.run(str(export_id), str(tenant.id))
        assert result["status"] == "completed", result

        # Re-read via the async session (force a fresh round-trip so we do
        # not see a cached pre-task object).
        await db.commit()
        await db.close()
        export = (
            await db.execute(
                select(ConsolidatedReport).where(
                    ConsolidatedReport.id == export_id
                )
            )
        ).scalar_one()
        assert export.status == "completed"
        assert export.file_id is not None
        assert export.completed_at is not None

        # The bytes must be a real XLSX (parsable by openpyxl). HRP-268
        # always emits the four canonical sheets — Summary / Matrix /
        # (Detail per candidate when there are any) / Incomplete data.
        wb = load_workbook(io.BytesIO(captured["bytes"]))
        assert wb.sheetnames[0] == "Summary"
        assert wb.sheetnames[1] == "Matrix"
        assert "Incomplete data" in wb.sheetnames

    async def test_task_marks_failed_when_upload_returns_none(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        from app.config import settings as app_settings

        from tests.conftest import TEST_DB_URL

        monkeypatch.setattr(app_settings, "database_url", TEST_DB_URL)

        from app.modules.recruitment.tasks import generate_report_task

        vac = await _make_vacancy(db, tenant, user)
        with patch(
            "app.modules.recruitment.tasks.generate_report_task.delay"
        ) as mock_delay:
            mock_delay.return_value.id = "tid"
            res = await service.enqueue_report(
                db,
                tenant.id,
                user.id,
                uuid.UUID(str(vac["id"])),
                ReportGenerateRequest(),
            )
        await db.commit()

        monkeypatch.setattr(
            "app.core.s3.upload_file", lambda *a, **k: None, raising=True
        )
        monkeypatch.setattr(
            "app.core.s3.get_s3_client", lambda: None, raising=True
        )

        result = generate_report_task.run(str(res["export_id"]), str(tenant.id))
        assert result["status"] == "failed", result

        await db.commit()
        await db.close()
        export = (
            await db.execute(
                select(ConsolidatedReport).where(
                    ConsolidatedReport.id == res["export_id"]
                )
            )
        ).scalar_one()
        assert export.status == "failed"
        assert "storage" in (export.error or "").lower()

    async def test_task_marks_failed_when_requesting_user_is_gone(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        # ConsolidatedReport.generated_by has ON DELETE SET NULL so a
        # deleted user leaves the export with NULL. files.uploaded_by is
        # FK users.id NOT NULL — the worker must fail-fast with a clear
        # error instead of either crashing inside the FK check or writing
        # a wrong UUID into uploaded_by (regression for a bug found in
        # review).
        from app.config import settings as app_settings

        from tests.conftest import TEST_DB_URL

        monkeypatch.setattr(app_settings, "database_url", TEST_DB_URL)

        from app.modules.recruitment.tasks import generate_report_task

        vac = await _make_vacancy(db, tenant, user)
        with patch(
            "app.modules.recruitment.tasks.generate_report_task.delay"
        ) as mock_delay:
            mock_delay.return_value.id = "tid"
            res = await service.enqueue_report(
                db,
                tenant.id,
                user.id,
                uuid.UUID(str(vac["id"])),
                ReportGenerateRequest(sections=["vacancy_summary"]),
            )
        # Simulate the user being deleted between enqueue and worker run.
        export = (
            await db.execute(
                select(ConsolidatedReport).where(
                    ConsolidatedReport.id == res["export_id"]
                )
            )
        ).scalar_one()
        export.generated_by = None
        await db.commit()
        await db.close()

        # Upload should never be reached — fail-fast happens before it.
        called: dict[str, bool] = {}

        def _should_not_be_called(*_args, **_kwargs):
            called["upload"] = True
            return "http://example/x"

        monkeypatch.setattr(
            "app.core.s3.upload_file", _should_not_be_called, raising=True
        )

        result = generate_report_task.run(
            str(res["export_id"]), str(tenant.id)
        )
        assert result["status"] == "failed"
        assert "user" in result["error"].lower()
        assert "upload" not in called

        await db.commit()
        export_after = (
            await db.execute(
                select(ConsolidatedReport).where(
                    ConsolidatedReport.id == res["export_id"]
                )
            )
        ).scalar_one()
        assert export_after.status == "failed"
        assert export_after.file_id is None


# ---------------------------------------------------------------------------
# R4d — Inline XLSX preview (FR-23 / SCR-83)
# ---------------------------------------------------------------------------


class TestReportPreview:
    """``GET /recruitment/reports/{id}/preview`` returns every sheet as JSON."""

    @staticmethod
    async def _seed_completed_report(db, tenant, user):
        from app.modules.recruitment.models import ConsolidatedReport
        from app.modules.storage.models import File

        vac = await _make_vacancy(db, tenant, user)
        file_row = File(
            tenant_id=tenant.id,
            name="report.xlsx",
            original_name="report.xlsx",
            path=f"{tenant.id}/reports/{uuid.uuid4()}.xlsx",
            size=1024,
            mime_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            uploaded_by=user.id,
            entity_type="report",
            entity_id=uuid.uuid4(),
        )
        db.add(file_row)
        await db.flush()
        export = ConsolidatedReport(
            tenant_id=tenant.id,
            vacancy_id=uuid.UUID(str(vac["id"])),
            sections=["vacancy_summary"],
            status="completed",
            generated_by=user.id,
            file_id=file_row.id,
        )
        db.add(export)
        await db.commit()
        await db.refresh(export)
        await db.refresh(file_row)
        return export, file_row

    async def test_preview_returns_sheets_when_xlsx_is_readable(
        self, db: AsyncSession, tenant, user, monkeypatch
    ):
        from openpyxl import Workbook

        export, file_row = await self._seed_completed_report(db, tenant, user)

        wb = Workbook()
        ws = wb.active
        ws.title = "Summary"
        ws.append(["Header", "Value"])
        ws.append(["Vacancy", "Senior Python"])
        ws.append(["Candidates", 3])
        wb.create_sheet("Notes").append(["x"])
        buf = io.BytesIO()
        wb.save(buf)
        xlsx_bytes = buf.getvalue()

        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        class _Client:
            def get_object(self, **kwargs):
                return {"Body": _Body(xlsx_bytes)}

        monkeypatch.setattr(
            "app.core.s3.get_s3_client", lambda: _Client()
        )
        # Force a Redis miss + skip cache write so the test does not
        # depend on a running Redis.
        monkeypatch.setattr(
            "redis.asyncio.from_url",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no redis")),
        )

        result = await service.get_report_preview(db, tenant.id, export.id)
        assert result["export_id"] == str(export.id)
        names = [s["name"] for s in result["sheets"]]
        assert "Summary" in names and "Notes" in names
        summary = next(s for s in result["sheets"] if s["name"] == "Summary")
        assert summary["cells"][0] == ["Header", "Value"]
        assert summary["cells"][1] == ["Vacancy", "Senior Python"]
        assert summary["cells"][2] == ["Candidates", 3]
        assert result["truncated"] is False

    async def test_preview_409_when_report_not_completed(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.recruitment.models import ConsolidatedReport

        vac = await _make_vacancy(db, tenant, user)
        export = ConsolidatedReport(
            tenant_id=tenant.id,
            vacancy_id=uuid.UUID(str(vac["id"])),
            sections=["vacancy_summary"],
            status="processing",
            generated_by=user.id,
        )
        db.add(export)
        await db.commit()
        await db.refresh(export)

        with pytest.raises(HTTPException) as exc:
            await service.get_report_preview(db, tenant.id, export.id)
        assert exc.value.status_code == 409

    async def test_preview_404_when_export_missing(
        self, db: AsyncSession, tenant
    ):
        with pytest.raises(HTTPException) as exc:
            await service.get_report_preview(db, tenant.id, uuid.uuid4())
        assert exc.value.status_code == 404
