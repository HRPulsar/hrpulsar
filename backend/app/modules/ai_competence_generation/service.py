"""Business logic for AI competence generation sessions.

Lifecycle helpers (create / cancel / refine / regenerate / clear), the
selection-state cascade, and the atomic `apply_session(...)` that
materialises checked nodes into real competence-tree rows.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_competence_generation.models import (
    ACTIVE_STATUSES,
    CompetenceGenerationSession,
)
from app.modules.ai_competence_generation.schemas import (
    SessionCreate,
    SessionRefine,
)
from app.modules.competence.models import (
    Competence,
    CompetenceGroup,
    CompetenceTreeAuditLog,
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

logger = logging.getLogger(__name__)


# Re-export for backwards-compat with callers that imported the helpers from
# `service`. New code should import from `billing_actions` directly.
from app.modules.ai_competence_generation.billing_actions import (  # noqa: E402
    refine_action_for_scope as _refine_billing_action,
)
from app.modules.ai_competence_generation.billing_actions import (
    start_action_for_scope as _start_billing_action,
)

# ---------------------------------------------------------------------------
# Pre-conditions (raise 422 with structured error_code)
# ---------------------------------------------------------------------------


async def _ensure_specializations_exist(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    result = await db.execute(
        select(DictionaryItem.id)
        .where(
            DictionaryItem.type == "specialization",
            effective_is_active_expr(tenant_id).is_(True),
            (DictionaryItem.tenant_id == tenant_id)
            | DictionaryItem.tenant_id.is_(None),
        )
        .limit(1)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "insufficient_data",
                "message": (
                    "At least one active specialization is required before "
                    "running whole-base generation."
                ),
            },
        )


async def _ensure_group_accessible(
    db: AsyncSession, tenant_id: uuid.UUID, group_id: uuid.UUID
) -> CompetenceGroup:
    group = await db.get(CompetenceGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    if group.tenant_id is not None and group.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Group not accessible")
    return group


async def _ensure_specialization_visible(
    db: AsyncSession, tenant_id: uuid.UUID, spec_id: uuid.UUID
) -> DictionaryItem:
    spec = await db.get(DictionaryItem, spec_id)
    if (
        spec is None
        or spec.type != "specialization"
        or (spec.tenant_id is not None and spec.tenant_id != tenant_id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Specialization not found")
    return spec


async def _ensure_specialization_accessible(
    db: AsyncSession, tenant_id: uuid.UUID, spec_id: uuid.UUID
) -> DictionaryItem:
    spec = await _ensure_specialization_visible(db, tenant_id, spec_id)
    pairs_q = await db.execute(
        select(GradeSpecialization.id)
        .where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == spec_id,
        )
        .limit(1)
    )
    if pairs_q.scalar_one_or_none() is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "insufficient_data",
                "message": (
                    "Specialization has no grades configured. "
                    "Add grades before running matrix generation."
                ),
            },
        )
    return spec


async def _ensure_competence_accessible(
    db: AsyncSession, tenant_id: uuid.UUID, comp_id: uuid.UUID
) -> Competence:
    comp = await db.get(Competence, comp_id)
    if comp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Competence not found")
    if comp.tenant_id is not None and comp.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Competence not accessible")
    return comp


async def _active_skill_levels(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[SkillLevel]:
    result = await db.execute(
        select(SkillLevel).where(
            SkillLevel.is_active.is_(True),
            (SkillLevel.tenant_id == tenant_id) | SkillLevel.tenant_id.is_(None),
        )
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# HRP-143: context options endpoint
# ---------------------------------------------------------------------------


async def list_context_options(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    scope: str,
    target_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Tenant data the preflight modal can drop into ``context_excludes``.

    Per-scope:
    - ``whole_base`` returns the full tree of all groups + competences.
    - ``group`` returns the group's subtree (children + own competences).
    - ``competence_indicators`` returns no tree (the target competence is
      implicit) — frontend uses the empty list to skip the tree section.

    Specializations / divisions / company description are tenant-wide and
    always returned, so the chips render even when source_tree is empty.
    """
    from app.modules.company.models import Division, Tenant

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
        {"id": str(sid), "title": title} for (sid, title) in spec_q.all()
    ]

    div_q = await db.execute(
        select(Division.id, Division.name)
        .where(Division.tenant_id == tenant_id)
        .order_by(Division.name)
    )
    divisions = [{"id": str(did), "name": name} for (did, name) in div_q.all()]

    tenant_row = await db.get(Tenant, tenant_id)
    company_description = (
        (tenant_row.description if tenant_row else None) or None
    )

    source_tree: list[dict[str, Any]] = []
    related_specializations: list[dict[str, str]] = []
    ancestors: list[dict[str, str]] = []
    descendants: list[dict[str, Any]] = []
    sibling_competences: list[dict[str, str]] = []
    # HRP-114 re-spec: for group/indicators scope every spec + division in the
    # tenant carries an `is_linked` flag so the modal can show the full list
    # with the linked subset pre-checked. Derived ids drive both flags.
    linked_specialization_ids: set[uuid.UUID] = set()
    linked_division_ids: set[uuid.UUID] = set()
    if scope == "whole_base":
        snapshot = await _snapshot_tree(db, tenant_id)
        source_tree = snapshot.get("groups", [])
    elif scope == "group" and target_id is not None:
        group = await db.get(CompetenceGroup, target_id)
        if group is not None:
            snapshot = await _snapshot_group(db, group, tenant_id)
            grp = snapshot.get("group") or {}
            source_tree = [grp] if grp else []
            ancestors = grp.get("ancestors", []) or []
            descendants = grp.get("descendants", []) or []
            # HRP-114: related specs = subset of tenant specs linked via
            # matrix to any competence inside this group (or its subtree).
            scope_competence_ids = _collect_competence_ids_in_group(grp)
            related_specializations = await _fetch_related_specializations(
                db, tenant_id, competence_ids=scope_competence_ids
            )
            linked_specialization_ids = {
                uuid.UUID(s["id"]) for s in related_specializations
            }
            linked_division_ids = await _fetch_linked_division_ids(
                db,
                tenant_id,
                specialization_ids=linked_specialization_ids,
            )
    elif scope == "competence_indicators" and target_id is not None:
        comp = await db.get(Competence, target_id)
        if comp is not None:
            related_specializations = await _fetch_related_specializations(
                db, tenant_id, competence_ids=[comp.id]
            )
            linked_specialization_ids = {
                uuid.UUID(s["id"]) for s in related_specializations
            }
            linked_division_ids = await _fetch_linked_division_ids(
                db,
                tenant_id,
                specialization_ids=linked_specialization_ids,
            )
            if comp.group_id is not None:
                sib_q = await db.execute(
                    select(Competence.id, Competence.title).where(
                        Competence.group_id == comp.group_id,
                        Competence.id != comp.id,
                        Competence.is_active.is_(True),
                    )
                )
                sibling_competences = [
                    {"id": str(cid), "title": ctitle}
                    for (cid, ctitle) in sib_q.all()
                ]

    # HRP-114 re-spec: stamp every spec/division with `is_linked` whenever the
    # scope can derive linkage. whole_base / matrix have no notion of linkage,
    # so the flag stays false there — the frontend uses it only when the modal
    # surface that needs the dimmer/marker is rendered (group + indicators).
    scope_has_linkage = scope in ("group", "competence_indicators")
    if scope_has_linkage:
        specializations = [
            {**s, "is_linked": uuid.UUID(s["id"]) in linked_specialization_ids}
            for s in specializations
        ]
        divisions = [
            {**d, "is_linked": uuid.UUID(d["id"]) in linked_division_ids}
            for d in divisions
        ]

    # HRP-159: specialization_matrix preflight needs structured context
    # blocks (positions / divisions / existing competences) so the user can
    # toggle each item off before generation. Tenant-wide lists above stay
    # for parity with whole_base.
    positions: list[dict[str, str | None]] = []
    matrix_divisions: list[dict[str, str | bool]] = []
    existing_competences: list[dict[str, str]] = []
    specialization_description: str | None = None
    if scope == "specialization_matrix" and target_id is not None:
        spec = await db.get(DictionaryItem, target_id)
        # Tenant guard: origin (NULL tenant_id) is visible to everyone; tenant
        # specs are visible only to their own tenant. Anything else means the
        # caller supplied a foreign id — return an empty context block rather
        # than leak the description.
        spec_visible = (
            spec is not None
            and spec.type == "specialization"
            and (spec.tenant_id is None or spec.tenant_id == tenant_id)
        )
        if spec_visible and spec is not None:
            specialization_description = spec.description

            pos_q = await db.execute(
                select(Position.id, Position.title, Position.description, Position.division_id)
                .where(
                    Position.tenant_id == tenant_id,
                    Position.specialization_id == target_id,
                    Position.is_active.is_(True),
                )
                .order_by(Position.title)
            )
            related_division_ids: set[uuid.UUID] = set()
            for pid, ptitle, pdesc, pdiv in pos_q.all():
                positions.append(
                    {
                        "id": str(pid),
                        "title": ptitle,
                        "description": pdesc,
                    }
                )
                if pdiv is not None:
                    related_division_ids.add(pdiv)

            # Re-emit divisions with a flag marking those linked through any
            # of the specialization's positions so the modal can pre-check
            # them. Other tenant divisions stay available for opt-in.
            matrix_divisions = [
                {
                    "id": d["id"],
                    "name": d["name"],
                    "related": uuid.UUID(d["id"]) in related_division_ids,
                }
                for d in divisions
            ]

            comp_q = await db.execute(
                select(Competence.id, Competence.title, Competence.description)
                .join(
                    GradeCompetenceLink,
                    GradeCompetenceLink.competence_id == Competence.id,
                )
                .join(
                    GradeSpecialization,
                    GradeSpecialization.id == GradeCompetenceLink.grade_specialization_id,
                )
                .where(
                    GradeSpecialization.specialization_id == target_id,
                    GradeSpecialization.tenant_id == tenant_id,
                    Competence.is_active.is_(True),
                )
                .distinct()
                .order_by(Competence.title)
            )
            existing_competences = [
                {"id": str(cid), "title": ctitle, "description": cdesc or ""}
                for (cid, ctitle, cdesc) in comp_q.all()
            ]

    return {
        "specializations": specializations,
        "divisions": divisions,
        "company_description": company_description,
        "source_tree": source_tree,
        "related_specializations": related_specializations,
        "ancestors": ancestors,
        "descendants": descendants,
        "sibling_competences": sibling_competences,
        "positions": positions,
        "matrix_divisions": matrix_divisions,
        "existing_competences": existing_competences,
        "specialization_description": specialization_description,
    }


