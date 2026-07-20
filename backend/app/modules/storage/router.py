import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.storage import service

router = APIRouter(tags=["storage"])


@router.post("/files/upload", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    entity_type: str | None = Form(None),
    entity_id: uuid.UUID | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.upload(
        db, current_user.tenant_id, current_user.id, file, entity_type, entity_id
    )


@router.get("/files/{file_id}")
async def get_file(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_file(db, current_user.tenant_id, file_id)


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await service.delete(db, current_user.tenant_id, file_id)
