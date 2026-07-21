"""AI service functions for recruitment module.

Resume parsing and vacancy profile generation via LLM.
"""

import logging
import re
from typing import Any

from pydantic import BaseModel

from app.modules.ai.llm_client import LLMOutputTruncatedError, generate_json
from app.modules.recruitment.prompts import (
    GENERATE_PROFILE,
    GENERATE_QUESTIONS,
    PARSE_RESUME,
    SYSTEM_RECRUITER,
)

logger = logging.getLogger(__name__)

# Output budget for recruitment LLM calls. Profiles, question sets and
# interview analyses are tree-shaped JSON in the tenant language; Cyrillic
# output tokenizes at ~1-1.5 chars/token and blows past the 8192-token
# default on rich vacancies (prod 2026-07-08: vacancy profile truncated
# mid-string → JSONDecodeError). A full profile (up to 15 competences ×
# 3 questions × 3 reference answers, plus legacy mirrors) can exceed 16k
# output tokens in Cyrillic, so ask for 32768 and let llm_client clamp
# per model: Sonnet allows 64000, gpt-4o tops out at 16384, Haiku at 8192.
RECRUITMENT_MAX_TOKENS = 32768

# Appended to the profile prompt on a truncation retry — trims the output
# to what every provider can emit within its clamped budget.
_COMPACT_PROFILE_SUFFIX = (
    "\n\nIMPORTANT: The previous attempt exceeded the output budget and was "
    "cut off. Generate a COMPACT profile this time — this overrides the "
    "'8-15 competences' rule above: at most 8 competences, exactly 3 "
    "indicators and exactly 3 questions per competence, and keep every "
    "answer example under 25 words. Do not sacrifice JSON validity."
)


def _as_dict(value: dict | list | BaseModel) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        first = value[0] if value else {}
        return first if isinstance(first, dict) else {}
    return value


async def parse_resume_text(text: str) -> dict:
    """Parse resume text into structured data via LLM.

    Returns dict with: first_name, last_name, contacts, experience,
    education, skills, languages, certificates, summary, plus
    ``current_position`` / ``years_of_experience`` / ``location`` at the
    top level (HRP-181 REDO Stage 3 — needed by the canonical Candidate
    denormalised columns).
    """
    prompt = PARSE_RESUME.format(resume_text=text)
    result = await generate_json(
        prompt,
        system=SYSTEM_RECRUITER,
        temperature=0.2,
        max_tokens=RECRUITMENT_MAX_TOKENS,
    )
    payload = _as_dict(result)
    _normalise_resume_payload(payload)
    return payload


def _normalise_resume_payload(payload: dict) -> None:
    """Backfill top-level denormalised fields when the LLM omits them.

    Stage 3 callers (``finalize_candidates_from_parsed`` and the candidate
    card) read ``current_position`` / ``years_of_experience`` / ``location``
    off the top level. The prompt asks for them, but every provider misses
    a field eventually — compute a deterministic fallback so the canonical
    columns stay populated.
    """
    experience = payload.get("experience")
    if (
        not payload.get("current_position")
        and isinstance(experience, list)
        and experience
    ):
        head = experience[0]
        if isinstance(head, dict):
            payload["current_position"] = head.get("position") or head.get("role")

    if isinstance(experience, list):
        for entry in experience:
            if not isinstance(entry, dict):
                continue
            position = entry.get("position") or entry.get("role")
            if position:
                entry.setdefault("position", position)
                entry.setdefault("role", position)
            _normalise_experience_entry(entry)

    contacts = payload.get("contacts")
    if not payload.get("location") and isinstance(contacts, dict):
        loc = contacts.get("location")
        if loc:
            payload["location"] = loc


def _normalise_experience_entry(entry: dict) -> None:
    """Map legacy experience keys onto the card contract (HRP-346).

    The card renders ``start_date`` / ``end_date`` / ``description``; the
    pre-HRP-346 prompt emitted ``period`` and ``achievements`` instead, and
    providers may still fall back to those names. Split/copy them rather
    than dropping the data.
    """
    if not entry.get("start_date") and not entry.get("end_date"):
        period = entry.get("period")
        if isinstance(period, str) and period.strip():
            parts = _split_period(period.strip())
            entry["start_date"] = parts[0] or None
            if len(parts) > 1:
                entry["end_date"] = parts[1] or None

    if not entry.get("description"):
        achievements = entry.get("achievements")
        if isinstance(achievements, list):
            achievements = "\n".join(str(a) for a in achievements if a)
        if isinstance(achievements, str) and achievements.strip():
            entry["description"] = achievements.strip()


# Spaced separator first — a bare ``-`` would split intra-date hyphens
# ("2020-01 - 2023-05") and ``to`` without word boundaries matches inside
# "October". The year-pair fallback handles compact "2020-2023".
_PERIOD_SPACED_SEP = re.compile(r"\s+(?:—|–|-|to)\s+")
_PERIOD_YEAR_PAIR = re.compile(r"^(\d{4})\s*[—–-]\s*(.+)$")