def _collect_competence_ids_in_group(group_snapshot: dict[str, Any]) -> list[uuid.UUID]:
    """Walk a `_snapshot_group` block and pull every competence id.

    Includes own competences + descendants (recursive). Used by
    ``_fetch_related_specializations`` so the related-specs query covers
    the whole subtree the LLM will see.
    """
    out: list[uuid.UUID] = []

    def walk(node: dict[str, Any]) -> None:
        for c in node.get("competences", []) or []:
            try:
                out.append(uuid.UUID(c["id"]))
            except (KeyError, ValueError, TypeError):
                continue
        for child in node.get("descendants", []) or []:
            walk(child)
        for child in node.get("children", []) or []:
            walk(child)

    walk(group_snapshot)
    return out


# ---------------------------------------------------------------------------
# Snapshot — frozen at create_session time
# ---------------------------------------------------------------------------


async def _snapshot_tree(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Compact JSON dump of the tenant's current competence tree (origin + own)."""
    groups_q = await db.execute(
        select(CompetenceGroup).where(
            (CompetenceGroup.tenant_id == tenant_id)
            | CompetenceGroup.tenant_id.is_(None),
            CompetenceGroup.is_active.is_(True),
        )
    )
    all_groups = list(groups_q.scalars().all())

    comps_q = await db.execute(
        select(Competence).where(
            (Competence.tenant_id == tenant_id) | Competence.tenant_id.is_(None),
            Competence.is_active.is_(True),
        )
    )
    all_comps = list(comps_q.scalars().all())

    by_parent: dict[uuid.UUID | None, list[CompetenceGroup]] = {}
    for g in all_groups:
        by_parent.setdefault(g.parent_id, []).append(g)
    comps_by_group: dict[uuid.UUID, list[Competence]] = {}
    for c in all_comps:
        comps_by_group.setdefault(c.group_id, []).append(c)

    def render(group: CompetenceGroup) -> dict[str, Any]:
        return {
            "id": str(group.id),
            "title": group.title,
            "description": group.description,
            "children": [render(c) for c in by_parent.get(group.id, [])],
            "competences": [
                {"id": str(c.id), "title": c.title, "description": c.description}
                for c in comps_by_group.get(group.id, [])
            ],
        }

    return {"groups": [render(g) for g in by_parent.get(None, [])]}


async def _snapshot_group(
    db: AsyncSession, group: CompetenceGroup, tenant_id: uuid.UUID
) -> dict[str, Any]:
    """Snapshot a single group + the surrounding library context.

    HRP-114: previously this only captured the group itself and its
    competences. The LLM now also receives the chain of ``ancestors`` (so
    it places new branches in the right hierarchical context) and the
    ``descendants`` subtree (so it avoids duplicating competences that
    already live below the target).

    HRP-155: each competence in the snapshot also carries its existing
    ``indicators`` so the LLM doesn't repeat them in augment mode and the
    worker can match indicators by (title, skill_level) against
    ``snapshot_id`` during the post-LLM annotation step.
    """
    comps_q = await db.execute(
        select(Competence).where(
            Competence.group_id == group.id, Competence.is_active.is_(True)
        )
    )
    own_comps = list(comps_q.scalars().all())
    own_indicators = await _fetch_indicators_for_competences(
        db, [c.id for c in own_comps]
    )
    own_competences = [
        {
            "id": str(c.id),
            "title": c.title,
            "description": c.description,
            "indicators": own_indicators.get(c.id, []),
        }
        for c in own_comps
    ]
    ancestors = await _fetch_group_ancestors(db, group)
    descendants = await _fetch_group_descendants(db, group, tenant_id)
    return {
        "group": {
            "id": str(group.id),
            "title": group.title,
            "description": group.description,
            "competences": own_competences,
            "ancestors": ancestors,
            "descendants": descendants,
        },
    }


async def _fetch_indicators_for_competences(
    db: AsyncSession, competence_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, str]]]:
    """Fetch active indicators grouped by competence id.

    HRP-155: snapshot helper. Returned shape per indicator is
    ``{"id", "title", "skill_level"}`` — the skill level is resolved to
    its title because that's what the LLM sees in prompts and what the
    matching helper uses to identify duplicates.
    """
    if not competence_ids:
        return {}
    rows = await db.execute(
        select(Indicator, SkillLevel.title)
        .join(SkillLevel, SkillLevel.id == Indicator.skill_level_id)
        .where(
            Indicator.competence_id.in_(competence_ids),
            Indicator.is_active.is_(True),
        )
    )
    out: dict[uuid.UUID, list[dict[str, str]]] = {}
    for ind, level_title in rows.all():
        out.setdefault(ind.competence_id, []).append(
            {
                "id": str(ind.id),
                "title": ind.title,
                "skill_level": level_title,
            }
        )
    return out


async def _fetch_related_specializations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    competence_ids: list[uuid.UUID],
) -> list[dict[str, str]]:
    """HRP-114: distinct specializations linked via matrix to any of the
    given competences. The result is the *subset* of tenant specializations
    that share a competence with the group / competence currently being
    generated — useful for the LLM to anchor on the right role context.

    Returns ``[{"id", "title"}]`` sorted by title; empty list when nothing
    matches.
    """
    if not competence_ids:
        return []
    rows = await db.execute(
        select(DictionaryItem.id, DictionaryItem.title)
        .distinct()
        .select_from(GradeCompetenceLink)
        .join(
            GradeSpecialization,
            GradeSpecialization.id
            == GradeCompetenceLink.grade_specialization_id,
        )
        .join(
            DictionaryItem,
            DictionaryItem.id == GradeSpecialization.specialization_id,
        )
        .where(
            GradeCompetenceLink.competence_id.in_(competence_ids),
            GradeSpecialization.tenant_id == tenant_id,
            effective_is_active_expr(tenant_id).is_(True),
        )
        .order_by(DictionaryItem.title)
    )
    return [{"id": str(sid), "title": title} for (sid, title) in rows.all()]


