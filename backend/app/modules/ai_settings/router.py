from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.ai_settings import service
from app.modules.ai_settings.schemas import (
    AISettingsRead,
    AISettingsUpdate,
    AllowedModelRead,
    EffortPresetRead,
)
from app.modules.auth.dependencies import require_role
from app.modules.auth.models import User

router = APIRouter(prefix="/admin/ai-settings", tags=["ai-settings"])


@router.get("", response_model=AISettingsRead)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    row = await service.get_or_default(db, current_user.tenant_id)
    return service.to_read_dict(row)


@router.patch("", response_model=AISettingsRead)
async def update_settings(
    patch: AISettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    row = await service.update(db, current_user.tenant_id, patch)
    return service.to_read_dict(row)


@router.post("/reset", response_model=AISettingsRead)
async def reset_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    row = await service.reset(db, current_user.tenant_id)
    return service.to_read_dict(row)


@router.get("/presets", response_model=list[EffortPresetRead])
async def get_presets(
    _: User = Depends(require_role("admin")),
):
    return service.list_presets()


@router.get("/models", response_model=list[AllowedModelRead])
async def get_allowed_models(
    _: User = Depends(require_role("admin")),
):
    return service.list_allowed_models()
