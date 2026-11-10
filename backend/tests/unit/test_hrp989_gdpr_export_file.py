"""HRP-989: a completed GDPR export has a file to download.

The worker uploaded the JSON and wrote its ``files`` row, but copied the
row's id onto the export request before the flush that assigns it - every
export completed with ``file_id`` NULL: no download link, and the erasure
and the retention expiry, which find export files by ``file_id``, never
deleted them. Covers the path export task -> request with a link ->
download, and both deletions, for new exports and for ones already stored
without the link.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.config import settings
from app.modules.company.models import Tenant
from app.modules.recruitment import gdpr_service
from app.modules.recruitment.models import GDPRExportRequest
from app.modules.storage.models import File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_recruitment_gdpr import _make_candidate_with_data


@pytest.fixture
def bucket(monkeypatch) -> dict[str, bytes]:
    """S3 on, backed by a dict; presigned URLs name the key they sign."""
    store: dict[str, bytes] = {}
    monkeypatch.setattr(settings, "s3_endpoint", "http://fake-s3")

    def _upload(body: bytes, path: str, _content_type: str) -> str:
        store[path] = body
        return path

    def _delete(path: str) -> bool:
        store.pop(path, None)
        return True

    monkeypatch.setattr(gdpr_service, "upload_file", _upload)
    monkeypatch.setattr(gdpr_service, "s3_delete_file", _delete)
    monkeypatch.setattr(
        gdpr_service,
        "get_presigned_url",
        lambda path, expires_in: f"http://fake-s3/{path}?signed",
    )
    return store


async def _export(db: AsyncSession, tenant, user) -> tuple[uuid.UUID, uuid.UUID]:
    candidate = await _make_candidate_with_data(db, tenant, user, with_interview=False)
    cand_id = uuid.UUID(str(candidate["id"]))
    row = GDPRExportRequest(
        tenant_id=tenant.id,
        requested_by=user.id,
        subject_type="candidate",
        subject_id=cand_id,
        status="processing",
    )
    db.add(row)
    await db.commit()
    result = await gdpr_service._perform_gdpr_export(db, row.id)
    assert result["status"] == "completed"
    return cand_id, row.id


async def test_a_completed_export_links_its_file_and_downloads(
    auth_client, db: AsyncSession, tenant, user, bucket
) -> None:
    cand_id, request_id = await _export(db, tenant, user)

    row = await db.get(GDPRExportRequest, request_id)
    await db.refresh(row)
    assert row.file_id is not None
    file_row = await db.get(File, row.file_id)
    assert file_row.path in bucket

    resp = await auth_client.get(
        "/api/recruitment/gdpr-requests", params={"candidate_id": str(cand_id)}
    )
    assert resp.status_code == 200, resp.text
    [item] = resp.json()["items"]
    assert item["status"] == "completed"
    assert item["file_url"] == f"http://fake-s3/{file_row.path}?signed"
    # The link serves the subject's data.
    assert str(cand_id).encode() in bucket[file_row.path]


async def test_erasure_deletes_the_export_file(
    db: AsyncSession, tenant, user, bucket
) -> None:
    cand_id, request_id = await _export(db, tenant, user)
    assert len(bucket) == 1

    log_row = await gdpr_service.gdpr_erase(db, tenant.id, user.id, cand_id)

    assert log_row.affected["export_files"] == 1
    assert bucket == {}
    row = await db.get(GDPRExportRequest, request_id)
    assert row.file_id is None


async def _legacy_export(db: AsyncSession, tenant, user, bucket) -> tuple:
    """An export the bug stored: completed, file and blob in place, no link."""
    cand_id, request_id = await _export(db, tenant, user)
    row = await db.get(GDPRExportRequest, request_id)
    row.file_id = None
    await db.commit()
    return cand_id, request_id


async def test_erasure_finds_an_export_stored_without_its_link(
    db: AsyncSession, tenant, user, bucket
) -> None:
    cand_id, request_id = await _legacy_export(db, tenant, user, bucket)

    log_row = await gdpr_service.gdpr_erase(db, tenant.id, user.id, cand_id)

    assert log_row.affected["export_files"] == 1
    assert bucket == {}


async def test_expiry_finds_an_export_stored_without_its_link(
    db: AsyncSession, tenant, user, bucket
) -> None:
    _cand_id, request_id = await _legacy_export(db, tenant, user, bucket)
    row = await db.get(GDPRExportRequest, request_id)
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()

    expired = await gdpr_service._expire_export_files(db, datetime.now(UTC))

    assert expired == 1
    assert bucket == {}
    # Gone for good: the next sweep has nothing left to pick up.
    assert await gdpr_service._expire_export_files(db, datetime.now(UTC)) == 0


async def _listed(auth_client, cand_id: uuid.UUID) -> dict:
    resp = await auth_client.get(
        "/api/recruitment/gdpr-requests", params={"candidate_id": str(cand_id)}
    )
    assert resp.status_code == 200, resp.text
    [item] = resp.json()["items"]
    return item


async def test_an_export_stored_without_its_link_downloads_its_file(
    auth_client, db: AsyncSession, tenant, user, bucket
) -> None:
    """Exports QA already made before the fix get their download link."""
    cand_id, request_id = await _legacy_export(db, tenant, user, bucket)
    [path] = bucket

    item = await _listed(auth_client, cand_id)

    assert item["status"] == "completed"
    assert item["file_url"] == f"http://fake-s3/{path}?signed"


async def test_another_tenants_files_row_is_not_picked(
    auth_client, db: AsyncSession, tenant, user, bucket
) -> None:
    cand_id, request_id = await _legacy_export(db, tenant, user, bucket)
    other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
    db.add(other)
    await db.commit()
    file_row = (
        await db.execute(select(File).where(File.entity_id == request_id))
    ).scalar_one()
    file_row.tenant_id = other.id
    await db.commit()

    assert (await _listed(auth_client, cand_id))["file_url"] is None