async def _fetch_linked_division_ids(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    specialization_ids: set[uuid.UUID],
) -> set[uuid.UUID]:
    """HRP-114 re-spec: divisions reachable from the given specializations
    via active positions inside this tenant.

    Division ← Position → Specialization. A division is "linked" to a scope
    (group / competence) when one of its positions references a spec that
    the scope's competences are bound to via matrix links. Empty input ⇒
    empty output.
    """
    if not specialization_ids:
        return set()
    rows = await db.execute(
        select(Position.division_id)
        .distinct()
        .where(
            Position.tenant_id == tenant_id,
            Position.specialization_id.in_(specialization_ids),
            Position.division_id.is_not(None),
            Position.is_active.is_(True),
        )
    )
    return {div_id for (div_id,) in rows.all() if div_id is not None}


async def _fetch_group_ancestors(
    db: AsyncSession, group: CompetenceGroup
) -> list[dict[str, str]]:
    """HRP-114: chain of parent groups up to the root, in root → leaf order.

    The LLM uses this to understand where the group sits in the library —
    e.g. ``"Backend → Languages → Python"`` so it doesn't suggest a
    "Python" competence at a level where it would duplicate the ancestor's
    intent.
    """
    chain: list[dict[str, str]] = []
    current = group
    seen: set[uuid.UUID] = set()
    while current.parent_id is not None and current.parent_id not in seen:
        seen.add(current.parent_id)
        parent = await db.get(CompetenceGroup, current.parent_id)
        if parent is None:
            break
        chain.append({"id": str(parent.id), "title": parent.title})
        current = parent
    chain.reverse()
    return chain


async def _fetch_group_descendants(
    db: AsyncSession, group: CompetenceGroup, tenant_id: uuid.UUID
) -> list[dict[str, Any]]:
    """HRP-114: nested children + their competences for the LLM context.

    Walks the subtree below ``group``. Only `is_active` rows visible to
    this tenant are included. Used by ``build_group_prompt`` so the model
    can avoid duplicating competences that already exist further down the
    branch.
    """
    groups_q = await db.execute(
        select(CompetenceGroup).where(
            (CompetenceGroup.tenant_id == tenant_id)
            | CompetenceGroup.tenant_id.is_(None),
            CompetenceGroup.is_active.is_(True),
        )
    )
    all_groups = list(groups_q.scalars().all())
    by_parent: dict[uuid.UUID | None, list[CompetenceGroup]] = {}
    for g in all_groups:
        by_parent.setdefault(g.parent_id, []).append(g)

    comps_q = await db.execute(
        select(Competence).where(
            (Competence.tenant_id == tenant_id) | Competence.tenant_id.is_(None),
            Competence.is_active.is_(True),
        )
    )
    all_comps = list(comps_q.scalars().all())
    comps_by_group: dict[uuid.UUID, list[Competence]] = {}
    for c in all_comps:
        comps_by_group.setdefault(c.group_id, []).append(c)

    # HRP-155: indicators per competence travel with the descendants block
    # so augment-mode title matching can recognise indicators that already
    # exist anywhere below the target group.
    indicators_by_comp = await _fetch_indicators_for_competences(
        db, [c.id for c in all_comps]
    )

    def render(g: CompetenceGroup) -> dict[str, Any]:
        return {
            "id": str(g.id),
            "title": g.title,
            "description": g.description,
            "children": [render(c) for c in by_parent.get(g.id, [])],
            "competences": [
                {
                    "id": str(c.id),
                    "title": c.title,
                    "indicators": indicators_by_comp.get(c.id, []),
                }
                for c in comps_by_group.get(g.id, [])
            ],
        }

    return [render(c) for c in by_parent.get(group.id, [])]


async def _snapshot_specialization(
    db: AsyncSession, tenant_id: uuid.UUID, spec_id: uuid.UUID
) -> dict[str, Any]:
    """Freeze grade attributes + existing matrix for the LLM context.

    Captured at session-create time so a refine/regenerate doesn't shift
    underneath the user if HR edits the matrix mid-flight.
    """
    spec = await db.get(DictionaryItem, spec_id)
    pairs_q = await db.execute(
        select(GradeSpecialization).where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == spec_id,
        )
    )
    pairs = list(pairs_q.scalars().all())
    pair_ids = [p.id for p in pairs]

    # `_ensure_specialization_accessible` already rejected matrix sessions
    # without grades, but `_snapshot_specialization` is called from other
    # contexts too (e.g. tests). Skip the link query when there are no pairs.
    matrix_by_pair: dict[uuid.UUID, list[dict[str, str]]] = {}
    if pair_ids:
        links_q = await db.execute(
            select(GradeCompetenceLink, Competence, SkillLevel)
            .join(Competence, Competence.id == GradeCompetenceLink.competence_id)
            .join(SkillLevel, SkillLevel.id == GradeCompetenceLink.skill_level_id)
            .where(GradeCompetenceLink.grade_specialization_id.in_(pair_ids))
        )
        for link, comp, lvl in links_q.all():
            matrix_by_pair.setdefault(link.grade_specialization_id, []).append(
                {"competence": comp.title, "skill_level": lvl.title}
            )

    # Mirror the UI ordering — the Specialization page uses the pair's
    # sort_index after HRP-57 P3 (drag-and-drop reorder), so the LLM sees
    # the same career ladder order the user does.
    grades_payload: list[dict[str, Any]] = []
    for p in pairs:
        grade_title = p.grade.title if p.grade else "?"
        grades_payload.append(
            {
                "grade_id": str(p.grade_id),
                "grade_title": grade_title,
                "sort_index": p.sort_index,
                "description": p.description,
                "requirements": p.requirements,
                "links": matrix_by_pair.get(p.id, []),
            }
        )
    grades_payload.sort(key=lambda g: g["sort_index"])

    return {
        "specialization": {
            "id": str(spec_id),
            "title": spec.title if spec else "",
            "description": spec.description if spec else None,
            "grades": grades_payload,
        },
    }


