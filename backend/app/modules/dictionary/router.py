import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.dictionary import service
from app.modules.dictionary.schemas import (
    DictionaryItemCreate,
    DictionaryItemRead,
    DictionaryItemUpdate,
    DictionaryItemUsageRead,
)

router = APIRouter(tags=["dictionaries"])


@router.get("/dictionaries/{item_type}", response_model=list[DictionaryItemRead])
async def list_items(
    item_type: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_items(db, current_user.tenant_id, item_type)


@router.post(
    "/dictionaries/{item_type}",
    response_model=DictionaryItemRead,
    status_code=201,
)
async def create_item(
    item_type: str,
    data: DictionaryItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.create_item(db, current_user.tenant_id, item_type, data)


@router.get("/dictionaries/items/{item_id}", response_model=DictionaryItemRead)
async def get_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_item(db, current_user.tenant_id, item_id)


@router.put("/dictionaries/items/{item_id}", response_model=DictionaryItemRead)
async def update_item(
    item_id: uuid.UUID,
    data: DictionaryItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.update_item(db, current_user.tenant_id, item_id, data)


@router.delete("/dictionaries/items/{item_id}", status_code=204)
async def delete_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_item(db, current_user.tenant_id, item_id)


@router.get(
    "/dictionaries/items/{item_id}/usage",
    response_model=DictionaryItemUsageRead,
)
async def get_item_usage(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HRP-103 redo: preview the live references that block delete so the
    confirm dialog can enumerate them before the operator commits."""
    return await service.get_item_usage(db, current_user.tenant_id, item_id)
