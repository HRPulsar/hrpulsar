import uuid

from fastapi import UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AppError
from app.core.s3 import delete_file, get_presigned_url, upload_file
from app.core.upload_validation import validate_upload
from app.modules.storage.models import File


async def upload(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    file: UploadFile,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    content_type_override: str | None = None,
) -> dict:
    data = await file.read()

    # Avatars are user-controlled and rendered inline in the browser, so they
    # must be raster images only — never PDFs or (worse) SVG/HTML. Everything
    # else goes through the general allowlist. In both cases the safe MIME and
    # extension are derived from the sniffed bytes, not the client's claim.
    safe_mime, ext = validate_upload(
        data=data,
        claimed_mime=content_type_override or file.content_type,
        max_bytes=settings.max_upload_mb * 1024 * 1024,
        images_only=(entity_type == "avatar"),
    )

    file_id = uuid.uuid4()
    path = f"{tenant_id}/{entity_type or 'general'}/{file_id}.{ext}"

    effective_type = safe_mime
    url = upload_file(data, path, effective_type)

    record = File(
        tenant_id=tenant_id,
        name=f"{file_id}.{ext}",
        original_name=file.filename or "unnamed",
        path=path,
        size=len(data),
        mime_type=effective_type,
        uploaded_by=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return {
        "id": record.id,
        "name": record.name,
        "original_name": record.original_name,
        "path": record.path,
        "size": record.size,
        "mime_type": record.mime_type,
        "url": url,
        "created_at": record.created_at,
    }


async def get_file(db: AsyncSession, tenant_id: uuid.UUID, file_id: uuid.UUID) -> dict:
    f = await db.get(File, file_id)
    if not f or f.tenant_id != tenant_id:
        raise AppError("storage_file_not_found", status.HTTP_404_NOT_FOUND)

    url = get_presigned_url(f.path)

    return {
        "id": f.id,
        "name": f.name,
        "original_name": f.original_name,
        "path": f.path,
        "size": f.size,
        "mime_type": f.mime_type,
        "url": url,
        "created_at": f.created_at,
    }


async def delete(db: AsyncSession, tenant_id: uuid.UUID, file_id: uuid.UUID) -> None:
    f = await db.get(File, file_id)
    if not f or f.tenant_id != tenant_id:
        raise AppError("storage_file_not_found", status.HTTP_404_NOT_FOUND)

    delete_file(f.path)
    await db.delete(f)
    await db.commit()
