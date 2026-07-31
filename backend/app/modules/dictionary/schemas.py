from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

VALID_TYPES = {
    "grade",
    "specialization",
    "role",
    "goal",
    "project",
    "competence_type",
    # HRP-281: open vocabularies the demo seed populates so the Settings
    # → Dictionaries page has more than the company's grade + spec catalog.
    "language",
    "certification",
    "office_location",
}


# HRP-282: tightened from 255/500 to 100/250 across every dictionary type.
# The DB columns stay at 255/500 — only the API validator caps user input.
TITLE_MAX_LENGTH = 100
DESCRIPTION_MAX_LENGTH = 250


class DictionaryItemCreate(BaseModel):
    title: str = Field(max_length=TITLE_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    sort_index: int = 0
    metadata: dict[str, Any] | None = None


class DictionaryItemUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=TITLE_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    is_active: bool | None = None
    sort_index: int | None = None
    metadata: dict[str, Any] | None = None


class DictionaryItemRead(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    description: str | None
    # HRP-479: set on origin rows only (seed migrations); NULL for
    # tenant-created items. Read-only — create/update never accept it.
    i18n_key: str | None = None
    is_active: bool
    sort_index: int
    tenant_id: uuid.UUID | None
    metadata: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DictionaryItemUsagePosition(BaseModel):
    id: uuid.UUID
    title: str


class DictionaryItemUsageChain(BaseModel):
    id: uuid.UUID
    grade_id: uuid.UUID | None
    grade_title: str | None
    specialization_id: uuid.UUID | None
    specialization_title: str | None


class DictionaryItemUsageRead(BaseModel):
    """HRP-103 redo: lists the live references that block delete so the
    confirm dialog can enumerate them instead of surfacing a bare count.

    Prod fix (issue 7559975192): also exposes counts for assessment /
    assessment group / PDP / exam pass-mark references — these tables have
    RESTRICT-by-default FKs on ``dictionary_items.id`` and the bare DELETE
    surfaced a 500 ForeignKeyViolationError before they were checked.
    """

    positions: list[DictionaryItemUsagePosition]
    chains: list[DictionaryItemUsageChain]
    assessments_count: int = 0
    assessment_groups_count: int = 0
    pdps_count: int = 0
    exam_pass_marks_count: int = 0
    # HRP-286 redo: competences referencing a competence_type item (the FK
    # is SET NULL, so the delete gate counts them explicitly).
    competences_count: int = 0
