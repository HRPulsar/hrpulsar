from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class PrimitiveRead(BaseModel):
    id: uuid.UUID
    code: str
    kind: str
    ai_verdict: str
    ai_as_of: date
    ai_basis: str
    title_en: str
    scope_en: str | None
    i18n_key: str
    sort_index: int
    introduced_in: str
    retired_in: str | None
    merged_into_id: uuid.UUID | None

    model_config = {"from_attributes": True}


# --- Internal mapping surface (tag work-internal, hidden from public OpenAPI)


class MapRequest(BaseModel):
    # None = every active competence of the caller's tenant.
    competence_ids: list[uuid.UUID] | None = None
    # Re-map fresh ai_suggested rows too (prompt iteration). Reviewed and
    # manual links are never overwritten unless their text went stale.
    force: bool = False


class MapEnqueued(BaseModel):
    task_id: str


class MappingRead(BaseModel):
    competence_id: uuid.UUID
    title: str
    description: str | None
    # Empty for a rejected verdict or a model answer with no code.
    codes: list[str]
    status: str
    confidence: float | None
    rationale: str | None
    prompt_version: str | None
    mapped_at: datetime
    reviewed_at: datetime | None
    # The competence text changed since the mapping was made.
    stale: bool


class ReviewItem(BaseModel):
    competence_id: uuid.UUID
    verdict: Literal["accepted", "corrected", "rejected"]
    # Only read for ``corrected``. Bounded like every other primitive input
    # (``PrimitiveOverride.code``): a code is at most 10 characters, and a
    # competence has no business carrying more of them than the catalog has.
    primitives: list[Annotated[str, Field(min_length=1, max_length=10)]] = Field(
        default_factory=list, max_length=50
    )


class ReviewRequest(BaseModel):
    items: list[ReviewItem] = Field(min_length=1, max_length=200)


class ReviewResult(BaseModel):
    accepted: int
    corrected: int
    rejected: int
