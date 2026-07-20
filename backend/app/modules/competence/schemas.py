from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# --- CompetenceGroup ---


class CompetenceGroupCreate(BaseModel):
    title: str = Field(max_length=300)
    description: str | None = Field(default=None, max_length=500)
    parent_id: uuid.UUID | None = None
    sort_index: int = 0
    is_active: bool = True


class CompetenceGroupUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=500)
    parent_id: uuid.UUID | None = None
    sort_index: int | None = None
    is_active: bool | None = None


class CompetenceGroupRead(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    parent_id: uuid.UUID | None
    tenant_id: uuid.UUID | None
    sort_index: int
    is_active: bool
    can_deactivate: bool
    is_root_origin: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class CompetenceGroupTree(CompetenceGroupRead):
    children: list[CompetenceGroupTree] = []
    competences: list[CompetenceRead] = []
    competences_count: int = 0
    # HRP-118: true when at least one descendant competence is referenced by a
    # matrix / assessment / IDP / employee card / talent market. The tree UI
    # uses this to hide the Delete menu (since deletion is rejected anyway).
    is_used: bool = False


# --- Competence ---


class CompetenceCreate(BaseModel):
    title: str = Field(max_length=300)
    description: str | None = Field(default=None, max_length=500)
    group_id: uuid.UUID
    competence_type_id: uuid.UUID | None = None


class CompetenceBulkCreateItem(BaseModel):
    title: str = Field(max_length=300)
    description: str | None = Field(default=None, max_length=500)
    competence_type_id: uuid.UUID | None = None


class CompetenceBulkCreate(BaseModel):
    items: list[CompetenceBulkCreateItem] = Field(min_length=1, max_length=100)


class CompetenceUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=500)
    group_id: uuid.UUID | None = None
    competence_type_id: uuid.UUID | None = None
    is_active: bool | None = None


class CompetenceRead(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    group_id: uuid.UUID
    competence_type_id: uuid.UUID | None
    tenant_id: uuid.UUID | None
    is_active: bool
    is_published: bool
    created_at: datetime
    is_origin: bool = False
    is_used: bool = False
    levels_completion: dict | None = None

    model_config = {"from_attributes": True}


class CompetenceDetail(CompetenceRead):
    indicators: list[IndicatorRead] = []
    materials: list[MaterialRead] = []


# --- SkillLevel ---


class SkillLevelCreate(BaseModel):
    title: str = Field(max_length=300)
    sort_index: int = 0
    i18n_key: str | None = Field(default=None, max_length=100)


class SkillLevelUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    sort_index: int | None = None
    i18n_key: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class SkillLevelRead(BaseModel):
    id: uuid.UUID
    title: str
    sort_index: int
    i18n_key: str | None
    is_active: bool
    tenant_id: uuid.UUID | None

    model_config = {"from_attributes": True}


# --- Indicator ---


class IndicatorCreate(BaseModel):
    title: str = Field(max_length=600)
    weight: int = 0
    sort_index: int = 0
    skill_level_id: uuid.UUID


class IndicatorUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=600)
    weight: int | None = None
    sort_index: int | None = None
    skill_level_id: uuid.UUID | None = None
    is_active: bool | None = None


class IndicatorRead(BaseModel):
    id: uuid.UUID
    title: str
    weight: int
    sort_index: int
    skill_level_id: uuid.UUID
    skill_level_title: str | None = None
    competence_id: uuid.UUID
    is_active: bool
    tenant_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Material ---


class MaterialCreate(BaseModel):
    title: str = Field(max_length=600)
    format: str | None = Field(default=None, max_length=100)
    link: str | None = Field(default=None, max_length=600)
    study_time: int | None = None
    comment: str | None = Field(default=None, max_length=350)
    material_type: str | None = Field(default=None, max_length=50)
    sort_index: int = 0
    skill_level_id: uuid.UUID


class MaterialUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=600)
    format: str | None = Field(default=None, max_length=100)
    link: str | None = Field(default=None, max_length=600)
    study_time: int | None = None
    comment: str | None = Field(default=None, max_length=350)
    material_type: str | None = Field(default=None, max_length=50)
    sort_index: int | None = None
    skill_level_id: uuid.UUID | None = None
    is_active: bool | None = None


class MaterialRead(BaseModel):
    id: uuid.UUID
    title: str
    format: str | None
    link: str | None
    study_time: int | None
    comment: str | None
    material_type: str | None
    sort_index: int
    skill_level_id: uuid.UUID
    skill_level_title: str | None = None
    competence_id: uuid.UUID
    is_active: bool
    tenant_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Material specialization override (POS7) ---


class MaterialOverrideCreate(BaseModel):
    material_id: uuid.UUID
    specialization_id: uuid.UUID
    mode: str = Field(pattern=r"^(hide|add)$")


class MaterialOverrideRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    material_id: uuid.UUID
    specialization_id: uuid.UUID
    mode: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MaterialInContext(MaterialRead):
    """Material as seen on the per-specialization tab.

    `source` distinguishes a regular base material from one that exists in
    this context only because of an `add` override, so the UI can label it
    «Added in context».
    """

    source: str = "base"


# --- Audit log ---


class CompetenceTreeAuditLogRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    action: str
    element_type: str | None
    element_id: uuid.UUID | None
    payload: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
