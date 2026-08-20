"""Prompt templates for AI-powered features."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.ai_settings.models import TenantAISettings

SYSTEM_COMPETENCE = """You are an HR expert specializing in competency framework design.
You create structured competency models for organizations.
Always respond with valid JSON only, no additional text."""

GENERATE_COMPETENCES = """Generate a competency framework for the specialization "{specialization}".

Company context: {company_description}
Activity fields: {activity_fields}

Generate 3-5 competence groups, each containing 2-4 competences.
Each competence should have a type: "hard_skill", "soft_skill", or "unique_skill".

Return JSON in this exact format:
```json
[
  {{
    "title": "Group Name",
    "description": "Group description",
    "competences": [
      {{
        "title": "Competence Name",
        "description": "What this competence means",
        "type": "hard_skill",
        "indicators": [
          {{"title": "Observable behavior at basic level", "skill_level": "basic"}},
          {{"title": "Observable behavior at intermediate level", "skill_level": "intermediate"}},
          {{"title": "Observable behavior at advanced level", "skill_level": "advanced"}}
        ]
      }}
    ]
  }}
]
```"""

GENERATE_INDICATORS = """Generate behavioral indicators for the competence "{competence_title}".

Context: {context}

Generate 2-3 indicators for each skill level (basic, intermediate, advanced).
Each indicator should describe an observable, measurable behavior.

Return JSON:
```json
[
  {{"title": "Indicator description", "skill_level": "basic", "weight": 1}},
  {{"title": "Indicator description", "skill_level": "intermediate", "weight": 2}},
  {{"title": "Indicator description", "skill_level": "advanced", "weight": 3}}
]
```"""

SUGGEST_PDP = """Based on the following assessment results, suggest a personal development plan.

Employee's weak competences (low scores):
{weak_competences}

Employee's strong competences (high scores):
{strong_competences}

Create 3-5 development items focusing on improving weak areas while leveraging strengths.

Return JSON:
```json
[
  {{
    "title": "Development goal title",
    "description": "What to achieve and why",
    "competence_title": "Related competence",
    "materials": [
      {{"title": "Resource name", "format": "course/book/article/video", "link": ""}}
    ]
  }}
]
```"""

# --- Position generation ---

SYSTEM_POSITION = """You are an HR organizational design expert.
You create structured job positions for organizations based on their structure, specializations, and grade levels.
Always respond with valid JSON only, no additional text."""

GENERATE_POSITIONS = """Generate job positions for an organization.

Company: {company_description}
Industry: {industry}
Company size: {company_size}
Activity fields: {activity_fields}

Existing specializations: {specializations}
Existing grades: {grades}
Existing divisions: {divisions}
Already existing positions (DO NOT duplicate these): {existing_positions}

Generate {count} positions that would complement the existing organizational structure.
Each position should logically combine a grade level with a specialization where applicable.
Not every position needs a grade or specialization — some positions are cross-functional.

Return JSON:
```json
[
  {{
    "title": "Position title",
    "description": "Brief description of responsibilities (1-2 sentences)",
    "specialization_title": "Matching specialization name or null",
    "grade_title": "Matching grade name or null",
    "division_name": "Suggested division name or null"
  }}
]
```"""


# --- Settings-aware system-prompt builders ---


def _augment(base: str, tenant_settings: TenantAISettings | None) -> str:
    if tenant_settings is None:
        return base

    from app.modules.ai_settings.service import build_system_prompt_extras

    extras = build_system_prompt_extras(tenant_settings)
    if not extras:
        return base
    return "\n\n".join([base, *extras])


def build_system_competence(
    tenant_settings: TenantAISettings | None = None,
) -> str:
    return _augment(SYSTEM_COMPETENCE, tenant_settings)


def build_system_position(
    tenant_settings: TenantAISettings | None = None,
) -> str:
    return _augment(SYSTEM_POSITION, tenant_settings)


SYSTEM_DEV_LOOP = """You are an HR analytics advisor for a talent-development platform.
You are given a snapshot of a company's development loop: assessment coverage,
competence gaps below the grade bar, development plans and their state.
Write for a busy HR manager. Respond with plain text only — no markdown,
no headings, no lists."""

DEV_LOOP_SUMMARY = """Here is the current development-loop snapshot as JSON:

{payload}

Field notes: "stages" is the assess -> gaps -> develop -> close pipeline;
"findings" are detected problems ("gaps_without_plan" = employees scoring
below the grade bar with no open development plan, "pdp_overdue" = plans past
their deadline, "pdp_stuck_review" = plans sitting in review/returned,
"assessment_coverage" = active employees without a recent assessment).

In 3-5 sentences: describe the overall state of the loop, name the single
most pressing problem (mention concrete employee names if provided), and say
which action to take first. Do not repeat raw numbers the reader already
sees; interpret them."""


def build_system_dev_loop(
    tenant_settings: TenantAISettings | None = None,
) -> str:
    return _augment(SYSTEM_DEV_LOOP, tenant_settings)


SYSTEM_MY_LOOP = """You are a supportive career coach inside a talent-development
platform, writing directly to an employee about their own development data.
Be encouraging and concrete; never use judgmental labels (no "weak", "poor",
"underperformer"). Frame gaps as growth opportunities. Respond with plain
text only — no markdown, no headings, no lists."""

MY_LOOP_SUMMARY = """Here is the employee's personal development snapshot as JSON:

{payload}

Field notes: "stages" covers their latest assessment, competence gaps below
the bar, active development plan and confirmed closures; "strengths" lists
their top and rare competences; "growth" shows the next grade on their career
ladder and what is still missing; "history" is their assessment score
timeline.

In 3-5 sentences, speaking to the employee as "you": acknowledge what is
going well (strengths, progress, closed gaps), then suggest what to focus on
in the next quarter and the first concrete step to take. Do not repeat raw
numbers the reader already sees; interpret them."""


def build_system_my_loop(
    tenant_settings: TenantAISettings | None = None,
) -> str:
    return _augment(SYSTEM_MY_LOOP, tenant_settings)
