"""Tests for GF10: Company logo upload/delete."""

from io import BytesIO
from unittest.mock import patch

import pytest
from app.modules.company import service
from app.modules.company.models import Tenant
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

# Valid PNG signature so the upload survives the storage-layer image sniff
# (app.core.upload_validation) and company-service magic detection.
_PNG = b"\x89PNG\r\n\x1a\n"


def _make_upload(
    content: bytes = _PNG + b"logo-bytes",
    filename: str = "logo.png",
    content_type: str = "image/png",
) -> UploadFile:
    return UploadFile(
        file=BytesIO(content), filename=filename, headers={"content-type": content_type}
    )


class TestUploadLogo:
    @patch("app.modules.storage.service.upload_file")
    async def test_upload_logo(self, mock_s3, db: AsyncSession, tenant, user):
        mock_s3.return_value = "https://s3.example.com/logo.png"

        file = _make_upload()
        result = await service.upload_logo(db, tenant.id, user.id, file)

        assert result["logo_file_id"] is not None
        assert result["id"] == tenant.id

        # Verify tenant has logo set
        refreshed = await db.get(Tenant, tenant.id)
        assert refreshed.logo_file_id is not None

    @patch("app.modules.storage.service.upload_file")
    async def test_upload_logo_replaces_existing(
        self, mock_s3, db: AsyncSession, tenant, user
    ):
        mock_s3.return_value = "https://s3.example.com/logo.png"

        # Upload first logo
        file1 = _make_upload(_PNG + b"logo1", "logo1.png")
        result1 = await service.upload_logo(db, tenant.id, user.id, file1)
        first_logo_id = result1["logo_file_id"]
        assert first_logo_id is not None

        # Upload second logo (should replace)
        with patch("app.modules.storage.service.delete_file"):
            file2 = _make_upload(_PNG + b"logo2", "logo2.png")
            result2 = await service.upload_logo(db, tenant.id, user.id, file2)

        assert result2["logo_file_id"] is not None
        assert result2["logo_file_id"] != first_logo_id

    async def test_upload_logo_invalid_type(self, db: AsyncSession, tenant, user):
        file = _make_upload(b"not-an-image", "doc.pdf", "application/pdf")
        with pytest.raises(HTTPException) as exc:
            await service.upload_logo(db, tenant.id, user.id, file)
        assert exc.value.status_code == 400
        assert "Invalid file type" in exc.value.detail


class TestDeleteLogo:
    @patch("app.modules.storage.service.upload_file")
    async def test_delete_logo(self, mock_s3, db: AsyncSession, tenant, user):
        mock_s3.return_value = "https://s3.example.com/logo.png"

        # First upload a logo
        file = _make_upload()
        await service.upload_logo(db, tenant.id, user.id, file)

        refreshed = await db.get(Tenant, tenant.id)
        assert refreshed.logo_file_id is not None

        # Delete it
        with patch("app.modules.storage.service.delete_file"):
            result = await service.delete_logo(db, tenant.id)

        assert result["logo_file_id"] is None

        refreshed = await db.get(Tenant, tenant.id)
        assert refreshed.logo_file_id is None

    async def test_delete_logo_not_set(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc:
            await service.delete_logo(db, tenant.id)
        assert exc.value.status_code == 404


class TestCompanyProfileWithLogo:
    @patch("app.modules.storage.service.upload_file")
    async def test_profile_includes_logo(self, mock_s3, db: AsyncSession, tenant, user):
        mock_s3.return_value = "https://s3.example.com/logo.png"

        file = _make_upload()
        await service.upload_logo(db, tenant.id, user.id, file)

        with patch(
            "app.core.s3.get_presigned_url",
            return_value="https://s3.example.com/logo.png",
        ):
            profile = await service.get_company_profile(db, tenant.id)

        assert profile["logo_file_id"] is not None
        assert profile["logo_url"] == "https://s3.example.com/logo.png"

    async def test_profile_without_logo(self, db: AsyncSession, tenant):
        profile = await service.get_company_profile(db, tenant.id)
        assert profile["logo_file_id"] is None
        assert profile["logo_url"] is None