def _split_period(period: str) -> list[str]:
    parts = _PERIOD_SPACED_SEP.split(period, maxsplit=1)
    if len(parts) > 1:
        return parts
    match = _PERIOD_YEAR_PAIR.match(period)
    if match:
        return [match.group(1), match.group(2)]
    return [period]


async def generate_vacancy_profile(vacancy_data: dict) -> dict:
    """Generate competency profile for a vacancy via LLM.

    Input: dict with title, specialization, grade, description,
    tasks_main, tasks_additional, tasks_kpi, vacancy_id, language.

    Returns dict with vacancy_id, language, competences list, coverage_note.
    """
    industry_context = ""
    if vacancy_data.get("industry_context"):
        industry_context = f"- Industry context: {vacancy_data['industry_context']}"

    # HRP-135 REDO: attachments_text already carries one "# Attachment: …"
    # header per file plus the extracted body. Wrap it in a header so the
    # model treats it as additional reference material, not the spec
    # itself. Empty string ⇒ section disappears entirely.
    attachments_section = ""
    attachments_text = (vacancy_data.get("attachments_text") or "").strip()
    if attachments_text:
        attachments_section = (
            "Attachments uploaded by the recruiter — treat as supplementary "
            "reference material (job spec, intake notes, etc.):\n\n"
            f"{attachments_text}"
        )

    # HRP-134 REDO: free-form recruiter clarification collected by the
    # "Generate competence matrix" modal — passes the recruiter's intent
    # straight to the model so the resulting list leans in the requested
    # direction. Empty string ⇒ section disappears entirely.
    clarification_section = ""
    clarification = (vacancy_data.get("clarification") or "").strip()
    if clarification:
        clarification_section = (
            "Recruiter clarification — incorporate this guidance when "
            "selecting and shaping competences:\n\n"
            f"{clarification}"
        )

    prompt = GENERATE_PROFILE.format(
        title=vacancy_data.get("title", ""),
        specialization=vacancy_data.get("specialization", "Not specified"),
        grade=vacancy_data.get("grade", "Not specified"),
        description=vacancy_data.get("description", "Not specified"),
        tasks_main=vacancy_data.get("tasks_main", "Not specified"),
        tasks_additional=vacancy_data.get("tasks_additional", "Not specified"),
        tasks_kpi=vacancy_data.get("tasks_kpi", "Not specified"),
        requirements=vacancy_data.get("requirements", "Not specified"),
        responsibilities=vacancy_data.get("responsibilities", "Not specified"),
        conditions=vacancy_data.get("conditions", "Not specified"),
        attachments_section=attachments_section,
        clarification_section=clarification_section,
        industry_context=industry_context,
        vacancy_id=vacancy_data.get("vacancy_id", ""),
        language=vacancy_data.get("language", "en"),
    )
    try:
        result = await generate_json(
            prompt,
            system=SYSTEM_RECRUITER,
            temperature=0.3,
            max_tokens=RECRUITMENT_MAX_TOKENS,
        )
    except LLMOutputTruncatedError:
        # Even the raised budget can overflow on providers with a lower
        # per-model ceiling (gpt-4o 16384, Haiku 8192) or on very rich
        # vacancies. One retry asking for a compact profile beats a 502 —
        # the recruiter still gets a usable matrix to edit.
        # The effective ceiling may be lower than the requested budget —
        # llm_client clamps per model (gpt-4o 16384, Haiku 8192).
        logger.warning(
            "vacancy profile truncated at the model's token ceiling "
            "(requested %s) for vacancy %s — retrying with the "
            "compact-profile instruction",
            RECRUITMENT_MAX_TOKENS,
            vacancy_data.get("vacancy_id", ""),
        )
        result = await generate_json(
            prompt + _COMPACT_PROFILE_SUFFIX,
            system=SYSTEM_RECRUITER,
            temperature=0.3,
            max_tokens=RECRUITMENT_MAX_TOKENS,
        )
    return _as_dict(result)


async def generate_individual_questions(
    resume_data: dict,
    profile_data: dict,
    vacancy_title: str,
    language: str = "en",
) -> list[dict]:
    """Generate individual interview questions for a candidate.

    Input: parsed resume data, vacancy competency profile, vacancy title.
    Returns list of question dicts with competence_name, question_text,
    good/acceptable/poor answers, resume_fragment, purpose, priority.
    """
    import json

    prompt = GENERATE_QUESTIONS.format(
        resume_data=json.dumps(resume_data, ensure_ascii=False, indent=2),
        profile_data=json.dumps(profile_data, ensure_ascii=False, indent=2),
        vacancy_title=vacancy_title,
        language=language,
    )
    result = await generate_json(
        prompt,
        system=SYSTEM_RECRUITER,
        temperature=0.3,
        max_tokens=RECRUITMENT_MAX_TOKENS,
    )
    if isinstance(result, dict):
        result = result.get("questions", [result])
    if not isinstance(result, list):
        result = []
    return result
