"""Prompt builders for AI competence generation sessions.

Each scope has its own builder returning `(system_prompt, user_prompt)`.
The system prompt carries the role definition + global rules; the user
prompt carries this run's inputs (company context, source tree, refinement
text). Few-shot examples sit between them — embedded inside the system
prompt so they survive across the OpenAI/Anthropic/Gemini message split.

Output contract is enforced by `GeneratedTreeSchema` /
`GeneratedIndicatorsSchema` — `llm_client.generate_json(..., schema=...)`
appends the JSON Schema to whatever system prompt we produce here.

The output-language directive is NOT part of these templates: tasks.py
appends `ai_settings_service.build_language_directive(...)` to the built
system prompt, so generated content follows the tenant's
`content_language` while the prompt text itself stays English (HRP-480).
"""

from __future__ import annotations

import json
from typing import Any

from app.modules.ai_competence_generation._examples import (
    GROUP_EXAMPLES,
    INDICATORS_EXAMPLES,
    TREE_EXAMPLES,
)

PROMPT_VERSION = "hrp144.v1"

_BASE_DEFINITIONS = (
    "You are an HR expert who designs competency frameworks for software "
    "and operations teams.\n\n"
    "Definitions:\n"
    "- Competence: a bundle of knowledge, skills, and traits required to "
    "perform a specific kind of work. Either a hard_skill (technical), "
    "soft_skill (interpersonal), or unique_skill (domain-specific).\n"
    "- Competence group: a thematic grouping of competences (and optional "
    "subgroups). The tree root is implicit.\n"
    "- Indicator: an observable, measurable behaviour that demonstrates a "
    "given skill_level for a competence."
)

_TREE_RULES = (
    "Tree-building rules:\n"
    "- Never duplicate a competence that already appears in the source tree.\n"
    "- Do not modify or rename the source tree — only return new groups and "
    "competences.\n"
    "- Do not turn a competence into a group or vice versa.\n"
    "- If a group would contain more than five competences, split it into "
    "thematic subgroups.\n"
    "- Required competences from the user's input must be present in the "
    "source tree or in your answer (skip them only if a near-synonym already "
    "exists).\n"
    "- Each competence must declare a `type` from: hard_skill, soft_skill, "
    "unique_skill.\n"
    "- HRP-144: when indicators are requested, every competence must carry "
    "AT LEAST 3 indicators per skill level — see the indicator rules below."
)

_INDICATOR_RULES = (
    "Indicator rules:\n"
    "- Only the skill levels listed by the user are valid; do not invent new "
    "ones.\n"
    "- Produce AT LEAST 3 indicators per skill level for every competence — "
    "fewer is unacceptable, more is fine when meaningfully distinct.\n"
    "- Indicators progress from minimal knowledge at the lowest level to full "
    "mastery at the highest; each higher level implicitly includes the "
    "behaviours of the levels below it.\n"
    "- Each indicator must be observable in real work — tie it to a concrete "
    "task or deliverable, not to theoretical knowledge.\n"
    "- An indicator should let an interviewer verify whether the candidate "
    "can apply the skill, not just whether they have heard of it.\n"
    "- Calibrate per level:\n"
    "  * Basic level = correct, minimally sufficient execution with no "
    "errors and no negative side-effects.\n"
    "  * Intermediate / Middle level = stability + autonomy: handles the "
    "task reliably without supervision.\n"
    "  * Advanced / High level = influence on outcomes, prevents problems "
    "ahead of time, strengthens the team around them.\n"
    "- Each indicator must start with an action verb (Knows, Understands, "
    "Applies, Designs, Coaches, ...).\n"
    "- Do not repeat indicators that already exist on the competence."
)


