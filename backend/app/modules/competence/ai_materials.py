"""AI generation for competence learning materials (HRP-51).

Given a competence and an optional context (specializations, indicators,
group), builds an LLM prompt that returns concrete learning resources
per skill level. The result is a preview the user reviews before any
``Material`` rows are persisted — saving happens through the bulk
``POST /competences/{id}/materials/bulk`` endpoint.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_sanitize import sanitize_user_refinement
from app.modules.ai import llm_client
from app.modules.ai_settings import service as ai_settings_service
from app.modules.company.models import Division, Tenant
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    Indicator,
    SkillLevel,
)
from app.modules.dictionary.models import DictionaryItem
from app.modules.dictionary.service import effective_is_active_expr
from app.modules.grade_system.models import (
    GradeCompetenceLink,
    GradeSpecialization,
)
from app.modules.position.models import Position

_SYSTEM_PROMPT = (
    "You are an HR / L&D expert. Given a competence (with its description "
    "and behavioural indicators) plus optional context (parent group, "
    "specializations that use the competence), recommend concrete learning "
    "materials for each requested skill level.\n\n"
    "Rules:\n"
    "- Each item must include a `title` (the resource name), a "
    "`material_type` (one of: course, book, article, video, podcast, "
    "documentation, practice), and a `skill_level` (one of the input "
    "skill levels — case-insensitive match to the user-supplied list).\n"
    "- `format` is a short freeform tag (e.g. \"Online course\", "
    "\"PDF book\", \"YouTube series\").\n"
    "- `link` is the URL when you are confident the resource exists at a "
    "stable URL; otherwise leave it null.\n"
    "- `study_time` is the expected study time IN HOURS, integer.\n"
    "- `comment` is a one-sentence rationale tying the resource to the "
    "competence's behavioural indicators or the listed specializations.\n"
    "- Calibrate difficulty per level: basic = fundamentals; "
    "intermediate = applied / project-based; advanced = "
    "depth / synthesis / coaching others.\n"
    "- Generate ALL textual content in English."
)


class GeneratedMaterialItem(BaseModel):
    """One material the LLM proposes. The frontend maps ``skill_level``
    back to the matching ``SkillLevel.id`` from the input set before
    posting to the bulk-save endpoint."""

    title: str = Field(min_length=1, max_length=600)
    format: str | None = Field(default=None, max_length=100)
    link: str | None = Field(default=None, max_length=600)
    study_time: int | None = None
    comment: str | None = Field(default=None, max_length=350)
    material_type: Literal[
        "course",
        "book",
        "article",
        "video",
        "podcast",
        "documentation",
        "practice",
    ]
    skill_level: str = Field(min_length=1, max_length=100)


class GeneratedMaterialsBundle(BaseModel):
    materials: list[GeneratedMaterialItem]


def build_materials_prompt(
    *,
    competence_title: str,
    competence_type: str | None,
    competence_description: str | None,
    group_title: str | None,
    indicators_by_level: dict[str, list[str]],
    specializations: list[str],
    divisions: list[str],
    sibling_competences: list[str],
    company_description: str | None,
    skill_levels: list[str],
    count_per_level: int,
    refinement: str | None,
) -> tuple[str, str]:
    """Build (system, user) prompts for the materials generator.

    ``indicators_by_level`` maps each skill level title to the indicators
    the operator opted into for context. HRP-51 review: every block here is
    optional context — the front-end picker lets the operator drop any
    section, so empty lists / ``None`` values must simply be omitted from
    the payload rather than confuse the LLM with empty keys.
    """
    task = (
        f"Task: recommend at least {count_per_level} learning materials per "
        f"skill_level for the competence '{competence_title}'. Cover every "
        "skill_level listed by the user; do not invent new levels."
    )
    system = "\n\n".join([_SYSTEM_PROMPT, task])

    payload: dict[str, Any] = {
        "competence": competence_title,
        "skill_levels": skill_levels,
        "count_per_level": count_per_level,
    }
    if competence_type:
        payload["competence_type"] = competence_type
    if competence_description:
        payload["competence_description"] = competence_description
    if group_title:
        payload["group"] = group_title
    # Indicators ship per-level so the LLM can match material difficulty to
    # the behaviours the operator selected. Skip empty levels so the prompt
    # doesn't carry decorative noise.
    cleaned_indicators = {
        lvl: items for lvl, items in indicators_by_level.items() if items
    }
    if cleaned_indicators:
        payload["indicators_by_level"] = cleaned_indicators
    if specializations:
        payload["specializations"] = specializations
    if divisions:
        payload["divisions"] = divisions
    if sibling_competences:
        payload["sibling_competences"] = sibling_competences
    if company_description:
        payload["company"] = company_description
    user = "Inputs:\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    if refinement and refinement.strip():
        user += (
            "\n\nUser refinement notes (apply these to your answer):\n"
            f"{refinement.strip()}"
        )
    return system, user


async def _resolve_linked_specialization_ids(
    db: AsyncSession, *, tenant_id: uuid.UUID, competence_id: uuid.UUID
) -> set[uuid.UUID]:
    """Specialization ids reachable from the competence through the matrix.
    Used both by the auto-resolve fallback in `generate_materials` and by
    the `context-options` endpoint to flag rows as `is_linked: true`."""
    q = await db.execute(
        select(DictionaryItem.id)
        .join(
            GradeSpecialization,
            GradeSpecialization.specialization_id == DictionaryItem.id,
        )
        .join(
            GradeCompetenceLink,
            GradeCompetenceLink.grade_specialization_id == GradeSpecialization.id,
        )
        .where(
            GradeCompetenceLink.competence_id == competence_id,
            GradeSpecialization.tenant_id == tenant_id,
            effective_is_active_expr(tenant_id).is_(True),
        )
        .distinct()
    )
    return {row for (row,) in q.all()}


async def _resolve_linked_division_ids(
    db: AsyncSession, *, tenant_id: uuid.UUID, competence_id: uuid.UUID
) -> set[uuid.UUID]:
    """Division ids reachable from the competence via
    competence → specializations → positions → divisions. Surfaced as
    `is_linked: true` in the context-options payload."""
    linked_specs = await _resolve_linked_specialization_ids(
        db, tenant_id=tenant_id, competence_id=competence_id
    )
    if not linked_specs:
        return set()
    q = await db.execute(
        select(Position.division_id)
        .where(
            Position.tenant_id == tenant_id,
            Position.specialization_id.in_(linked_specs),
            Position.division_id.is_not(None),
        )
        .distinct()
    )
    return {row for (row,) in q.all() if row is not None}


class MaterialsContextGroup(BaseModel):
    id: uuid.UUID
    title: str


class MaterialsContextCompetence(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    type: str | None
    group: MaterialsContextGroup | None


class MaterialsContextIndicator(BaseModel):
    id: uuid.UUID
    title: str
    skill_level_id: uuid.UUID | None
    skill_level_title: str | None


class MaterialsContextLinkedItem(BaseModel):
    id: uuid.UUID
    title: str
    is_linked: bool


class MaterialsContextSibling(BaseModel):
    id: uuid.UUID
    title: str


class MaterialsContextOptions(BaseModel):
    """HRP-51 review: payload for the materials Generate dialog's context
    picker. Surfaces every block the operator can opt into or out of."""

    competence: MaterialsContextCompetence
    indicators: list[MaterialsContextIndicator]
    specializations: list[MaterialsContextLinkedItem]
    divisions: list[MaterialsContextLinkedItem]
    sibling_competences: list[MaterialsContextSibling]
    company_description: str | None


async def list_materials_context_options(
    db: AsyncSession, *, tenant_id: uuid.UUID, competence_id: uuid.UUID
) -> MaterialsContextOptions:
    """Build the context-options payload for the AI materials dialog.

    Each `is_linked` flag tells the front-end which rows to pre-check —
    specializations linked through this competence's matrix, divisions
    reachable via those specializations' positions. Unlinked rows are
    included so the operator can broaden context manually.
    """
    competence = await db.get(Competence, competence_id)
    if competence is None or (
        competence.tenant_id is not None
        and competence.tenant_id != tenant_id
    ):
        raise ValueError("Competence not found")

    group: CompetenceGroup | None = None
    if competence.group_id:
        group = await db.get(CompetenceGroup, competence.group_id)

    competence_type_title: str | None = None
    if competence.competence_type_id:
        ct_q = await db.execute(
            select(DictionaryItem.title).where(
                DictionaryItem.id == competence.competence_type_id
            )
        )
        competence_type_title = ct_q.scalar_one_or_none()

    ind_q = await db.execute(
        select(Indicator, SkillLevel.id, SkillLevel.title, SkillLevel.sort_index)
        .join(SkillLevel, SkillLevel.id == Indicator.skill_level_id)
        .where(
            Indicator.competence_id == competence_id,
            Indicator.is_active.is_(True),
            # Defensive tenant scoping — origin-pack indicators ride along,
            # other tenants' indicators on the same competence never appear.
            (Indicator.tenant_id == tenant_id) | Indicator.tenant_id.is_(None),
        )
        .order_by(SkillLevel.sort_index, Indicator.sort_index, Indicator.title)
    )
    indicators = [
        MaterialsContextIndicator(
            id=ind.id,
            title=ind.title,
            skill_level_id=lvl_id,
            skill_level_title=lvl_title,
        )
        for ind, lvl_id, lvl_title, _ in ind_q.all()
    ]

    linked_spec_ids = await _resolve_linked_specialization_ids(
        db, tenant_id=tenant_id, competence_id=competence_id
    )
    spec_q = await db.execute(
        select(DictionaryItem.id, DictionaryItem.title)
        .where(
            DictionaryItem.type == "specialization",
            effective_is_active_expr(tenant_id).is_(True),
            (DictionaryItem.tenant_id == tenant_id)
            | DictionaryItem.tenant_id.is_(None),
        )
        .order_by(DictionaryItem.title)
    )
    specializations = [
        MaterialsContextLinkedItem(
            id=row_id, title=row_title, is_linked=row_id in linked_spec_ids
        )
        for row_id, row_title in spec_q.all()
    ]

    linked_div_ids = await _resolve_linked_division_ids(
        db, tenant_id=tenant_id, competence_id=competence_id
    )
    div_q = await db.execute(
        select(Division.id, Division.name)
        .where(
            Division.tenant_id == tenant_id,
        )
        .order_by(Division.name)
    )
    divisions = [
        MaterialsContextLinkedItem(
            id=row_id, title=row_name, is_linked=row_id in linked_div_ids
        )
        for row_id, row_name in div_q.all()
    ]

    siblings: list[MaterialsContextSibling] = []
    if competence.group_id is not None:
        sib_q = await db.execute(
            select(Competence.id, Competence.title)
            .where(
                Competence.group_id == competence.group_id,
                Competence.id != competence_id,
                Competence.is_active.is_(True),
                (Competence.tenant_id == tenant_id)
                | Competence.tenant_id.is_(None),
            )
            .order_by(Competence.title)
        )
        siblings = [
            MaterialsContextSibling(id=row_id, title=row_title)
            for row_id, row_title in sib_q.all()
        ]

    tenant = await db.get(Tenant, tenant_id)
    company_description = tenant.description if tenant else None

    return MaterialsContextOptions(
        competence=MaterialsContextCompetence(
            id=competence.id,
            title=competence.title,
            description=competence.description,
            type=competence_type_title,
            group=(
                MaterialsContextGroup(id=group.id, title=group.title)
                if group
                else None
            ),
        ),
        indicators=indicators,
        specializations=specializations,
        divisions=divisions,
        sibling_competences=siblings,
        company_description=company_description,
    )


async def generate_materials(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    skill_level_ids: list[uuid.UUID] | None,
    specialization_ids: list[uuid.UUID] | None,
    indicator_ids: list[uuid.UUID] | None = None,
    division_ids: list[uuid.UUID] | None = None,
    sibling_competence_ids: list[uuid.UUID] | None = None,
    include_company_description: bool = True,
    refinement: str | None = None,
    count_per_level: int = 3,
) -> list[GeneratedMaterialItem]:
    """Build the prompt, call the LLM, return the parsed material list.

    HRP-51 review: every context block beyond the competence itself is now
    an explicit list passed in by the caller. ``None`` for indicator_ids
    keeps the previous behaviour (all indicators included); empty list
    means the operator deselected all indicators on purpose. The same
    distinction applies to ``specialization_ids`` (None = auto-pick linked,
    [] = no spec context).
    """
    competence = await db.get(Competence, competence_id)
    if competence is None or (
        competence.tenant_id is not None
        and competence.tenant_id != tenant_id
    ):
        raise ValueError("Competence not found")

    group: CompetenceGroup | None = None
    if competence.group_id:
        group = await db.get(CompetenceGroup, competence.group_id)

    levels_q = await db.execute(
        select(SkillLevel)
        .where(
            SkillLevel.is_active.is_(True),
            (SkillLevel.tenant_id == tenant_id) | (SkillLevel.tenant_id.is_(None)),
        )
        .order_by(SkillLevel.sort_index)
    )
    all_levels = list(levels_q.scalars().all())
    if skill_level_ids:
        wanted_ids = set(skill_level_ids)
        levels = [lvl for lvl in all_levels if lvl.id in wanted_ids]
    else:
        levels = all_levels
    if not levels:
        raise ValueError("No skill levels resolved for this generation request")

    ind_q = await db.execute(
        select(Indicator, SkillLevel.title)
        .join(SkillLevel, SkillLevel.id == Indicator.skill_level_id)
        .where(
            Indicator.competence_id == competence_id,
            Indicator.is_active.is_(True),
            # Mirror the tenant-scope guard from the context-options query.
            (Indicator.tenant_id == tenant_id) | Indicator.tenant_id.is_(None),
        )
    )
    indicators_by_level: dict[str, list[str]] = {lvl.title: [] for lvl in levels}
    indicator_filter = (
        set(indicator_ids) if indicator_ids is not None else None
    )
    for ind, level_title in ind_q.all():
        if level_title not in indicators_by_level:
            continue
        if indicator_filter is not None and ind.id not in indicator_filter:
            continue
        indicators_by_level[level_title].append(ind.title)

    specialization_titles: list[str] = []
    if specialization_ids is not None:
        if specialization_ids:
            spec_q = await db.execute(
                select(DictionaryItem.title)
                .where(
                    DictionaryItem.id.in_(specialization_ids),
                    DictionaryItem.type == "specialization",
                    effective_is_active_expr(tenant_id).is_(True),
                    (DictionaryItem.tenant_id == tenant_id)
                    | DictionaryItem.tenant_id.is_(None),
                )
                .order_by(DictionaryItem.title)
            )
            specialization_titles = [t for (t,) in spec_q.all()]
    else:
        # Backwards-compat: `None` = auto-pick every linked specialization,
        # matching the original HRP-51 contract before the context picker
        # let the operator pass an explicit (possibly empty) list.
        spec_q = await db.execute(
            select(DictionaryItem.title)
            .join(
                GradeSpecialization,
                GradeSpecialization.specialization_id == DictionaryItem.id,
            )
            .join(
                GradeCompetenceLink,
                GradeCompetenceLink.grade_specialization_id == GradeSpecialization.id,
            )
            .where(
                GradeCompetenceLink.competence_id == competence_id,
                GradeSpecialization.tenant_id == tenant_id,
                effective_is_active_expr(tenant_id).is_(True),
            )
            .distinct()
            .order_by(DictionaryItem.title)
        )
        specialization_titles = [t for (t,) in spec_q.all()]

    division_titles: list[str] = []
    if division_ids:
        div_q = await db.execute(
            select(Division.name)
            .where(
                Division.id.in_(division_ids),
                Division.tenant_id == tenant_id,
            )
            .order_by(Division.name)
        )
        division_titles = [t for (t,) in div_q.all()]

    sibling_titles: list[str] = []
    if sibling_competence_ids:
        sib_q = await db.execute(
            select(Competence.title)
            .where(
                Competence.id.in_(sibling_competence_ids),
                # Stay inside the competence's own group — the request
                # shape doesn't let the operator hand-pick across groups.
                Competence.group_id == competence.group_id,
                Competence.is_active.is_(True),
                (Competence.tenant_id == tenant_id)
                | Competence.tenant_id.is_(None),
            )
            .order_by(Competence.title)
        )
        sibling_titles = [t for (t,) in sib_q.all()]

    company_description: str | None = None
    if include_company_description:
        tenant = await db.get(Tenant, tenant_id)
        if tenant is not None:
            company_description = tenant.description

    competence_type_title: str | None = None
    if competence.competence_type_id:
        ct_q = await db.execute(
            select(DictionaryItem.title).where(
                DictionaryItem.id == competence.competence_type_id
            )
        )
        competence_type_title = ct_q.scalar_one_or_none()

    system, user_prompt = build_materials_prompt(
        competence_title=competence.title,
        competence_type=competence_type_title,
        competence_description=competence.description,
        group_title=group.title if group else None,
        indicators_by_level=indicators_by_level,
        specializations=specialization_titles,
        divisions=division_titles,
        sibling_competences=sibling_titles,
        company_description=company_description,
        skill_levels=[lvl.title for lvl in levels],
        count_per_level=max(1, count_per_level),
        refinement=sanitize_user_refinement(refinement),
    )

    tenant_settings = await ai_settings_service.get_or_default(db, tenant_id)
    # The bundle schema is strict — a single drifted ``material_type`` from
    # the LLM would fail the whole batch. Use ``generate_json`` without a
    # schema and validate items one-by-one so the worker tolerates partial
    # drift and the user still sees the clean rows.
    raw = await llm_client.generate_json(
        user_prompt,
        system=system,
        tenant_settings=tenant_settings,
        max_tokens=4096,
    )

    raw_items: list[Any] = []
    if isinstance(raw, dict):
        raw_items = list(raw.get("materials") or [])
    elif isinstance(raw, list):
        raw_items = list(raw)

    wanted_titles = {lvl.title.casefold().strip() for lvl in levels}
    items: list[GeneratedMaterialItem] = []
    for item in raw_items:
        try:
            parsed = GeneratedMaterialItem.model_validate(item)
        except ValidationError:
            # Skip rows the LLM emitted with an unsupported material_type or
            # any other contract violation. We log nothing here — a quiet
            # filter is enough to keep the preview list usable.
            continue
        if parsed.skill_level.casefold().strip() in wanted_titles:
            items.append(parsed)
    return items
