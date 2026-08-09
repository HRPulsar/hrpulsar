from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.ai import model_catalog_service, providers
from app.modules.ai_settings import service
from app.modules.ai_settings.schemas import (
    AISettingsRead,
    AISettingsUpdate,
    AllowedModelRead,
    EffortPresetRead,
    ProviderStatusRead,
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
    return await service.to_read_dict_async(db, row)


@router.patch("", response_model=AISettingsRead)
async def update_settings(
    patch: AISettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    row = await service.update(db, current_user.tenant_id, patch)
    return await service.to_read_dict_async(db, row)


@router.post("/reset", response_model=AISettingsRead)
async def reset_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    row = await service.reset(db, current_user.tenant_id)
    return await service.to_read_dict_async(db, row)


@router.get("/presets", response_model=list[EffortPresetRead])
async def get_presets(
    _: User = Depends(require_role("admin")),
):
    return service.list_presets()


@router.get("/models", response_model=list[AllowedModelRead])
async def get_allowed_models(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """Pickable models from the dynamic catalog (HRP-466).

    Tenants only ever see ``approved AND enabled`` rows — pending models
    awaiting platform-admin moderation stay invisible. A fresh install
    (empty catalog) is lazily seeded from the curated registry."""
    rows = await model_catalog_service.approved_models(db)
    if not rows:
        await model_catalog_service.seed_from_registry(db)
        rows = await model_catalog_service.approved_models(db)
    return model_catalog_service.to_read_dicts(rows)


@router.get("/providers", response_model=list[ProviderStatusRead])
async def get_provider_statuses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Which LLM providers this tenant can actually generate through
    (platform env key, tenant BYOK key, or a local OpenAI-compatible
    endpoint). The model selector on /settings/ai offers only these."""
    return await providers.configured_providers(db, current_user.tenant_id)