def _format_examples(examples: list[tuple[dict, dict]]) -> str:
    lines: list[str] = []
    for i, (q, a) in enumerate(examples, start=1):
        lines.append(f"Example {i} input:")
        lines.append(json.dumps(q, ensure_ascii=False, indent=2))
        lines.append(f"Example {i} output:")
        lines.append(json.dumps(a, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def _refinement_block(refinement: str | None) -> str:
    if not refinement:
        return ""
    return f"\n\nUser refinement notes (apply these to your answer):\n{refinement}"


# ---------------------------------------------------------------------------
# Whole-base / group / indicators
# ---------------------------------------------------------------------------


def build_tree_prompt(
    *,
    specializations: list[str],
    divisions: list[str],
    projects: list[str],
    company: str | None,
    source_tree: dict[str, Any],
    with_indicators: bool,
    refinement: str | None,
    required_elements: list[str] | None = None,
) -> tuple[str, str]:
    sections = [
        _BASE_DEFINITIONS,
        _TREE_RULES,
    ]
    if with_indicators:
        # HRP-144: indicator-rules block must travel with the tree prompt
        # whenever ``with_indicators`` is on — otherwise the LLM has no
        # spec on minimum count, level calibration, or phrasing.
        sections.append(_INDICATOR_RULES)
    sections.append(
        "Task: extend the source competence tree with new groups and "
        "competences that reflect the user's inputs. "
        + (
            "Each new competence must include AT LEAST 3 indicators for every "
            "skill_level mentioned in the user input."
            if with_indicators
            else "Do not include indicators in your answer."
        )
    )
    sections.append(_format_examples(TREE_EXAMPLES))
    system = "\n\n".join(sections)

    user_payload = {
        "specializations": specializations,
        "divisions": divisions,
        "projects": projects,
        "company": company,
        "required_elements": required_elements or [],
        "with_indicators": with_indicators,
        "source_tree": source_tree,
    }
    user = "Inputs:\n" + json.dumps(user_payload, ensure_ascii=False, indent=2)
    user += _refinement_block(refinement)
    return system, user


def build_group_prompt(
    *,
    group_title: str,
    group_description: str | None,
    source_tree: dict[str, Any],
    with_indicators: bool,
    refinement: str | None,
    required_elements: list[str] | None = None,
    specialization: str | None = None,
    specializations: list[str] | None = None,
    related_specializations: list[str] | None = None,
    divisions: list[str] | None = None,
    company: str | None = None,
    ancestors: list[str] | None = None,
    descendants: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Prompt for `group` scope.

    HRP-114: tenant-wide context (``specializations``, ``divisions``,
    ``company``) is optional — the preflight modal can drop each via
    ``context_excludes``. When a category is excluded the worker passes
    ``None`` / empty list and the key is omitted from the payload entirely.

    ``related_specializations``: the subset of tenant specs whose matrices
    reference any competence already in this group's subtree. Highlighting
    them separately lets the LLM anchor on the role context that actually
    uses these competences.

    ``ancestors`` / ``descendants``: surrounding library structure so the
    LLM understands where the group sits and which competences already
    exist below it (avoid duplicates).
    """
    sections = [_BASE_DEFINITIONS, _TREE_RULES]
    if with_indicators:
        sections.append(_INDICATOR_RULES)  # HRP-144
    # HRP-155: when ``source_tree`` carries existing subgroups / competences
    # the operator opted into augment mode — the LLM should both extend the
    # group with new branches AND fill gaps inside the existing ones. The
    # worker post-processes the response to attach ``snapshot_id`` to nodes
    # whose title matches the snapshot, so the LLM doesn't need to echo any
    # identifiers — matching is title-based.
    has_existing_subtree = bool(source_tree)
    if has_existing_subtree:
        task_lines = [
            f"Task: enrich the group '{group_title}' in augment mode. "
            "Two kinds of output are expected and they may be combined "
            "in one response:",
            (
                "1. New branches — brand-new subgroups and competences "
                "not present in `source_tree`."
            ),
            (
                "2. Augment existing items — for any subgroup already in "
                "`source_tree` you MAY return it with NEW child competences "
                "added underneath (reuse the subgroup's exact title so it "
                "is recognised). For any competence already in "
                "`source_tree` you MAY return it with NEW indicators added "
                "(reuse the competence's exact title; do NOT repeat "
                "indicators already listed under that competence in "
                "`source_tree`)."
            ),
            (
                "Augment override: the Tree-building rule 'Never duplicate "
                "a competence that already appears in the source tree' is "
                "RELAXED for this run — re-emit existing subgroups and "
                "competences ONLY when you have new children or indicators "
                "to attach beneath them."
            ),
            (
                "Each new or augmenting competence must include AT LEAST 3 "
                "indicators per skill level."
                if with_indicators
                else "Do not include indicators."
            ),
        ]
        sections.append("\n".join(task_lines))
    else:
        sections.append(
            f"Task: extend the group '{group_title}' with new "
            "competences (and subgroups, if needed). Return the group "
            "itself in your answer with only the *new* competences "
            "underneath. "
            + (
                "Each competence must include AT LEAST 3 indicators per " "skill level."
                if with_indicators
                else "Do not include indicators."
            )
        )
    sections.append(_format_examples(GROUP_EXAMPLES))
    system = "\n\n".join(sections)

    user_payload: dict[str, Any] = {
        "group": {"title": group_title, "description": group_description},
        "specialization": specialization,
        "required_elements": required_elements or [],
        "with_indicators": with_indicators,
        "source_tree": source_tree,
    }
    if specializations:
        user_payload["specializations"] = specializations
    if related_specializations:
        user_payload["related_specializations"] = related_specializations
    if divisions:
        user_payload["divisions"] = divisions
    if company:
        user_payload["company"] = company
    if ancestors:
        user_payload["ancestor_groups"] = ancestors
    if descendants:
        user_payload["descendant_groups"] = descendants
    user = "Inputs:\n" + json.dumps(user_payload, ensure_ascii=False, indent=2)
    user += _refinement_block(refinement)
    return system, user


_MATRIX_RULES = (
    "Matrix-building rules:\n"
    "- Every competence must declare a `grade_levels` map covering ALL "
    "grades from the input list.\n"
    "- Use only the skill levels listed by the user; do not invent new ones.\n"
    "- Levels must be monotonically non-decreasing from junior to senior "
    "grades — a higher grade can never require a lower level than a junior "
    "grade for the same competence.\n"
    "- Do not duplicate competences that already appear in the existing "
    "matrix. You may extend existing competences with finer indicators only "
    "when explicitly asked.\n"
    "- Group competences thematically; if a group would hold more than five "
    "competences, split it.\n"
    "- Each competence must declare a `type` from: hard_skill, soft_skill, "
    "unique_skill.\n"
    "- Each competence must include indicators covering every input "
    "skill_level — AT LEAST 3 indicators per level (HRP-144).\n"
    "- Indicator phrasing must follow the indicator rules: observable on "
    "real work, action-verb first, calibrated per level (basic = correct "
    "minimum / intermediate = stable + autonomous / advanced = influence "
    "on outcomes), with each higher level implicitly including lower ones."
)


def build_specialization_matrix_prompt(
    *,
    specialization: str,
    specialization_description: str | None = None,
    grades: list[str],
    skill_levels: list[str],
    company: str | None,
    existing_matrix: dict[str, Any],
    responsibilities: str | None,
    daily_tasks: str | None,
    weekly_tasks: str | None,
    kpi: str | None,
    requirements_text: str | None,
    parsed_files: str | None,
    refinement: str | None,
    indicators_for_existing: bool = False,
    positions: list[dict[str, Any]] | None = None,
    divisions: list[str] | None = None,
    existing_competences: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """System+user prompt for `specialization_matrix` scope.

    `existing_matrix` lets the LLM avoid suggesting duplicates and respect
    levels already configured. `parsed_files` is the concatenated plain-text
    extract from uploaded PDFs / DOCX / spreadsheets — large but capped at
    50 000 characters by `ai.file_parsing`.

    HRP-119: ``indicators_for_existing`` flips the "extend existing competence
    with extra indicators" branch on. The matrix rules already allow this when
    explicitly asked — this flag is that explicit ask.

    HRP-159: ``positions`` / ``divisions`` / ``existing_competences`` /
    ``specialization_description`` are the structured context blocks the user
    can toggle from the preflight modal. Each is dropped entirely when the
    worker passes ``None`` / empty list, so the prompt only carries data the
    user explicitly opted into. ``positions`` is a list of
    ``{title, description}`` dicts (positions linked to this specialization),
    ``divisions`` a list of division names (company-wide, optionally filtered
    by the positions' divisions), and ``existing_competences`` a list of
    ``{title, description}`` dicts for competences already present in the
    matrix.
    """

    task_lines = [
        f"Task: design the competence matrix for the '{specialization}' "
        "specialization. Return groups of competences; each competence "
        "must include indicators per skill level AND a `grade_levels` "
        "map (grade title → skill_level title) describing how the "
        "expectation rises along the career ladder."
    ]
    if indicators_for_existing:
        task_lines.append(
            "Additionally: for every competence already present in "
            "`existing_matrix`, return the SAME competence title with "
            "its existing `grade_levels` preserved, and only NEW indicators "
            "in the `indicators` array (do not repeat indicators that "
            "already appear under that competence). Do not change the "
            "competence's title or `type`."
        )
    system = "\n\n".join(
        [
            _BASE_DEFINITIONS,
            _MATRIX_RULES,
            "\n".join(task_lines),
        ]
    )

    user_payload: dict[str, Any] = {
        "specialization": specialization,
        "grades": grades,
        "skill_levels": skill_levels,
        "company": company,
        "existing_matrix": existing_matrix,
        "responsibilities": responsibilities,
        "daily_tasks": daily_tasks,
        "weekly_tasks": weekly_tasks,
        "kpi": kpi,
        "requirements_text": requirements_text,
    }
    if specialization_description:
        user_payload["specialization_description"] = specialization_description
    if positions:
        user_payload["positions"] = positions
    if divisions:
        user_payload["divisions"] = divisions
    if existing_competences:
        user_payload["existing_competences"] = existing_competences
    user = "Inputs:\n" + json.dumps(user_payload, ensure_ascii=False, indent=2)
    if parsed_files:
        user += "\n\nUploaded reference documents (plain text):\n" + parsed_files
    user += _refinement_block(refinement)
    return system, user


def build_indicators_prompt(
    *,
    competence_title: str,
    competence_type: str,
    skill_levels: list[str],
    parents: list[str],
    existing_indicators: list[dict[str, str]],
    refinement: str | None,
    required_elements: list[str] | None = None,
    specialization_context: dict[str, Any] | None = None,
    specializations: list[str] | None = None,
    related_specializations: list[str] | None = None,
    divisions: list[str] | None = None,
    company: str | None = None,
    sibling_competences: list[str] | None = None,
) -> tuple[str, str]:
    """Build the indicator-generation prompt.

    HRP-102: ``specialization_context`` is an optional matrix snapshot
    (``{specialization_title, grades, sibling_competences}``) that the
    caller passes when the session was launched from a spec-matrix cell.
    Including the spec title + career-ladder grades lets the LLM
    calibrate indicator difficulty; listing sibling competences nudges
    it away from duplicating ideas that already belong elsewhere on
    that matrix.

    HRP-114: tenant-wide context (``specializations``, ``divisions``,
    ``company``) and ``sibling_competences`` (other competences in the
    same group) are optional — the preflight modal can drop each via
    ``context_excludes``. When excluded the worker passes ``None`` /
    empty list and the key is omitted from the payload entirely.
    """
    task = (
        f"Task: produce additional indicators for the competence "
        f"'{competence_title}'. Cover every skill_level listed by "
        "the user. Do not regenerate indicators that already exist."
    )
    if specialization_context:
        spec_title = specialization_context.get("specialization_title")
        if spec_title:
            task += (
                f" The competence belongs to the '{spec_title}' specialization "
                "matrix — calibrate indicator difficulty to the listed grades "
                "and avoid overlapping with sibling competences."
            )
    system = "\n\n".join(
        [
            _BASE_DEFINITIONS,
            _INDICATOR_RULES,
            task,
            _format_examples(INDICATORS_EXAMPLES),
        ]
    )
    user_payload: dict[str, Any] = {
        "competence": competence_title,
        "competence_type": competence_type,
        "skill_levels": skill_levels,
        "parents": parents,
        "existing_indicators": existing_indicators,
        "required_elements": required_elements or [],
    }
    if specializations:
        user_payload["specializations"] = specializations
    if related_specializations:
        user_payload["related_specializations"] = related_specializations
    if divisions:
        user_payload["divisions"] = divisions
    if company:
        user_payload["company"] = company
    if sibling_competences:
        user_payload["sibling_competences_in_group"] = sibling_competences
    if specialization_context:
        user_payload["specialization_context"] = {
            "specialization": specialization_context.get("specialization_title"),
            "grades": [
                g.get("grade_title")
                for g in (specialization_context.get("grades") or [])
                if g.get("grade_title")
            ],
            "sibling_competences": specialization_context.get(
                "sibling_competences", []
            ),
        }
    user = "Inputs:\n" + json.dumps(user_payload, ensure_ascii=False, indent=2)
    user += _refinement_block(refinement)
    return system, user
