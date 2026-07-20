"""Pydantic schemas for AI competence generation sessions.

`GeneratedTreeSchema` is the strict contract returned by the LLM. Every
node carries a transient `temp_id` (uuid4 the worker assigns after parsing)
so the frontend can address checkboxes without colliding with real
database UUIDs. `apply_session` resolves these temp_ids when persisting.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Strict LLM output schema (passed to llm_client.generate_json as `schema`)
# ---------------------------------------------------------------------------


class GeneratedIndicator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=600)
    skill_level: str = Field(
        min_length=1,
        max_length=100,
        description="Skill-level title from the source list (e.g. 'basic').",
    )


class GeneratedMatrixCompetence(BaseModel):
    """Competence inside a `specialization_matrix` payload.

    Differs from `GeneratedCompetence`: each competence carries an explicit
    map ``grade_levels`` from grade title to skill-level title — that's the
    matrix the apply step writes into `GradeCompetenceLink` for every
    `(grade_specialization, competence)` pair. Indicators are still listed
    once per competence (not per grade); apply step inserts them under the
    target competence's own indicator list, not under the matrix link.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=500)
    type: Literal["hard_skill", "soft_skill", "unique_skill"] = "hard_skill"
    indicators: list[GeneratedIndicator] = Field(default_factory=list)
    grade_levels: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Map of grade title → skill-level title for the matrix row. "
            "Levels must come from the input skill_levels list. Higher "
            "grades cannot drop below lower grades."
        ),
    )


class GeneratedMatrixGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=500)
    competences: list[GeneratedMatrixCompetence] = Field(default_factory=list)


class GeneratedMatrixSchema(BaseModel):
    """Top-level schema for `specialization_matrix` scope.

    Flatter than `GeneratedTreeSchema` — matrix groups are visual buckets
    inside one specialization, not a full hierarchy. The apply step folds
    them into existing competence groups (or creates new ones at the root).
    """

    model_config = ConfigDict(extra="forbid")

    groups: list[GeneratedMatrixGroup] = Field(default_factory=list)


class GeneratedCompetence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=500)
    type: Literal["hard_skill", "soft_skill", "unique_skill"] = "hard_skill"
    indicators: list[GeneratedIndicator] = Field(default_factory=list)


class GeneratedGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=500)
    children: list[GeneratedGroup] = Field(default_factory=list)
    competences: list[GeneratedCompetence] = Field(default_factory=list)


class GeneratedTreeSchema(BaseModel):
    """Top-level schema: a list of new groups, each with its competences/children.

    Used for both `whole_base` and `group` scopes. For `group`, the LLM still
    returns a list — the worker treats each top-level entry as a sibling
    of the target group's existing children.
    """

    model_config = ConfigDict(extra="forbid")

    groups: list[GeneratedGroup] = Field(default_factory=list)


class GeneratedIndicatorsSchema(BaseModel):
    """Output schema for `competence_indicators` scope."""

    model_config = ConfigDict(extra="forbid")

    indicators: list[GeneratedIndicator] = Field(default_factory=list)


GeneratedGroup.model_rebuild()


# ---------------------------------------------------------------------------
# Request DTOs
# ---------------------------------------------------------------------------


SessionScope = Literal[
    "whole_base", "group", "competence_indicators", "specialization_matrix"
]
SessionStatus = Literal["pending", "running", "ready", "error", "applied", "cancelled"]