async def _snapshot_competence(
    db: AsyncSession,
    comp: Competence,
    *,
    specialization_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Freeze the competence + (optional) matrix context for the LLM.

    When the AI indicators session is launched from a matrix cell
    (HRP-102), the caller passes the source ``specialization_id`` so the
    prompt can include the spec's grades and the *sibling* competences
    already on that matrix — the LLM uses them to avoid duplication and
    tailor difficulty to the career ladder.
    """
    indicators_q = await db.execute(
        select(Indicator, SkillLevel.title)
        .join(SkillLevel, SkillLevel.id == Indicator.skill_level_id)
        .where(
            Indicator.competence_id == comp.id, Indicator.is_active.is_(True)
        )
    )
    snapshot: dict[str, Any] = {
        "competence": {
            "id": str(comp.id),
            "title": comp.title,
            "description": comp.description,
            "indicators": [
                {
                    "id": str(ind.id),
                    "title": ind.title,
                    # HRP-114 re-spec: result modal surfaces existing indicators
                    # next to new ones, so we ship the resolved skill_level
                    # title (matches the format used in _snapshot_group).
                    "skill_level": level_title,
                    "skill_level_id": str(ind.skill_level_id),
                }
                for (ind, level_title) in indicators_q.all()
            ],
        },
    }
    if specialization_id is not None and tenant_id is not None:
        snapshot["specialization_context"] = await _snapshot_matrix_context(
            db,
            tenant_id=tenant_id,
            specialization_id=specialization_id,
            target_competence_id=comp.id,
        )
    return snapshot


async def _snapshot_matrix_context(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    specialization_id: uuid.UUID,
    target_competence_id: uuid.UUID,
) -> dict[str, Any]:
    """Pull a flattened matrix context for the indicator-generation prompt.

    Returns the spec title, the grades wired to it, and the sibling
    competences already on the matrix (every competence other than the
    target). The LLM uses this to (a) avoid suggesting indicators that
    duplicate what sibling competences already cover, (b) calibrate
    indicator difficulty against the career ladder.
    """
    spec = await db.get(DictionaryItem, specialization_id)
    if spec is None or spec.type != "specialization":
        return {}

    pairs_q = await db.execute(
        select(GradeSpecialization).where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == specialization_id,
        )
    )
    pairs = list(pairs_q.scalars().all())
    grades_payload: list[dict[str, Any]] = []
    for p in pairs:
        if p.grade is None:
            continue
        grades_payload.append(
            {
                "grade_id": str(p.grade_id),
                "grade_title": p.grade.title,
                "sort_index": p.sort_index,
            }
        )
    grades_payload.sort(key=lambda g: g["sort_index"])

    sibling_titles: list[str] = []
    if pairs:
        from app.modules.grade_system.models import GradeCompetenceLink

        sibling_q = await db.execute(
            select(Competence.title)
            .join(
                GradeCompetenceLink,
                GradeCompetenceLink.competence_id == Competence.id,
            )
            .where(
                GradeCompetenceLink.grade_specialization_id.in_(
                    [p.id for p in pairs]
                ),
                Competence.id != target_competence_id,
                Competence.is_active.is_(True),
            )
            .distinct()
        )
        sibling_titles = sorted({t for (t,) in sibling_q.all() if t})

    return {
        "specialization_id": str(specialization_id),
        "specialization_title": spec.title,
        "grades": grades_payload,
        "sibling_competences": sibling_titles,
    }


# ---------------------------------------------------------------------------
# Create / get / list
# ---------------------------------------------------------------------------


async def get_active_session(
    db: AsyncSession, user_id: uuid.UUID
) -> CompetenceGenerationSession | None:
    result = await db.execute(
        select(CompetenceGenerationSession).where(
            CompetenceGenerationSession.user_id == user_id,
            CompetenceGenerationSession.status.in_(ACTIVE_STATUSES),
        )
    )
    return result.scalar_one_or_none()


async def list_other_active_sessions(
    db: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    """List active competence-generation sessions of *other* tenant users.

    Powers the PreflightModal: when a tenant admin opens /competences and
    someone else is already running a generation, we want to surface their
    name + scope so the second admin can wait or coordinate.
    """
    from app.modules.auth.models import User

    rows = await db.execute(
        select(CompetenceGenerationSession, User.first_name, User.last_name)
        .join(User, User.id == CompetenceGenerationSession.user_id)
        .where(
            CompetenceGenerationSession.tenant_id == tenant_id,
            CompetenceGenerationSession.user_id != user_id,
            CompetenceGenerationSession.status.in_(ACTIVE_STATUSES),
        )
        .order_by(CompetenceGenerationSession.created_at.desc())
    )
    return [
        {
            "session_id": sess.id,
            "user_id": sess.user_id,
            "user_full_name": " ".join(part for part in (first, last) if part).strip(),
            "scope": sess.scope,
            "target_id": sess.target_id,
            "status": sess.status,
            "created_at": sess.created_at,
        }
        for sess, first, last in rows.all()
    ]


def _count_payload_nodes(payload: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """Walk LLM payload, return (competence temp_ids, indicator temp_ids).

    Both `whole_base`/`group`/`specialization_matrix` (grouped tree) and
    `competence_indicators` (flat list) shapes are handled — the latter has
    no `groups` key and only contributes to indicator ids.
    """
    comp_ids: list[str] = []
    ind_ids: list[str] = []
    if not payload:
        return comp_ids, ind_ids

    def visit_group(g: dict[str, Any]) -> None:
        for ch in g.get("children", []) or []:
            visit_group(ch)
        for c in g.get("competences", []) or []:
            cid = c.get("temp_id")
            if cid:
                comp_ids.append(cid)
            for i in c.get("indicators", []) or []:
                iid = i.get("temp_id")
                if iid:
                    ind_ids.append(iid)

    for g in payload.get("groups", []) or []:
        visit_group(g)
    for i in payload.get("indicators", []) or []:
        iid = i.get("temp_id")
        if iid:
            ind_ids.append(iid)

    return comp_ids, ind_ids


def compute_session_counts(sess: CompetenceGenerationSession) -> dict[str, int]:
    """Derive totals + accepted/rejected counts for a history row.

    For `specialization_matrix`, `grades` is read from the frozen
    base_snapshot (LLM output doesn't repeat the grade list — it's an input).
    For applied sessions we trust `applied_result.created_*` as the
    authoritative accept count; otherwise we count `True` selections.
    """
    payload = sess.payload or {}
    comp_ids, ind_ids = _count_payload_nodes(payload)

    grades_total = 0
    if sess.scope == "specialization_matrix":
        snapshot_grades = (sess.base_snapshot or {}).get("specialization", {}).get(
            "grades", []
        ) or []
        grades_total = len(snapshot_grades)

    competences_total = len(comp_ids)
    indicators_total = len(ind_ids)
    is_indicator_scope = sess.scope == "competence_indicators"

    if sess.status == "applied" and sess.applied_result:
        if is_indicator_scope:
            accepted = len(sess.applied_result.get("created_indicators", []) or [])
            rejected = max(0, indicators_total - accepted)
        else:
            accepted = len(sess.applied_result.get("created_competences", []) or [])
            rejected = max(0, competences_total - accepted)
    else:
        sel = sess.selection_state or {}
        if is_indicator_scope:
            # `_apply_indicators_only` defaults missing-from-selection indicators
            # to *accepted* (default_when_missing=True). Mirror that here so a
            # fresh `ready` session displays as "all 14 ready to accept" rather
            # than "user rejected everything".
            accepted = sum(1 for tid in ind_ids if sel.get(tid, True))
            rejected = indicators_total - accepted
        else:
            accepted = sum(1 for tid in comp_ids if sel.get(tid))
            rejected = competences_total - accepted

    return {
        "grades": grades_total,
        "competences": competences_total,
        "indicators": indicators_total,
        "accepted": accepted,
        "rejected": rejected,
    }


def session_summary(sess: CompetenceGenerationSession) -> dict[str, Any]:
    """Compact input brief for the history row (no LLM payload bytes)."""
    params = sess.params or {}
    filenames = params.get("uploaded_filenames") or []
    return {
        "refinement_prompt": params.get("refinement_prompt"),
        "position_title": params.get("position_title"),
        "file_count": len(filenames) if isinstance(filenames, list) else 0,
        "with_indicators": bool(params.get("with_indicators", True)),
    }


async def list_sessions(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    target_id: uuid.UUID | None = None,
    scope: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List tenant generation sessions with derived counts.

    Visible to all tenant admins — AI history is a team log, not a per-user
    inbox. We pull full ORM rows (counts need `payload` + `applied_result` +
    `base_snapshot`), but the *response* drops `payload` entirely so the
    history list stays small over the wire.
    """
    from app.modules.auth.models import User

    stmt = (
        select(CompetenceGenerationSession, User.first_name, User.last_name)
        .join(User, User.id == CompetenceGenerationSession.user_id)
        .where(CompetenceGenerationSession.tenant_id == tenant_id)
    )
    if target_id is not None:
        stmt = stmt.where(CompetenceGenerationSession.target_id == target_id)
    if scope is not None:
        stmt = stmt.where(CompetenceGenerationSession.scope == scope)
    stmt = (
        stmt.order_by(CompetenceGenerationSession.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = await db.execute(stmt)

    result: list[dict[str, Any]] = []
    for sess, first, last in rows.all():
        full_name = " ".join(part for part in (first, last) if part).strip() or "—"
        result.append(
            {
                "id": sess.id,
                "user_id": sess.user_id,
                "user_full_name": full_name,
                "scope": sess.scope,
                "target_id": sess.target_id,
                "status": sess.status,
                "error_code": sess.error_code,
                "error_message": sess.error_message,
                "parent_session_id": sess.parent_session_id,
                "prompt_version": sess.prompt_version,
                "llm_model": sess.llm_model,
                "summary": session_summary(sess),
                "counts": compute_session_counts(sess),
                "created_at": sess.created_at,
                "updated_at": sess.updated_at,
                "finished_at": sess.finished_at,
            }
        )
    return result


async def get_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> CompetenceGenerationSession:
    sess = await db.get(CompetenceGenerationSession, session_id)
    if sess is None or sess.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if sess.user_id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your session")
    return sess


async def get_session_for_view(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID,
) -> CompetenceGenerationSession:
    """Tenant-scoped read for the AI history tab (HRP-71).

    Mirrors `list_sessions` visibility — any admin in the tenant can open any
    session in read-only mode. Mutating endpoints (refine / regenerate /
    apply / cancel / patch_selection) still go through `get_session` which
    additionally requires `sess.user_id == user_id`.
    """
    sess = await db.get(CompetenceGenerationSession, session_id)
    if sess is None or sess.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return sess


async def create_session(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: SessionCreate,
    *,
    cost: float | None = None,
    extra_params: dict[str, Any] | None = None,
) -> CompetenceGenerationSession:
    """Validate pre-conditions, snapshot the tree, persist row in `pending`.

    `extra_params` is merged into `params` *before* the row hits the DB so
    callers (e.g. the matrix multipart endpoint) can ship scope-specific
    inputs in one round-trip instead of doing a second commit.
    """

    if payload.scope == "whole_base":
        await _ensure_specializations_exist(db, tenant_id)
        if payload.target_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "whole_base does not accept target_id",
            )
        snapshot = await _snapshot_tree(db, tenant_id)

    elif payload.scope == "group":
        if payload.target_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "group scope requires target_id",
            )
        group = await _ensure_group_accessible(db, tenant_id, payload.target_id)
        snapshot = await _snapshot_group(db, group, tenant_id)

    elif payload.scope == "specialization_matrix":
        if payload.target_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "specialization_matrix scope requires target_id",
            )
        await _ensure_specialization_accessible(db, tenant_id, payload.target_id)
        levels = await _active_skill_levels(db, tenant_id)
        if not levels:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "error_code": "insufficient_data",
                    "message": (
                        "At least one active skill level is required to "
                        "generate a specialization matrix."
                    ),
                },
            )
        snapshot = await _snapshot_specialization(db, tenant_id, payload.target_id)

    elif payload.scope == "competence_indicators":
        if payload.target_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "competence_indicators scope requires target_id",
            )
        comp = await _ensure_competence_accessible(db, tenant_id, payload.target_id)
        if not comp.title:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "error_code": "insufficient_data",
                    "message": "Target competence has no title.",
                },
            )
        levels = await _active_skill_levels(db, tenant_id)
        if not levels:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "error_code": "insufficient_data",
                    "message": (
                        "At least one active skill level is required to "
                        "generate indicators."
                    ),
                },
            )
        # HRP-102: optional matrix context. We validate visibility up-front
        # so a missing/foreign spec id surfaces as a clean 404 instead of
        # silently dropping the spec block from the snapshot mid-session.
        # Matrix-empty specs (zero grades) are still allowed here — the
        # snapshot just degrades to an empty `specialization_context` and
        # the prompt skips the ladder block. Only `create_session(matrix)`
        # itself requires grades (that path uses `_ensure_…_accessible`).
        spec_context_id: uuid.UUID | None = payload.params.specialization_id
        if spec_context_id is not None:
            await _ensure_specialization_visible(db, tenant_id, spec_context_id)
        snapshot = await _snapshot_competence(
            db, comp, specialization_id=spec_context_id, tenant_id=tenant_id
        )

    else:  # pragma: no cover — Pydantic validates the literal
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown scope")

    params_dict = payload.params.model_dump(mode="json")
    if extra_params:
        params_dict.update(extra_params)
    # `billing_action` is the source of truth the Celery task reads to decide
    # what to consume on `ready`. The handler precheck above used the same
    # action — store it on the row so worker / tests don't have to recompute.
    params_dict["billing_action"] = _start_billing_action(payload.scope)
    if cost is not None:
        params_dict["cost"] = cost

    sess = CompetenceGenerationSession(
        tenant_id=tenant_id,
        user_id=user_id,
        scope=payload.scope,
        target_id=payload.target_id,
        params=params_dict,
        base_snapshot=snapshot,
        selection_state={},
        status="pending",
    )
    db.add(sess)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        # Triggered by ux_compgen_one_active_per_user partial unique index.
        # HRP-33: surface the live session's id/scope/target so the UI can
        # redirect the user to the in-flight review instead of swallowing
        # the conflict in a generic "session exists" toast that leaves them
        # stranded with no way to discover where the session actually lives.
        existing = await get_active_session(db, user_id)
        detail: dict[str, Any] = {
            "error_code": "active_session_exists",
            "message": "An active generation session already exists for this user.",
        }
        if existing is not None:
            position_id = (existing.params or {}).get("position_id")
            detail["session"] = {
                "id": str(existing.id),
                "scope": existing.scope,
                "target_id": (
                    str(existing.target_id) if existing.target_id else None
                ),
                "status": existing.status,
                "position_id": position_id,
            }
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from e
    await db.refresh(sess)
    return sess


