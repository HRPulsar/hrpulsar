"""``SKILL.md`` for a step (HRP-760, REFACTOR_PLAN §4.4): the prompt side.

``SKILL.md = skeleton of the pack + the company's context``. The skeleton
(``ai_workforce.skill_templates``) fixes the construction - a pipeline
with verification for strong codes, generation with a human acceptance
for draft codes; the context is what an empty chat does not have: the
indicators the company itself wrote for the competences behind the
step's capabilities (its own definition of "done well"), the step's
attributes (who answers for it, reversibility, output type) and the
handover point - a step a person signs off, or one that changes the
outside world, must end with a handover, never with the act.

The platform does not execute the skill (decision 2026-08-06): the file
goes into the client's own agent runner. The language of the file follows
the tenant's content language through the standard directive; nothing
here is localized through the UI catalogs.

English only: this file reaches the public tree.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_workforce.skill_templates import PIPELINE_PACKS, skeleton_for
from app.modules.competence.models import Competence, Indicator
from app.modules.primitives.models import CompetencePrimitive, Primitive
from app.modules.work.models import WorkContainer, WorkStep

# v2 (2026-09-10, R7): findings beyond the reference are findings, not noise.
PROMPT_VERSION = "v2skill.v2"
# Bounds on the company context in the prompt: enough to shape the
# criteria, not the whole competence tree.
MAX_COMPETENCES = 8
MAX_INDICATORS_PER_COMPETENCE = 12
# Agent Skills frontmatter limits: name ≤ 64 chars of [a-z0-9-],
# description ≤ 1024 chars.
NAME_MAX = 64
DESCRIPTION_MAX = 1024
# When no pack overlaps the step (P13 alone), the construction still has
# to come from somewhere: acceptance for a draft verdict, pipeline else.
FALLBACK_ACCEPTANCE_PACK = "drafting"
FALLBACK_PIPELINE_PACK = "extraction"


def pack_for_step(codes: set[str], packs: Sequence[dict[str, Any]]) -> dict | None:
    """The pack whose set contains the step's codes; failing that, the one
    with the largest overlap, catalog order breaking ties. ``None`` when
    nothing overlaps (or the step has no code)."""
    best: dict | None = None
    best_overlap = 0
    for pack in packs:
        pack_codes = set(pack["primitive_codes"])
        if codes and codes <= pack_codes:
            return pack
        overlap = len(codes & pack_codes)
        if overlap > best_overlap:
            best, best_overlap = pack, overlap
    return best


def fallback_pack_code(primitives: Sequence[Primitive]) -> str:
    if any(p.ai_verdict == "draft" for p in primitives):
        return FALLBACK_ACCEPTANCE_PACK
    return FALLBACK_PIPELINE_PACK


def needs_handover(step: WorkStep) -> bool:
    """§4.4: signed off by a person, or acting in the outside world."""
    return step.responsibility in ("formal", "regulatory") or (
        step.output_type == "external_change"
    )


def slugify(name: str, fallback: str = "") -> str:
    """ASCII slug; a name with no latin letter at all (a non-latin tenant
    whose model ignored the transliteration rule) falls back to
    ``fallback``, then to a constant."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug and fallback:
        slug = re.sub(r"[^a-z0-9]+", "-", fallback.lower()).strip("-")
    return (slug or "step-skill")[:NAME_MAX].rstrip("-")


def _strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block. Without a closing fence there
    is no frontmatter - a body opening on a thematic break keeps its text."""
    if text.startswith("---"):
        _, sep, rest = text[3:].partition("\n---\n")
        return rest.lstrip("\n") if sep else text
    return text


def _skeleton_body(pack_code: str) -> str:
    """The skeleton without its YAML frontmatter - the frontmatter is
    rendered here from the model's name and description."""
    return _strip_frontmatter(skeleton_for(pack_code))


async def load_indicators(
    db: AsyncSession, tenant_id: uuid.UUID, primitive_ids: Sequence[uuid.UUID]
) -> list[tuple[str, list[str]]]:
    """``(competence title, [indicator titles])`` for the active competences
    the tenant reads - its own and the shared library's - that exercise the
    step's capabilities: the company's own "done well", bounded so the
    prompt stays small."""
    if not primitive_ids:
        return []
    competences = (
        await db.execute(
            select(Competence.id, Competence.title)
            .join(
                CompetencePrimitive, CompetencePrimitive.competence_id == Competence.id
            )
            .where(
                CompetencePrimitive.visible_to(tenant_id),
                CompetencePrimitive.primitive_id.in_(list(primitive_ids)),
                Competence.is_active.is_(True),
                Competence.applicable_to != "agent",
            )
            .group_by(Competence.id, Competence.title)
            # The competences that exercise most of the step's capabilities
            # first; the alphabet only breaks ties.
            .order_by(func.count().desc(), Competence.title, Competence.id)
            .limit(MAX_COMPETENCES)
        )
    ).all()
    if not competences:
        return []
    rows = await db.execute(
        select(Indicator.competence_id, Indicator.title)
        .where(
            Indicator.competence_id.in_([c.id for c in competences]),
            Indicator.visible_to(tenant_id),
            Indicator.is_active.is_(True),
        )
        .order_by(Indicator.competence_id, Indicator.sort_index, Indicator.title)
    )
    by_competence: dict[uuid.UUID, list[str]] = {}
    for competence_id, title in rows.all():
        bucket = by_competence.setdefault(competence_id, [])
        if len(bucket) < MAX_INDICATORS_PER_COMPETENCE:
            bucket.append(title)
    return [(c.title, by_competence.get(c.id, [])) for c in competences]


