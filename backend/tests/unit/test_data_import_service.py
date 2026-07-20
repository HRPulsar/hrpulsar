import io
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from app.modules.data_import import service
from fastapi import UploadFile
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession


def _make_excel(rows: list[list]) -> io.BytesIO:
    """Create an in-memory Excel file from rows."""
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _make_upload(buf: io.BytesIO, filename: str = "test.xlsx") -> UploadFile:
    return UploadFile(file=buf, filename=filename)


class TestStartImportAsync:
    """Tests for async start_import (queues Celery task)."""

    @patch("app.modules.data_import.tasks.run_import_task")
    async def test_start_import_returns_pending(
        self, mock_task, db: AsyncSession, tenant, user
    ):
        mock_task.apply_async = MagicMock()
        excel = _make_excel(
            [
                ["email", "first_name", "last_name", "position", "hire_date"],
                ["alice@test.com", "Alice", "Smith", "Engineer", date(2024, 1, 15)],
            ]
        )
        file = _make_upload(excel)
        result = await service.start_import(db, tenant.id, user.id, "employees", file)

        assert result["status"] == "pending"
        assert result["total_rows"] == 1
        assert result["processed_rows"] == 0
        mock_task.apply_async.assert_called_once()

    @patch("app.modules.data_import.tasks.run_import_task")
    async def test_start_import_queues_celery_task(
        self, mock_task, db: AsyncSession, tenant, user
    ):
        mock_task.apply_async = MagicMock()
        excel = _make_excel(
            [
                ["type", "title", "description"],
                ["grade", "Junior", "Entry level"],
                ["grade", "Middle", "Mid level"],
            ]
        )
        file = _make_upload(excel)
        result = await service.start_import(
            db, tenant.id, user.id, "dictionaries", file
        )

        assert result["status"] == "pending"
        assert result["total_rows"] == 2
        # Verify Celery task was called with correct args (via apply_async)
        kwargs = mock_task.apply_async.call_args.kwargs
        args = kwargs["args"]
        assert args[0] == str(result["id"])  # job_id
        assert args[1] == str(tenant.id)  # tenant_id
        assert args[3] == "dictionaries"  # import_type
        assert kwargs["headers"]["module"] == "data_import"
        assert kwargs["headers"]["action"] == "import_dictionaries"

    async def test_invalid_import_type(self, db: AsyncSession, tenant, user):
        excel = _make_excel([["a"], ["b"]])
        file = _make_upload(excel)

        with pytest.raises(Exception) as exc:
            await service.start_import(db, tenant.id, user.id, "invalid_type", file)
        assert "400" in str(exc.value.status_code)


class TestListJobs:
    @patch("app.modules.data_import.tasks.run_import_task")
    async def test_list_jobs(self, mock_task, db: AsyncSession, tenant, user):
        mock_task.apply_async = MagicMock()
        excel = _make_excel(
            [
                ["type", "title", "description"],
                ["grade", "Test", "Desc"],
            ]
        )
        await service.start_import(
            db, tenant.id, user.id, "dictionaries", _make_upload(excel)
        )

        items, total = await service.list_jobs(db, tenant.id)
        assert total >= 1
        assert items[0]["import_type"] == "dictionaries"
        assert items[0]["status"] == "pending"

    @patch("app.modules.data_import.tasks.run_import_task")
    async def test_list_jobs_pagination(
        self, mock_task, db: AsyncSession, tenant, user
    ):
        mock_task.apply_async = MagicMock()
        for i in range(3):
            excel = _make_excel([["type", "title"], ["grade", f"G{i}"]])
            await service.start_import(
                db, tenant.id, user.id, "dictionaries", _make_upload(excel)
            )

        items, total = await service.list_jobs(db, tenant.id, skip=0, limit=2)
        assert len(items) == 2
        assert total >= 3


class TestGetJob:
    @patch("app.modules.data_import.tasks.run_import_task")
    async def test_get_job(self, mock_task, db: AsyncSession, tenant, user):
        mock_task.apply_async = MagicMock()
        excel = _make_excel(
            [
                ["type", "title"],
                ["grade", "Senior"],
            ]
        )
        result = await service.start_import(
            db, tenant.id, user.id, "dictionaries", _make_upload(excel)
        )
        job = await service.get_job(db, tenant.id, result["id"])
        assert job["id"] == result["id"]
        assert job["status"] == "pending"

    async def test_get_job_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(Exception) as exc:
            await service.get_job(db, tenant.id, uuid.uuid4())
        assert "404" in str(exc.value.status_code)