# ---------------------------------------------------------------------------
# Selection-state cascade
# ---------------------------------------------------------------------------


def _walk_payload(
    payload: dict[str, Any] | None,
) -> tuple[dict[str, str | None], dict[str, list[str]]]:
    """Return (parent_of, children_of) maps keyed by `temp_id`.

    `payload` carries the LLM tree after the worker normalised every node
    with a `temp_id`. We walk it once to build cascade lookups.
    """
    parent_of: dict[str, str | None] = {}
    children_of: dict[str, list[str]] = {}
    if not payload:
        return parent_of, children_of

    def visit_group(group: dict[str, Any], parent: str | None) -> None:
        gid = group.get("temp_id")
        if not gid:
            return
        parent_of[gid] = parent
        children_of.setdefault(gid, [])
        if parent is not None:
            children_of.setdefault(parent, []).append(gid)

        for child in group.get("children", []) or []:
            visit_group(child, gid)
        for comp in group.get("competences", []) or []:
            cid = comp.get("temp_id")
            if not cid:
                continue
            parent_of[cid] = gid
            children_of.setdefault(cid, [])
            children_of.setdefault(gid, []).append(cid)
            for ind in comp.get("indicators", []) or []:
                iid = ind.get("temp_id")
                if not iid:
                    continue
                parent_of[iid] = cid
                children_of.setdefault(iid, [])
                children_of.setdefault(cid, []).append(iid)

    for group in payload.get("groups", []) or []:
        visit_group(group, None)

    # Indicator-only payload (competence_indicators scope)
    for ind in payload.get("indicators", []) or []:
        iid = ind.get("temp_id")
        if iid:
            parent_of[iid] = None
            children_of.setdefault(iid, [])

    return parent_of, children_of


def apply_selection_cascade(
    selection_state: dict[str, bool],
    payload: dict[str, Any] | None,
    node_id: str,
    selected: bool,
) -> dict[str, bool]:
    """Update selection: select propagates up; deselect propagates down."""
    parent_of, children_of = _walk_payload(payload)
    new_state = dict(selection_state)
    new_state[node_id] = selected

    if selected:
        cur = parent_of.get(node_id)
        while cur is not None:
            new_state[cur] = True
            cur = parent_of.get(cur)
    else:
        stack = list(children_of.get(node_id, []))
        while stack:
            cur = stack.pop()
            new_state[cur] = False
            stack.extend(children_of.get(cur, []))

    return new_state


async def update_selection(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    node_id: str,
    selected: bool,
) -> CompetenceGenerationSession:
    sess = await get_session(db, session_id, user_id=user_id, tenant_id=tenant_id)
    if sess.status != "ready":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot edit selection on session in status '{sess.status}'.",
        )
    # Cascade only over the boolean half of selection_state. _edits is a
    # sidecar dict that lives under `EDITS_KEY` and must round-trip
    # untouched — apply_selection_cascade is typed `dict[str, bool]` and
    # walking it over the magic key would corrupt the stored override.
    selection, edits = _split_state(sess.selection_state)
    cascaded = apply_selection_cascade(selection, sess.payload, node_id, selected)
    new_state: dict[str, Any] = dict(cascaded)
    if edits:
        new_state[EDITS_KEY] = edits
    sess.selection_state = new_state
    await db.commit()
    await db.refresh(sess)
    return sess


EDITS_KEY = "_edits"


def _split_state(
    raw: dict[str, Any] | None,
) -> tuple[dict[str, bool], dict[str, dict[str, str]]]:
    """Split a stored selection_state dict into (selection, edits).

    Selection_state is a JSONB blob that holds two shapes side-by-side:
    `{temp_id: bool}` for accept/reject and `{"_edits": {temp_id: {...}}}`
    for per-suggestion overrides. Splitting keeps every cascade/apply call
    site honest about which half it's reading.
    """
    if not raw:
        return {}, {}
    selection = {
        k: bool(v) for k, v in raw.items() if k != EDITS_KEY and isinstance(v, bool)
    }
    edits_raw = raw.get(EDITS_KEY) or {}
    edits: dict[str, dict[str, str]] = {}
    if isinstance(edits_raw, dict):
        for tid, payload in edits_raw.items():
            if isinstance(payload, dict):
                title = payload.get("title")
                if isinstance(title, str) and title:
                    edits[tid] = {"title": title}
    return selection, edits


