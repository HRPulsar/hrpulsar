import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import User
from app.modules.competence import ai_materials, material_overrides, service
from app.modules.competence.models import CompetenceTreeAuditLog
from app.modules.competence.schemas import (
    CompetenceBulkCreate,
    CompetenceCreate,
    CompetenceDetail,
    CompetenceGroupCreate,
    CompetenceGroupRead,
    CompetenceGroupTree,
    CompetenceGroupUpdate,
    CompetenceRead,
    CompetenceTreeAuditLogRead,
    CompetenceUpdate,
    IndicatorCreate,
    IndicatorRead,
    IndicatorUpdate,
    MaterialCreate,
    MaterialInContext,
    MaterialOverrideCreate,
    MaterialOverrideRead,
    MaterialRead,
    MaterialUpdate,
    SkillLevelCreate,
    SkillLevelRead,
    SkillLevelUpdate,
)
from app.modules.competence.usage import (
    check_competence_usage,
    check_group_usage,
    check_indicator_usage,
    check_material_usage,
)

router = APIRouter(tags=["competences"])


# --- Tree ---


@router.get("/competence-tree", response_model=list[CompetenceGroupTree])
async def get_competence_tree(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_competence_tree(db, current_user.tenant_id)


# --- Groups: CRUD ---


@router.post("/competence-groups", response_model=CompetenceGroupRead, status_code=201)
async def create_group(
    data: CompetenceGroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_group(
        db, current_user.tenant_id, data, actor_id=current_user.id
    )


@router.put("/competence-groups/{group_id}", response_model=CompetenceGroupRead)
async def update_group(
    group_id: uuid.UUID,
    data: CompetenceGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_group(
        db, current_user.tenant_id, group_id, data, actor_id=current_user.id
    )


@router.delete("/competence-groups/{group_id}", status_code=204)
async def delete_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_group(
        db, current_user.tenant_id, group_id, actor_id=current_user.id
    )


# --- Groups: usage / activate / deactivate / move ---


@router.get("/competence-groups/{group_id}/usage")
async def get_group_usage(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    usage = await check_group_usage(db, group_id)
    return {
        "matrix": usage.matrix,
        "employee_card": usage.employee_card,
        "assessment": usage.assessment,
        "idp": usage.idp,
        "talent_market": usage.talent_market,
        "is_used": usage.is_used,
    }


@router.patch(
    "/competence-groups/{group_id}/activate", response_model=CompetenceGroupRead
)
async def activate_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.activate_group(
        db, current_user.tenant_id, group_id, actor_id=current_user.id
    )


@router.patch(
    "/competence-groups/{group_id}/deactivate", response_model=CompetenceGroupRead
)
async def deactivate_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.deactivate_group(
        db, current_user.tenant_id, group_id, actor_id=current_user.id
    )


@router.post("/competence-groups/{group_id}/move", response_model=CompetenceGroupRead)
async def move_group(
    group_id: uuid.UUID,
    new_parent_id: uuid.UUID | None = Body(None),
    new_sort_index: int = Body(0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.move_group(
        db,
        current_user.tenant_id,
        group_id,
        new_parent_id,
        new_sort_index,
        actor_id=current_user.id,
    )


# --- Competences: CRUD ---


@router.post("/competences", response_model=CompetenceRead, status_code=201)
async def create_competence(
    data: CompetenceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.create_competence(
        db, current_user.tenant_id, data, actor_id=current_user.id
    )


@router.post(
    "/competence-groups/{group_id}/competences/bulk",
    response_model=list[CompetenceRead],
    status_code=201,
)
async def bulk_create_competences(
    group_id: uuid.UUID,
    data: CompetenceBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """HRP-108: add several competences to a group in one shot."""
    return await service.bulk_create_competences(
        db, current_user.tenant_id, group_id, data, actor_id=current_user.id
    )


@router.get("/competences/{competence_id}", response_model=CompetenceDetail)
async def get_competence(
    competence_id: uuid.UUID,
    skill_level_id: uuid.UUID | None = Query(
        None,
        description=(
            "HRP-43: when set, return only indicators/materials whose skill "
            "level has sort_index ≤ the requested level (i.e. the chosen "
            "level and every level below it)."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_competence_detail(
        db,
        current_user.tenant_id,
        competence_id,
        skill_level_id=skill_level_id,
    )


@router.put("/competences/{competence_id}", response_model=CompetenceRead)
async def update_competence(
    competence_id: uuid.UUID,
    data: CompetenceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.update_competence(
        db, current_user.tenant_id, competence_id, data, actor_id=current_user.id
    )


@router.delete("/competences/{competence_id}", status_code=204)
async def delete_competence(
    competence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_competence(
        db, current_user.tenant_id, competence_id, actor_id=current_user.id
    )


# --- Competences: usage / publish / activate / move ---


@router.get("/competences/{competence_id}/usage")
async def get_competence_usage(
    competence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    usage = await check_competence_usage(db, competence_id)
    return {
        "matrix": usage.matrix,
        "employee_card": usage.employee_card,
        "assessment": usage.assessment,
        "idp": usage.idp,
        "talent_market": usage.talent_market,
        "is_used": usage.is_used,
    }


@router.post("/competences/{competence_id}/publish", response_model=CompetenceRead)
async def publish_competence(
    competence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.publish_competence(
        db, current_user.tenant_id, competence_id, actor_id=current_user.id
    )


@router.post("/competences/{competence_id}/unpublish", response_model=CompetenceRead)
async def unpublish_competence(
    competence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.unpublish_competence(
        db, current_user.tenant_id, competence_id, actor_id=current_user.id
    )


@router.patch("/competences/{competence_id}/activate", response_model=CompetenceRead)
async def activate_competence(
    competence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.activate_competence(
        db, current_user.tenant_id, competence_id, actor_id=current_user.id
    )


@router.patch("/competences/{competence_id}/deactivate", response_model=CompetenceRead)
async def deactivate_competence(
    competence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.deactivate_competence(
        db, current_user.tenant_id, competence_id, actor_id=current_user.id
    )


@router.post("/competences/{competence_id}/move", response_model=CompetenceRead)
async def move_competence(
    competence_id: uuid.UUID,
    new_group_id: uuid.UUID = Body(..., embed=True),
    new_sort_index: int = Body(0, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await service.move_competence(
        db,
        current_user.tenant_id,
        competence_id,
        new_group_id,
        new_sort_index,
        actor_id=current_user.id,
    )


# --- Skill Levels ---


@router.get("/skill-levels", response_model=list[SkillLevelRead])
async def list_skill_levels(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_skill_levels(db, current_user.tenant_id)


@router.post("/skill-levels", response_model=SkillLevelRead, status_code=201)
async def create_skill_level(
    data: SkillLevelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.create_skill_level(
        db,
        current_user.tenant_id,
        title=data.title,
        sort_index=data.sort_index,
        i18n_key=data.i18n_key,
        actor_id=current_user.id,
    )


@router.patch("/skill-levels/{skill_level_id}", response_model=SkillLevelRead)
async def update_skill_level(
    skill_level_id: uuid.UUID,
    data: SkillLevelUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.update_skill_level(
        db,
        current_user.tenant_id,
        skill_level_id,
        title=data.title,
        sort_index=data.sort_index,
        i18n_key=data.i18n_key,
        is_active=data.is_active,
        actor_id=current_user.id,
    )


@router.delete("/skill-levels/{skill_level_id}", status_code=204)
async def delete_skill_level(
    skill_level_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_skill_level(
        db, current_user.tenant_id, skill_level_id, actor_id=current_user.id
    )


# --- Indicators ---


def _serialize_indicator(ind) -> dict:
    return {
        **{
            k: getattr(ind, k)
            for k in (
                "id",
                "title",
                "weight",
                "sort_index",
                "skill_level_id",
                "competence_id",
                "is_active",
                "tenant_id",
                "created_at",
            )
        },
        "skill_level_title": ind.skill_level.title if ind.skill_level else None,
    }


@router.post(
    "/competences/{competence_id}/indicators",
    response_model=IndicatorRead,
    status_code=201,
)
async def create_indicator(
    competence_id: uuid.UUID,
    data: IndicatorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    ind = await service.create_indicator(
        db, current_user.tenant_id, competence_id, data, actor_id=current_user.id
    )
    return _serialize_indicator(ind)


class IndicatorBulkCreate(BaseModel):
    """HRP-49: payload for ``POST /competences/{id}/indicators/bulk``.

    Used by the inline multi-line entry in the indicators editor — one
    line per indicator title, all under the same skill level.
    """

    indicators: list[IndicatorCreate] = Field(min_length=1)


@router.post(
    "/competences/{competence_id}/indicators/bulk",
    response_model=list[IndicatorRead],
    status_code=201,
)
async def bulk_create_indicators(
    competence_id: uuid.UUID,
    body: IndicatorBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """HRP-49: persist multiple indicators in one call."""
    created = await service.create_indicators_bulk(
        db,
        current_user.tenant_id,
        competence_id,
        body.indicators,
        actor_id=current_user.id,
    )
    return [_serialize_indicator(ind) for ind in created]


@router.put("/indicators/{indicator_id}", response_model=IndicatorRead)
async def update_indicator(
    indicator_id: uuid.UUID,
    data: IndicatorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    ind = await service.update_indicator(
        db, current_user.tenant_id, indicator_id, data, actor_id=current_user.id
    )
    return _serialize_indicator(ind)


@router.delete("/indicators/{indicator_id}", status_code=204)
async def delete_indicator(
    indicator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_indicator(
        db, current_user.tenant_id, indicator_id, actor_id=current_user.id
    )


@router.get("/indicators/{indicator_id}/usage")
async def get_indicator_usage(
    indicator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from app.modules.competence.models import Indicator

    ind = await db.get(Indicator, indicator_id)
    if ind is None:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_404_NOT_FOUND, "Indicator not found")
    usage = await check_indicator_usage(db, ind)
    return {
        "assessment": usage.assessment,
        "idp": usage.idp,
        "is_used": usage.is_used,
    }


@router.patch("/indicators/{indicator_id}/activate", response_model=IndicatorRead)
async def activate_indicator(
    indicator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    ind = await service.activate_indicator(
        db, current_user.tenant_id, indicator_id, actor_id=current_user.id
    )
    return _serialize_indicator(ind)


@router.patch("/indicators/{indicator_id}/deactivate", response_model=IndicatorRead)
async def deactivate_indicator(
    indicator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    ind = await service.deactivate_indicator(
        db, current_user.tenant_id, indicator_id, actor_id=current_user.id
    )
    return _serialize_indicator(ind)


@router.post("/indicators/{indicator_id}/move", response_model=IndicatorRead)
async def move_indicator(
    indicator_id: uuid.UUID,
    new_skill_level_id: uuid.UUID = Body(..., embed=True),
    new_sort_index: int = Body(0, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    ind = await service.move_indicator(
        db,
        current_user.tenant_id,
        indicator_id,
        new_skill_level_id,
        new_sort_index,
        actor_id=current_user.id,
    )
    return _serialize_indicator(ind)


# --- Materials ---


def _serialize_material(mat) -> dict:
    return {
        **{
            k: getattr(mat, k)
            for k in (
                "id",
                "title",
                "format",
                "link",
                "study_time",
                "comment",
                "material_type",
                "sort_index",
                "skill_level_id",
                "competence_id",
                "is_active",
                "tenant_id",
                "created_at",
            )
        },
        "skill_level_title": mat.skill_level.title if mat.skill_level else None,
    }


@router.post(
    "/competences/{competence_id}/materials",
    response_model=MaterialRead,
    status_code=201,
)
async def create_material(
    competence_id: uuid.UUID,
    data: MaterialCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    mat = await service.create_material(
        db, current_user.tenant_id, competence_id, data, actor_id=current_user.id
    )
    return _serialize_material(mat)


class MaterialBulkCreate(BaseModel):
    """HRP-51: payload for ``POST /competences/{id}/materials/bulk``.

    Used right after AI generation to persist the items the user kept in
    the review modal. Validation falls through to ``MaterialCreate``.
    """

    materials: list[MaterialCreate] = Field(min_length=1)


@router.post(
    "/competences/{competence_id}/materials/bulk",
    response_model=list[MaterialRead],
    status_code=201,
)
async def bulk_create_materials(
    competence_id: uuid.UUID,
    body: MaterialBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """HRP-51: persist multiple materials in one call (AI-review confirm).

    Tenant-guarded + transactional via ``service.create_materials_bulk``.
    """
    created = await service.create_materials_bulk(
        db,
        current_user.tenant_id,
        competence_id,
        body.materials,
        actor_id=current_user.id,
    )
    return [_serialize_material(mat) for mat in created]


class MaterialAIGenerateRequest(BaseModel):
    """HRP-51: input for ``POST /competences/{id}/ai-generate-materials``.

    ``skill_level_ids`` empty/``None`` → every active skill level.
    ``specialization_ids`` is tri-state: ``None`` falls back to the auto-
    picked linked set (legacy behaviour); ``[]`` means the operator
    deselected every specialization; a non-empty list overrides.
    ``indicator_ids`` ``None`` → every indicator; ``[]`` → none.
    ``division_ids`` ``None``/``[]`` → no division context.
    ``sibling_competence_ids`` ``None``/``[]`` → no sibling context.
    """

    skill_level_ids: list[uuid.UUID] | None = None
    specialization_ids: list[uuid.UUID] | None = None
    # HRP-51 review: new context blocks the operator can opt into from the
    # extended dialog. Defaults preserve the historical request payload.
    indicator_ids: list[uuid.UUID] | None = None
    division_ids: list[uuid.UUID] | None = None
    sibling_competence_ids: list[uuid.UUID] | None = None
    include_company_description: bool = True
    refinement: str | None = Field(default=None, max_length=4000)
    count_per_level: int = Field(default=3, ge=1, le=10)

    @field_validator("refinement", mode="before")
    @classmethod
    def _normalise_refinement(cls, value):
        # HRP-163: a refinement that is just whitespace adds a blank
        # "User refinement notes:" block to the prompt for no value; treat
        # it as missing instead.
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


@router.get(
    "/competences/{competence_id}/ai-generate-materials/context-options",
    response_model=ai_materials.MaterialsContextOptions,
)
async def materials_context_options(
    competence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """HRP-51 review: drives the materials Generate dialog's context picker.

    Returns the competence summary plus all indicators, every tenant
    specialization and division flagged with ``is_linked`` (linked through
    this competence's matrix / positions), the competence's sibling
    competences and the tenant's company description.
    """
    try:
        return await ai_materials.list_materials_context_options(
            db,
            tenant_id=current_user.tenant_id,
            competence_id=competence_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/competences/{competence_id}/ai-generate-materials",
    response_model=list[ai_materials.GeneratedMaterialItem],
)
async def ai_generate_materials(
    competence_id: uuid.UUID,
    body: MaterialAIGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """HRP-51: generate learning-material suggestions per skill level via LLM.

    Returns a preview list; the user reviews it in the modal and saves the
    selected entries through ``POST /competences/{id}/materials/bulk``.
    """
    try:
        return await ai_materials.generate_materials(
            db,
            tenant_id=current_user.tenant_id,
            competence_id=competence_id,
            skill_level_ids=body.skill_level_ids,
            specialization_ids=body.specialization_ids,
            indicator_ids=body.indicator_ids,
            division_ids=body.division_ids,
            sibling_competence_ids=body.sibling_competence_ids,
            include_company_description=body.include_company_description,
            refinement=body.refinement,
            count_per_level=body.count_per_level,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.put("/materials/{material_id}", response_model=MaterialRead)
async def update_material(
    material_id: uuid.UUID,
    data: MaterialUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    mat = await service.update_material(
        db, current_user.tenant_id, material_id, data, actor_id=current_user.id
    )
    return _serialize_material(mat)


@router.delete("/materials/{material_id}", status_code=204)
async def delete_material(
    material_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await service.delete_material(
        db, current_user.tenant_id, material_id, actor_id=current_user.id
    )


@router.get("/materials/{material_id}/usage")
async def get_material_usage(
    material_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    usage = await check_material_usage(db, material_id)
    return {"idp": usage.idp, "is_used": usage.is_used}


@router.patch("/materials/{material_id}/activate", response_model=MaterialRead)
async def activate_material(
    material_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    mat = await service.activate_material(
        db, current_user.tenant_id, material_id, actor_id=current_user.id
    )
    return _serialize_material(mat)


@router.patch("/materials/{material_id}/deactivate", response_model=MaterialRead)
async def deactivate_material(
    material_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    mat = await service.deactivate_material(
        db, current_user.tenant_id, material_id, actor_id=current_user.id
    )
    return _serialize_material(mat)


@router.post("/materials/{material_id}/move", response_model=MaterialRead)
async def move_material(
    material_id: uuid.UUID,
    new_skill_level_id: uuid.UUID = Body(..., embed=True),
    new_sort_index: int = Body(0, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    mat = await service.move_material(
        db,
        current_user.tenant_id,
        material_id,
        new_skill_level_id,
        new_sort_index,
        actor_id=current_user.id,
    )
    return _serialize_material(mat)


# --- Material specialization overrides (POS7) ---


def _serialize_material_in_context(mat, source: str) -> dict:
    return {
        "id": mat.id,
        "title": mat.title,
        "format": mat.format,
        "link": mat.link,
        "study_time": mat.study_time,
        "comment": mat.comment,
        "material_type": mat.material_type,
        "sort_index": mat.sort_index,
        "skill_level_id": mat.skill_level_id,
        "skill_level_title": mat.skill_level.title if mat.skill_level else None,
        "competence_id": mat.competence_id,
        "is_active": mat.is_active,
        "tenant_id": mat.tenant_id,
        "created_at": mat.created_at,
        "source": source,
    }


@router.get(
    "/competences/{competence_id}/materials",
    response_model=list[MaterialInContext],
)
async def list_competence_materials(
    competence_id: uuid.UUID,
    specialization_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List materials with override applied for `specialization_id` if given."""
    visible = await material_overrides.get_materials_for_specialization(
        db, current_user.tenant_id, competence_id, specialization_id
    )
    added_in_context: set[uuid.UUID] = set()
    if specialization_id is not None:
        overrides = await material_overrides.list_overrides(
            db,
            current_user.tenant_id,
            competence_id,
            specialization_id=specialization_id,
        )
        added_in_context = {o.material_id for o in overrides if o.mode == "add"}

    out: list[dict] = []
    for mat in visible:
        source = "added" if mat.id in added_in_context else "base"
        out.append(_serialize_material_in_context(mat, source))
    return out


@router.get(
    "/competences/{competence_id}/material-overrides",
    response_model=list[MaterialOverrideRead],
)
async def list_material_overrides(
    competence_id: uuid.UUID,
    specialization_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await material_overrides.list_overrides(
        db,
        current_user.tenant_id,
        competence_id,
        specialization_id=specialization_id,
    )


@router.post(
    "/competences/{competence_id}/material-overrides",
    response_model=MaterialOverrideRead,
    status_code=201,
)
async def create_material_override(
    competence_id: uuid.UUID,
    data: MaterialOverrideCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    return await material_overrides.add_material_override(
        db,
        current_user.tenant_id,
        competence_id,
        material_id=data.material_id,
        specialization_id=data.specialization_id,
        mode=data.mode,
    )


@router.delete(
    "/competences/{competence_id}/material-overrides/{override_id}",
    status_code=204,
)
async def delete_material_override(
    competence_id: uuid.UUID,
    override_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    await material_overrides.remove_material_override(
        db, current_user.tenant_id, competence_id, override_id
    )


# --- Audit log ---


@router.get(
    "/competences/{competence_id}/audit-log",
    response_model=list[CompetenceTreeAuditLogRead],
)
async def get_competence_audit_log(
    competence_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager")),
):
    """Recent audit-log entries that touched this competence directly."""
    result = await db.execute(
        select(CompetenceTreeAuditLog)
        .where(
            CompetenceTreeAuditLog.element_id == competence_id,
            CompetenceTreeAuditLog.tenant_id == current_user.tenant_id,
        )
        .order_by(CompetenceTreeAuditLog.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