def _strip_to_none(value: str | None) -> str | None:
    """HRP-163: trim whitespace + treat all-blank strings as missing so the
    LLM prompt isn't padded with a blank "User refinement notes:" block."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class SessionParams(BaseModel):
    """Free-form params attached to a session at creation time."""

    model_config = ConfigDict(extra="ignore")

    with_indicators: bool = True
    refinement_prompt: str | None = Field(default=None, max_length=4000)

    @field_validator("refinement_prompt", mode="before")
    @classmethod
    def _normalise_refinement_prompt(cls, value):
        return _strip_to_none(value) if isinstance(value, str) else value
    # HRP-102: when an indicator-generation session is launched from a
    # specialization-matrix cell we carry the source spec id so the prompt
    # can see grades and sibling competences. Optional everywhere else.
    specialization_id: uuid.UUID | None = None
    # HRP-123 / HRP-124 / HRP-114: the preflight modal lets the user trim
    # the context the LLM sees before generation. Recognised keys:
    # - "specializations" / "divisions" / "company" — tenant-wide context
    #   (HRP-123, applied to whole_base + HRP-114 group + indicators)
    # - "source_tree" — drops the existing competence tree from a
    #   whole_base augment, or the existing group children for `group`
    #   scope, so the LLM starts from scratch
    # - "existing_indicators" — `competence_indicators` only; drops the
    #   competence's current indicators from the prompt so the LLM
    #   suggests freely
    # - "sibling_competences" — `competence_indicators` only; drops other
    #   competences in the same group / matrix sibling set so they don't
    #   influence indicator phrasing
    # Empty list = use everything available (default). Names appearing
    # here are dropped from the prompt.
    context_excludes: list[str] = Field(default_factory=list)


class SessionCreate(BaseModel):
    scope: SessionScope
    target_id: uuid.UUID | None = None
    params: SessionParams = Field(default_factory=SessionParams)


class SessionRefine(BaseModel):
    """Body of POST /sessions/{id}/refine.

    Mirrors the four free-form fields from the PM spec — they are concatenated
    by the prompt builder; an explicitly null value is dropped.
    """

    general: str | None = Field(default=None, max_length=2000)
    add: str | None = Field(default=None, max_length=2000)
    change: str | None = Field(default=None, max_length=2000)
    exclude: str | None = Field(default=None, max_length=2000)

    @field_validator("general", "add", "change", "exclude", mode="before")
    @classmethod
    def _normalise_refine_field(cls, value):
        return _strip_to_none(value) if isinstance(value, str) else value


class SessionApply(BaseModel):
    publish: bool = False
    idempotency_key: str = Field(min_length=8, max_length=100)


class SelectionPatch(BaseModel):
    node_id: str = Field(min_length=1, max_length=100)
    selected: bool


class SelectionEdit(BaseModel):
    """Per-suggestion override (HRP-71 phase 3) — currently only title.

    Stored verbatim under `selection_state["_edits"][temp_id]` and consumed
    by `apply_session` when materialising the row. Extra keys are forbidden
    so a future `description`/`type` rename has to be added explicitly.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=600)


class SelectionReplace(BaseModel):
    """Body of `PUT /sessions/{id}/selection-state`.

    Frontend ships the full final selection map after applying cascade
    locally, so apply doesn't need N round-trips for big matrices.
    `edits` carries per-suggestion title overrides (HRP-71 phase 3) — they
    survive across `replaceSelection` calls only when re-sent.
    """

    selection_state: dict[str, bool] = Field(default_factory=dict)
    edits: dict[str, SelectionEdit] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Response DTOs
# ---------------------------------------------------------------------------


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID

    scope: SessionScope
    target_id: uuid.UUID | None

    params: dict
    payload: dict | None
    selection_state: dict

    status: SessionStatus
    error_code: str | None
    error_message: str | None

    parent_session_id: uuid.UUID | None
    prompt_version: str
    llm_model: str | None
    tokens_used: int | None

    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    # HRP-114 re-spec: existing-content preview alongside the generated tree.
    # Populated from `base_snapshot` so the result modal can render
    # already-present subgroups/competences/indicators as read-only siblings of
    # the new suggestions — the user sees what's already there without having
    # to leave the dialog. `None` for scopes where the notion doesn't apply
    # (matrix has its own preview path).
    existing_tree: list[dict] | None = None
    existing_indicators: list[dict] | None = None


class ApplyResult(BaseModel):
    """What `POST /sessions/{id}/apply` returns."""

    created_groups: list[uuid.UUID] = Field(default_factory=list)
    created_competences: list[uuid.UUID] = Field(default_factory=list)
    created_indicators: list[uuid.UUID] = Field(default_factory=list)
    created_grade_links: list[uuid.UUID] = Field(default_factory=list)
    idempotency_key: str


class OtherActiveSessionRead(BaseModel):
    """One row in `GET /sessions/active-others` — used by PreflightModal."""

    session_id: uuid.UUID
    user_id: uuid.UUID
    user_full_name: str
    scope: SessionScope
    target_id: uuid.UUID | None
    status: SessionStatus
    created_at: datetime


class SessionHistorySummary(BaseModel):
    """Compact brief of what was fed into a session — surfaces in history list."""

    refinement_prompt: str | None = None
    position_title: str | None = None
    file_count: int = 0
    with_indicators: bool = True


class SessionHistoryCounts(BaseModel):
    """Derived totals for a session row.

    `grades` is non-zero only for `specialization_matrix`. `accepted` /
    `rejected` come from `applied_result.created_*` for terminal-applied
    sessions, and from `selection_state` checkboxes for everything else.
    """

    grades: int = 0
    competences: int = 0
    indicators: int = 0
    accepted: int = 0
    rejected: int = 0


class SessionHistoryItem(BaseModel):
    """One row in `GET /sessions` — list view, no payload, derived counts."""

    id: uuid.UUID
    user_id: uuid.UUID
    user_full_name: str

    scope: SessionScope
    target_id: uuid.UUID | None

    status: SessionStatus
    error_code: str | None
    error_message: str | None

    parent_session_id: uuid.UUID | None
    prompt_version: str
    llm_model: str | None

    summary: SessionHistorySummary
    counts: SessionHistoryCounts

    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