async def replace_selection(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    selection_state: dict[str, bool],
    edits: dict[str, dict[str, str]] | None = None,
) -> CompetenceGenerationSession:
    """Bulk-replace the selection map + per-suggestion edits in one round-trip.

    The frontend matrix review modal applies cascade locally and ships the
    final dict; per-node PATCH would mean N requests on a 50-row diff.
    No cascade fixup here — the client owns that — but we still validate
    that every key references a node that exists in the payload to keep
    `apply_session` from materialising orphan ids.

    `edits` (HRP-71 phase 3) is a `{temp_id: {title}}` map of inline-rename
    overrides applied at materialisation time. It persists alongside the
    selection map under the magic `_edits` key so a single JSONB column
    holds both halves of the review state.
    """
    sess = await get_session(db, session_id, user_id=user_id, tenant_id=tenant_id)
    if sess.status != "ready":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot edit selection on session in status '{sess.status}'.",
        )

    parent_of, _ = _walk_payload(sess.payload)
    valid_ids = set(parent_of.keys())
    cleaned_selection = {
        k: bool(v) for k, v in selection_state.items() if k in valid_ids
    }
    cleaned_edits: dict[str, dict[str, str]] = {}
    for tid, override in (edits or {}).items():
        if tid not in valid_ids:
            continue
        title = override.get("title") if isinstance(override, dict) else None
        if isinstance(title, str) and title.strip():
            cleaned_edits[tid] = {"title": title.strip()}

    new_state: dict[str, Any] = dict(cleaned_selection)
    if cleaned_edits:
        new_state[EDITS_KEY] = cleaned_edits
    sess.selection_state = new_state
    await db.commit()
    await db.refresh(sess)
    return sess


# ---------------------------------------------------------------------------
# Cancel / clear / refine / regenerate
# ---------------------------------------------------------------------------


async def cancel_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> CompetenceGenerationSession:
    sess = await get_session(db, session_id, user_id=user_id, tenant_id=tenant_id)
    if sess.status in ("applied", "cancelled"):
        return sess
    sess.status = "cancelled"
    task_id = sess.celery_task_id
    await db.commit()
    await db.refresh(sess)
    # Tell the broker to drop the task: if still queued, the worker will skip
    # it; if mid-run, the worker checks status before billing consume and
    # exits without charging the tenant. terminate=False keeps the worker
    # process alive — we never want SIGKILL mid-LLM-call.
    if task_id:
        try:
            from app.core.celery_app import celery

            celery.control.revoke(task_id, terminate=False)
        except Exception:
            logger.exception("compgen revoke failed for task %s", task_id)
    # Notify any open drawer / status-button so they leave the "running" state
    # without waiting for the next 5s polling tick.
    from app.modules.ai_competence_generation.tasks import _broadcast_session_update

    await _broadcast_session_update(tenant_id, user_id, sess.id, "cancelled")
    return sess


async def clear_payload(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> CompetenceGenerationSession:
    sess = await get_session(db, session_id, user_id=user_id, tenant_id=tenant_id)
    sess.payload = None
    sess.selection_state = {}
    # HRP-97: Clear data is the explicit "start fresh" lever — drop the
    # refinement form snapshot + composed prompt so the next Try again /
    # Refine runs against the original brief, matching the spec's "data is
    # wiped … user clicks the clear data button" requirement.
    if sess.params:
        params = dict(sess.params)
        params.pop("refinement_form", None)
        params.pop("refinement_prompt", None)
        sess.params = params
    await db.commit()
    await db.refresh(sess)
    return sess


def _compose_refinement(refine: SessionRefine) -> str:
    """Flatten the four free-form refinement fields into one prompt block.

    Same flat format works for every scope including `specialization_matrix`
    — the scope-specific prompt builder receives this string as
    `refinement=` and decides how to interpret it. For
    `specialization_matrix` the model treats `add` as «extra competences»,
    `change` as «adjust grade-levels», and `exclude` as «drop these from
    the matrix».
    """
    parts: list[str] = []
    if refine.general:
        parts.append(f"General: {refine.general}")
    if refine.add:
        parts.append(f"Add: {refine.add}")
    if refine.change:
        parts.append(f"Change: {refine.change}")
    if refine.exclude:
        parts.append(f"Exclude: {refine.exclude}")
    return "\n".join(parts)


async def refine_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    refine: SessionRefine,
    cost: float | None = None,
) -> CompetenceGenerationSession:
    """Spawn a child session whose params include the refinement text."""
    parent = await get_session(db, session_id, user_id=user_id, tenant_id=tenant_id)
    if parent.status != "ready":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot refine a session in status '{parent.status}'.",
        )
    refinement_text = _compose_refinement(refine)
    if not refinement_text:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "At least one refinement field must be provided.",
        )

    # Mark parent as applied-by-refinement so the partial unique index
    # frees up; the child becomes the new active session. Flush right away
    # so the UPDATE lands before the child INSERT — otherwise SQLAlchemy
    # may emit INSERT first and trip ux_compgen_one_active_per_user in the
    # same transaction.
    parent.status = "cancelled"
    await db.flush()

    new_params = dict(parent.params or {})
    new_params["refinement_prompt"] = refinement_text
    # HRP-97: persist the structured form snapshot so the UI can re-hydrate
    # the panel after drawer reopen / page refresh / Try again. Dropping
    # `None` keys keeps the payload compact and lets future fields opt in
    # without polluting params with empty strings.
    new_params["refinement_form"] = {
        k: v
        for k, v in {
            "general": refine.general,
            "add": refine.add,
            "change": refine.change,
            "exclude": refine.exclude,
        }.items()
        if v
    }
    # Refine has a flat cost regardless of the parent's scope — one LLM call
    # on a smaller, focused context. Override any inherited billing_action,
    # but route specialization_matrix refines to their own billing category.
    new_params["billing_action"] = _refine_billing_action(parent.scope)
    if cost is not None:
        new_params["cost"] = cost
    else:
        new_params.pop("cost", None)

    child = CompetenceGenerationSession(
        tenant_id=tenant_id,
        user_id=user_id,
        scope=parent.scope,
        target_id=parent.target_id,
        params=new_params,
        base_snapshot=parent.base_snapshot,
        selection_state={},
        status="pending",
        parent_session_id=parent.id,
    )
    db.add(child)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        # ux_compgen_one_active_per_user — another active session beat us
        # in (double-click race, or stray active session in a different
        # scope).
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An active generation session already exists for this user.",
        ) from e
    await db.refresh(child)
    return child


async def regenerate_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    cost: float | None = None,
) -> CompetenceGenerationSession:
    """Spawn a child session inheriting the parent's params.

    Accepted parent states: `ready`, `error`, `applied`, `cancelled` —
    everything terminal plus `ready` (which we forcibly cancel to free the
    per-user partial unique index). `pending`/`running` parents are still
    in flight and would compete with the child, so they're rejected.
    """
    parent = await get_session(db, session_id, user_id=user_id, tenant_id=tenant_id)
    if parent.status in ("pending", "running"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot regenerate a session in status '{parent.status}'.",
        )
    if parent.status == "ready":
        parent.status = "cancelled"
        # Flush the UPDATE before the child INSERT so the partial unique
        # index sees parent as already-cancelled within this transaction.
        await db.flush()
    new_params = dict(parent.params or {})
    # Inherit the parent's billing intent: regenerating a refine costs a
    # refine; regenerating an initial whole_base costs whole_base again.
    # If the parent predates CR14 (no billing_action stored), fall back to
    # scope-derived action.
    if not new_params.get("billing_action"):
        new_params["billing_action"] = _start_billing_action(parent.scope)
    if cost is not None:
        new_params["cost"] = cost
    else:
        new_params.pop("cost", None)
    child = CompetenceGenerationSession(
        tenant_id=tenant_id,
        user_id=user_id,
        scope=parent.scope,
        target_id=parent.target_id,
        params=new_params,
        base_snapshot=parent.base_snapshot,
        selection_state={},
        status="pending",
        parent_session_id=parent.id,
    )
    db.add(child)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        # ux_compgen_one_active_per_user — another active session beat us
        # in (double-click race, or stray active session in a different
        # scope).
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An active generation session already exists for this user.",
        ) from e
    await db.refresh(child)
    return child


