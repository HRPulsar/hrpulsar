"""Storage service when S3 says no (review §3).

Two halves of the same rule: a ``File`` row and the object behind it must
appear and disappear together. Before this, a refused upload still wrote
the row (and answered 201 with ``"url": null``), and a refused delete
still dropped the row, orphaning the bytes.

Both guards ask whether storage is configured at all: an install without
S3 keeps the documented metadata-only mode.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import pytest
from app.config import settings
from app.modules.storage import service as storage_service
from app.modules.storage.models import File
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _upload() -> UploadFile:
    return UploadFile(
        filename="test.png",
        file=BytesIO(b"\x89PNG\r\n\x1a\n" + b"payload-bytes"),
        headers={"content-type": "image/png"},
    )


async def _rows(db: AsyncSession, tenant_id) -> list[File]:
    result = await db.execute(select(File).where(File.tenant_id == tenant_id))
    return list(result.scalars().all())


@pytest.fixture
def s3_configured(monkeypatch):
    monkeypatch.setattr(settings, "s3_endpoint", "http://minio.test:9000")


class TestUploadFailure:
    async def test_refused_upload_leaves_no_row(
        self, db: AsyncSession, tenant, user, s3_configured
    ) -> None:
        before = len(await _rows(db, tenant.id))
        with (
            patch("app.modules.storage.service.upload_file", return_value=None),
            pytest.raises(HTTPException) as exc,
        ):
            await storage_service.upload(db, tenant.id, user.id, _upload())
        assert exc.value.status_code == 502
        assert len(await _rows(db, tenant.id)) == before

    async def test_upload_without_storage_stays_metadata_only(
        self, db: AsyncSession, tenant, user, monkeypatch
    ) -> None:
        """No S3 configured is not an error — it is the documented
        metadata-only mode (.env.example, "File Storage")."""
        monkeypatch.setattr(settings, "s3_endpoint", "")
        with patch("app.modules.storage.service.upload_file", return_value=None):
            result = await storage_service.upload(db, tenant.id, user.id, _upload())
        assert result["url"] is None

    async def test_successful_upload_returns_a_url(
        self, db: AsyncSession, tenant, user
    ) -> None:
        with patch(
            "app.modules.storage.service.upload_file",
            return_value="https://s3.example.com/test.png",
        ):
            result = await storage_service.upload(db, tenant.id, user.id, _upload())
        assert result["url"] == "https://s3.example.com/test.png"


class TestDeleteFailure:
    async def test_refused_delete_keeps_the_row(
        self, db: AsyncSession, tenant, user, s3_configured
    ) -> None:
        with patch(
            "app.modules.storage.service.upload_file",
            return_value="https://s3.example.com/test.png",
        ):
            uploaded = await storage_service.upload(db, tenant.id, user.id, _upload())

        with (
            patch("app.modules.storage.service.delete_file", return_value=False),
            pytest.raises(HTTPException) as exc,
        ):
            await storage_service.delete(db, tenant.id, uploaded["id"])
        assert exc.value.status_code == 502
        # The row is the only pointer to the key — it has to survive so the
        # delete can be retried instead of orphaning the object.
        assert await db.get(File, uploaded["id"]) is not None

        with patch("app.modules.storage.service.delete_file", return_value=True):
            await storage_service.delete(db, tenant.id, uploaded["id"])
        assert await db.get(File, uploaded["id"]) is None