def build_system_prompt(
    pack_code: str, step: WorkStep, extras: Sequence[str] = ()
) -> str:
    handover = (
        "- This step is signed off by a person or changes the outside world: "
        "the skill must end with a handover to a named role (the draft, what "
        "was checked, the open questions) and must never perform the outside "
        "action itself.\n"
        if needs_handover(step)
        else ""
    )
    parts = [
        "You write an Agent Skill - a SKILL.md file - for one step of a "
        "company's process. An AI agent (a coding agent, a chat assistant or "
        "the company's own runner) will follow it to perform the step on the "
        "company's behalf; the platform itself does not execute it.\n\n"
        "Fill the skeleton below with the company's context. Keep its section "
        "structure and headings; replace every {{placeholder}} with concrete "
        "content from the context, or with a clearly marked assumption where "
        "the context is silent. Never invent facts about the company.\n\n"
        "Rules:\n"
        "- The criteria and checks come from the company's own indicators of "
        "the competences involved: rewrite them as checks an agent can apply.\n"
        "- The boundaries come from the step's attributes: who answers for it, "
        "how reversible it is, what kind of output it produces.\n"
        f"{handover}"
        "- The reference set limits what the agent certifies, not what it "
        "notices: a finding outside the reference that would stop the owner "
        "from accepting the result is reported in the section the skeleton "
        "gives it, as a finding without a verdict - never dropped as out of "
        "scope.\n"
        "- Address the agent in the second person, imperative, concrete; no "
        "marketing language.\n\n"
        "- Never mention the internal capability codes (P1, B2 and the like) "
        "in the file: say what the agent does, not which code it is.\n\n"
        "Return JSON with three fields: name (a slug for the skill: ASCII "
        "lowercase latin letters, digits and hyphens only - transliterate if "
        "the step title is not latin - at most 64 characters, derived from "
        "the step title), description (one sentence saying when to use this "
        "skill, at most 1024 characters), body (the filled skeleton as "
        "markdown, without any YAML frontmatter).\n\n"
        "Skeleton:\n\n" + _skeleton_body(pack_code),
        *extras,
    ]
    return "\n\n".join(parts)


def build_user_prompt(
    *,
    container: WorkContainer,
    step: WorkStep,
    primitives: Sequence[Primitive],
    indicators: Sequence[tuple[str, list[str]]],
) -> str:
    lines = [
        f"Process: {container.title} ({container.type})",
    ]
    if container.description:
        lines.append(f"Process description: {container.description}")
    if container.goal:
        lines.append(f"Goal: {container.goal}")
    lines += [
        "",
        f"Step {step.position}: {step.title}",
    ]
    if step.description:
        lines.append(f"Step description: {step.description}")
    if step.notes:
        lines.append(f"Notes: {step.notes}")
    lines += [
        "Attributes: "
        f"accountability={step.responsibility}, "
        f"reversibility={step.reversibility or 'unknown'}, "
        f"hours_per_run={'unknown' if step.hours_per_run is None else step.hours_per_run}, "
        f"runs_per_year={'unknown' if step.runs_per_year is None else step.runs_per_year}, "
        f"output={step.output_type}, "
        f"handover_required={'yes' if needs_handover(step) else 'no'}",
        "",
        "Capabilities the step requires:",
    ]
    lines += [
        f"- {p.code} {p.title_en}" + (f": {p.scope_en}" if p.scope_en else "")
        for p in primitives
    ]
    lines.append("")
    if indicators:
        lines.append(
            "The company's own indicators for the competences that exercise "
            "these capabilities (what 'done well' means here):"
        )
        for title, items in indicators:
            lines.append(f"- {title}")
            lines += [f"  - {item}" for item in items]
    else:
        lines.append(
            "The company has no competences mapped to these capabilities yet: "
            "derive the criteria from the step itself and mark them as assumptions."
        )
    return "\n".join(lines)


def render(
    pack_code: str,
    name: str,
    description: str,
    body: str,
    *,
    fallback_name: str = "",
) -> tuple[str, str]:
    """``(skill_name, SKILL.md)``: the frontmatter is ours, the body the
    model's - minus any frontmatter the model added despite the rule. The
    description goes through ``json.dumps`` - a valid YAML double-quoted
    scalar whatever it contains."""
    slug = slugify(name, fallback_name)
    body = _strip_frontmatter(body.strip())
    construction = "pipeline" if pack_code in PIPELINE_PACKS else "acceptance"
    text = (
        "---\n"
        f"name: {slug}\n"
        f"description: {json.dumps(description[:DESCRIPTION_MAX], ensure_ascii=False)}\n"
        f"pack: {pack_code}\n"
        f"construction: {construction}\n"
        "---\n\n"
        f"{body.strip()}\n"
    )
    return slug, text