# ---------------------------------------------------------------------------
# Apply — persist selected nodes into the real competence tree
# ---------------------------------------------------------------------------


async def _resolve_skill_level(
    db: AsyncSession, tenant_id: uuid.UUID, key: str
) -> uuid.UUID | None:
    """Match a skill_level by i18n_key first, then by lower(title)."""
    result = await db.execute(
        select(SkillLevel.id)
        .where(
            and_(
                (SkillLevel.tenant_id == tenant_id) | SkillLevel.tenant_id.is_(None),
                SkillLevel.is_active.is_(True),
                (SkillLevel.i18n_key == key.lower()) | (SkillLevel.title.ilike(key)),
            )
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


def _is_selected(
    selection: dict[str, bool],
    node: dict[str, Any],
    default_when_missing: bool = False,
) -> bool:
    tid = node.get("temp_id")
    if not tid:
        return default_when_missing
    return bool(selection.get(tid, default_when_missing))


def _resolve_title(node: dict[str, Any], edits: dict[str, dict[str, str]]) -> str:
    """Pick the inline-edit title override (HRP-71 phase 3) or fall back to the LLM title."""
    tid = node.get("temp_id")
    if tid:
        override = edits.get(tid)
        if override:
            edited = override.get("title")
            if isinstance(edited, str) and edited.strip():
                return edited.strip()
    return node["title"]


async def apply_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    publish: bool,
    idempotency_key: str,
    actor_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Materialise selected nodes into competence_groups/competences/indicators.

    Idempotent on `idempotency_key`: a second call with the same key on an
    already-applied session returns the original `applied_result` without
    re-creating rows.
    """
    sess = await get_session(db, session_id, user_id=user_id, tenant_id=tenant_id)

    if sess.status == "applied":
        if sess.applied_idempotency_key == idempotency_key and sess.applied_result:
            return sess.applied_result
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Session already applied with a different idempotency_key.",
        )

    if sess.status != "ready":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot apply a session in status '{sess.status}'.",
        )

    payload = sess.payload or {}
    selection, edits = _split_state(sess.selection_state)

    created_groups: list[uuid.UUID] = []
    created_competences: list[uuid.UUID] = []
    created_indicators: list[uuid.UUID] = []
    created_grade_links: list[uuid.UUID] = []

    if sess.scope == "competence_indicators":
        if sess.target_id is None:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Indicator-scope session has no target competence.",
            )
        await _apply_indicators_only(
            db,
            tenant_id=tenant_id,
            competence_id=sess.target_id,
            payload=payload,
            selection=selection,
            edits=edits,
            publish=publish,
            created_indicators=created_indicators,
        )
    elif sess.scope == "specialization_matrix":
        if sess.target_id is None:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Matrix session has no target specialization.",
            )
        # HRP-33: when launched from a Position, fold all generated competences
        # under one group named after the position so /competences shows them
        # as a single coherent bucket. Without a position, keep the LLM's
        # group split (existing specialization-page flow).
        position_group_title: str | None = None
        params_full = sess.params or {}
        if params_full.get("position_id"):
            position_group_title = (params_full.get("position_title") or "").strip()
            if not position_group_title:
                position = await db.get(Position, uuid.UUID(params_full["position_id"]))
                position_group_title = position.title if position else None
        await _apply_specialization_matrix(
            db,
            tenant_id=tenant_id,
            specialization_id=sess.target_id,
            payload=payload,
            selection=selection,
            edits=edits,
            publish=publish,
            position_group_title=position_group_title,
            created_groups=created_groups,
            created_competences=created_competences,
            created_indicators=created_indicators,
            created_grade_links=created_grade_links,
        )
    else:
        # Resolve target group for `group` scope; for `whole_base` we walk
        # the `groups` list at the root (parent=None).
        target_parent_id: uuid.UUID | None = None
        if sess.scope == "group":
            target_parent_id = sess.target_id

        for group_node in payload.get("groups", []) or []:
            await _apply_group_recursive(
                db,
                tenant_id=tenant_id,
                parent_id=target_parent_id,
                node=group_node,
                selection=selection,
                edits=edits,
                publish=publish,
                created_groups=created_groups,
                created_competences=created_competences,
                created_indicators=created_indicators,
            )

    # Audit
    db.add(
        CompetenceTreeAuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="ai_generation_applied",
            element_type="generation_session",
            element_id=sess.id,
            payload={
                "scope": sess.scope,
                "target_id": str(sess.target_id) if sess.target_id else None,
                "publish": publish,
                "groups": [str(g) for g in created_groups],
                "competences": [str(c) for c in created_competences],
                "indicators": [str(i) for i in created_indicators],
                "grade_links": [str(g) for g in created_grade_links],
                "idempotency_key": idempotency_key,
            },
        )
    )

    sess.status = "applied"
    sess.applied_idempotency_key = idempotency_key
    sess.applied_result = {
        "created_groups": [str(g) for g in created_groups],
        "created_competences": [str(c) for c in created_competences],
        "created_indicators": [str(i) for i in created_indicators],
        "created_grade_links": [str(g) for g in created_grade_links],
        "idempotency_key": idempotency_key,
    }
    await db.commit()
    return sess.applied_result


async def _apply_group_recursive(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    node: dict[str, Any],
    selection: dict[str, bool],
    edits: dict[str, dict[str, str]],
    publish: bool,
    created_groups: list[uuid.UUID],
    created_competences: list[uuid.UUID],
    created_indicators: list[uuid.UUID],
) -> None:
    """Persist `node` (group) and recurse into children/competences if selected.

    A group is materialised when itself or any of its descendants is checked
    — otherwise nothing under it is selected and we can skip entirely.
    """
    if not _has_selected_descendant(node, selection) and not _is_selected(
        selection, node
    ):
        return

    snapshot_id = node.get("snapshot_id")
    title = _resolve_title(node, edits)
    if snapshot_id:
        # Existing group — re-use its DB id.
        try:
            real_id = uuid.UUID(snapshot_id)
        except ValueError:
            real_id = None
        if real_id is not None and (await db.get(CompetenceGroup, real_id)) is not None:
            current_id = real_id
        else:
            current_id = await _create_group(
                db,
                tenant_id=tenant_id,
                parent_id=parent_id,
                title=title,
                description=node.get("description"),
                created_groups=created_groups,
            )
    else:
        current_id = await _create_group(
            db,
            tenant_id=tenant_id,
            parent_id=parent_id,
            title=title,
            description=node.get("description"),
            created_groups=created_groups,
        )

    for comp_node in node.get("competences", []) or []:
        if not _is_selected(selection, comp_node):
            continue
        await _apply_competence(
            db,
            tenant_id=tenant_id,
            group_id=current_id,
            comp_node=comp_node,
            selection=selection,
            edits=edits,
            publish=publish,
            created_competences=created_competences,
            created_indicators=created_indicators,
        )

    for sub in node.get("children", []) or []:
        await _apply_group_recursive(
            db,
            tenant_id=tenant_id,
            parent_id=current_id,
            node=sub,
            selection=selection,
            edits=edits,
            publish=publish,
            created_groups=created_groups,
            created_competences=created_competences,
            created_indicators=created_indicators,
        )


def _has_selected_descendant(node: dict[str, Any], selection: dict[str, bool]) -> bool:
    if _is_selected(selection, node):
        return True
    for sub in node.get("children", []) or []:
        if _has_selected_descendant(sub, selection):
            return True
    for comp in node.get("competences", []) or []:
        if _is_selected(selection, comp):
            return True
        for ind in comp.get("indicators", []) or []:
            if _is_selected(selection, ind):
                return True
    return False


async def _create_group(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    title: str,
    description: str | None,
    created_groups: list[uuid.UUID],
) -> uuid.UUID:
    g = CompetenceGroup(
        title=title,
        description=description,
        parent_id=parent_id,
        tenant_id=tenant_id,
        is_active=True,
        can_deactivate=True,
    )
    db.add(g)
    await db.flush()
    created_groups.append(g.id)
    return g.id


async def _apply_competence(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    comp_node: dict[str, Any],
    selection: dict[str, bool],
    edits: dict[str, dict[str, str]],
    publish: bool,
    created_competences: list[uuid.UUID],
    created_indicators: list[uuid.UUID],
) -> None:
    # HRP-155: in group-scope augment mode the worker tags competences that
    # already exist in the library with ``snapshot_id``. Reuse the DB row
    # instead of creating a duplicate; only the newly suggested indicators
    # (those without ``snapshot_id``) get appended underneath.
    #
    # Snapshot-tagged competences are rendered locked in the review tree
    # (HRP-123/124) so the user cannot rename or edit them inline — any
    # rename made through the legacy `_edits` map is intentionally
    # ignored here. Same convention as `_apply_group_recursive` for
    # snapshot-tagged groups. Permitting rename-on-existing would be a
    # separate feature.
    comp_snapshot_id = comp_node.get("snapshot_id")
    comp_id: uuid.UUID | None = None
    if comp_snapshot_id:
        try:
            comp_id = uuid.UUID(str(comp_snapshot_id))
        except ValueError:
            comp_id = None
        if comp_id is not None:
            existing = await db.get(Competence, comp_id)
            # ``tenant_id is None`` covers origin (platform-shared) rows
            # that are visible to every tenant — those still match.
            if existing is None or existing.tenant_id not in (tenant_id, None):
                comp_id = None
    if comp_id is None:
        comp = Competence(
            title=_resolve_title(comp_node, edits),
            description=comp_node.get("description"),
            group_id=group_id,
            tenant_id=tenant_id,
            is_active=True,
            is_published=publish,
        )
        db.add(comp)
        await db.flush()
        created_competences.append(comp.id)
        comp_id = comp.id

    for ind_node in comp_node.get("indicators", []) or []:
        # HRP-155: indicators that match an existing DB row stay locked in
        # the tree (`snapshot_id` set on the suggestion). Don't re-create
        # them on apply regardless of selection state — the original row
        # already lives under this competence.
        if ind_node.get("snapshot_id"):
            continue
        if not _is_selected(selection, ind_node, default_when_missing=True):
            continue
        sl_id = await _resolve_skill_level(
            db, tenant_id, ind_node.get("skill_level", "")
        )
        if sl_id is None:
            continue
        ind = Indicator(
            title=_resolve_title(ind_node, edits),
            skill_level_id=sl_id,
            competence_id=comp_id,
            tenant_id=tenant_id,
            is_active=True,
        )
        db.add(ind)
        await db.flush()
        created_indicators.append(ind.id)


async def _apply_indicators_only(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    competence_id: uuid.UUID,
    payload: dict[str, Any],
    selection: dict[str, bool],
    edits: dict[str, dict[str, str]],
    publish: bool,
    created_indicators: list[uuid.UUID],
) -> None:
    """Apply selected indicators to an existing competence.

    The `publish` flag controls visibility of the new indicators:
    * `True` — `is_active=True` (visible immediately, like manually created).
    * `False` — `is_active=False` (added as drafts; user activates later).
    """
    for ind_node in payload.get("indicators", []) or []:
        if not _is_selected(selection, ind_node, default_when_missing=True):
            continue
        sl_id = await _resolve_skill_level(
            db, tenant_id, ind_node.get("skill_level", "")
        )
        if sl_id is None:
            continue
        ind = Indicator(
            title=_resolve_title(ind_node, edits),
            skill_level_id=sl_id,
            competence_id=competence_id,
            tenant_id=tenant_id,
            is_active=publish,
        )
        db.add(ind)
        await db.flush()
        created_indicators.append(ind.id)


async def _apply_specialization_matrix(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    specialization_id: uuid.UUID,
    payload: dict[str, Any],
    selection: dict[str, bool],
    edits: dict[str, dict[str, str]],
    publish: bool,
    position_group_title: str | None = None,
    created_groups: list[uuid.UUID],
    created_competences: list[uuid.UUID],
    created_indicators: list[uuid.UUID],
    created_grade_links: list[uuid.UUID],
) -> None:
    """Materialise selected matrix entries into the competence tree + matrix.

    Each selected competence becomes:

    * a new `Competence` row under a fresh `CompetenceGroup` per matrix
      group node (existing groups with the same title are reused),
    * `Indicator` rows for each selected indicator on that competence,
    * `GradeCompetenceLink` rows on the spec×grade pairs declared in the
      LLM's `grade_levels` map.

    Grades are matched by title (case-insensitive). Skill levels also by
    title via `_resolve_skill_level`. Anything that fails to resolve is
    silently skipped — partial application is fine because the user can
    refine and rerun.

    NOTE: This is a *create-only* path — every selected node becomes a fresh
    `Competence`/`Indicator` row, even when a competence with the same title
    already exists in the tenant's tree. We rely on the user's checkbox
    review to drop duplicates before pressing Apply (the LLM's snapshot
    block already lists the existing matrix, so the model knows which
    titles to avoid). A future iteration may dedup against
    `Competence.title` per-tenant; tracked separately.
    """
    pairs_q = await db.execute(
        select(GradeSpecialization).where(
            GradeSpecialization.tenant_id == tenant_id,
            GradeSpecialization.specialization_id == specialization_id,
        )
    )
    pairs = list(pairs_q.scalars().all())
    if not pairs:
        return

    pairs_by_grade_title: dict[str, GradeSpecialization] = {}
    for p in pairs:
        if p.grade and p.grade.title:
            pairs_by_grade_title[p.grade.title.strip().lower()] = p

    # HRP-33: position-launched matrix collapses LLM group split into one
    # named bucket. We resolve it once up-front: if the user already ran
    # AI Generate on this position before, reuse the existing group instead
    # of stacking duplicates with identical titles in /competences. The
    # group is created on first need so an all-deselected payload doesn't
    # leave an empty group behind.
    shared_group_id: uuid.UUID | None = None
    if position_group_title is not None:
        existing_q = await db.execute(
            select(CompetenceGroup.id).where(
                CompetenceGroup.tenant_id == tenant_id,
                CompetenceGroup.parent_id.is_(None),
                CompetenceGroup.title == position_group_title,
                CompetenceGroup.is_active.is_(True),
            )
        )
        existing_id = existing_q.scalar_one_or_none()
        if existing_id is not None:
            shared_group_id = existing_id

    for group_node in payload.get("groups", []) or []:
        if not _has_selected_descendant(group_node, selection) and not _is_selected(
            selection, group_node
        ):
            continue

        if position_group_title is None:
            group_id = await _create_group(
                db,
                tenant_id=tenant_id,
                parent_id=None,
                title=_resolve_title(group_node, edits),
                description=group_node.get("description"),
                created_groups=created_groups,
            )
        else:
            if shared_group_id is None:
                shared_group_id = await _create_group(
                    db,
                    tenant_id=tenant_id,
                    parent_id=None,
                    title=position_group_title,
                    description=group_node.get("description"),
                    created_groups=created_groups,
                )
            group_id = shared_group_id

        for comp_node in group_node.get("competences", []) or []:
            if not _is_selected(selection, comp_node):
                continue

            comp = Competence(
                title=_resolve_title(comp_node, edits),
                description=comp_node.get("description"),
                group_id=group_id,
                tenant_id=tenant_id,
                is_active=True,
                is_published=publish,
            )
            db.add(comp)
            await db.flush()
            created_competences.append(comp.id)

            for ind_node in comp_node.get("indicators", []) or []:
                if not _is_selected(selection, ind_node, default_when_missing=True):
                    continue
                sl_id = await _resolve_skill_level(
                    db, tenant_id, ind_node.get("skill_level", "")
                )
                if sl_id is None:
                    continue
                ind = Indicator(
                    title=_resolve_title(ind_node, edits),
                    skill_level_id=sl_id,
                    competence_id=comp.id,
                    tenant_id=tenant_id,
                    is_active=True,
                )
                db.add(ind)
                await db.flush()
                created_indicators.append(ind.id)

            for grade_title, level_title in (
                comp_node.get("grade_levels") or {}
            ).items():
                pair = pairs_by_grade_title.get(grade_title.strip().lower())
                if pair is None:
                    continue
                sl_id = await _resolve_skill_level(db, tenant_id, level_title)
                if sl_id is None:
                    continue
                link = GradeCompetenceLink(
                    grade_specialization_id=pair.id,
                    competence_id=comp.id,
                    skill_level_id=sl_id,
                )
                db.add(link)
                await db.flush()
                created_grade_links.append(link.id)
