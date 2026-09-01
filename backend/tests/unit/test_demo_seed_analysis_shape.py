"""HRP-598: the demo analysis fixtures are in the production payload shape.

The demo renders through the same components production does, so a
fixture that drifts from ``InterviewAnalysisResult`` shows up as an
empty panel on the demo and nowhere else. Validating the fixture
against the pydantic contract — rather than against a list of strings —
means the guard keeps up on its own when the schema grows a field.
"""

from __future__ import annotations

import re

import pytest
from app.modules.demo.seed_data import (
    ELENA_INTERVIEW_ANALYSIS,
    TOMAS_INTERVIEW_ANALYSIS,
)
from app.modules.recruitment.onboarding_service import DEMO_AI_ANALYSIS
from app.modules.recruitment.prompts_interview import InterviewAnalysisResult

FIXTURES = {
    "elena": ELENA_INTERVIEW_ANALYSIS,
    "tomas": TOMAS_INTERVIEW_ANALYSIS,
    # The onboarding "first hiring cycle" sample renders through the same
    # panel for every new tenant, so it is held to the same contract.
    "onboarding": DEMO_AI_ANALYSIS,
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_validates_against_the_ai_contract(name: str):
    InterviewAnalysisResult.model_validate(FIXTURES[name])


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_carries_every_field_the_writer_persists(name: str):
    """No missing keys (the UI reads them) and no legacy extras.

    ``analyze_interview_task`` writes ``model_dump()`` of the whole
    result onto ``interviews.analysis_data``; the seed must carry the
    same key set, or a panel that reads one of the absent keys renders
    empty only on the demo.
    """
    fixture = FIXTURES[name]
    written = InterviewAnalysisResult.model_validate(fixture).model_dump()
    assert set(fixture) == set(written)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_every_ui_section_has_content(name: str):
    """Verdict panel, competence matrix, blind spots, process findings.

    An empty list is valid for the schema but renders as a missing
    section — which is the bug this fixture pass fixed.
    """
    fixture = FIXTURES[name]
    assert fixture["verdict"] and fixture["verdict_summary"]
    assert fixture["competence_assessments"]
    assert fixture["blind_spots"]
    if name != "onboarding":
        # The onboarding sample ships a four-line transcript — there is
        # nothing honest to say about the interview process there.
        assert fixture["process_findings"]


def test_assessed_competences_cite_their_evidence():
    """HRP-250 acceptance: the demo opens on an evaluation with citations."""
    for fixture in FIXTURES.values():
        for ca in fixture["competence_assessments"]:
            if ca["status"] == "assessed":
                assert ca["citations"], ca["competence_id"]
                assert all(c["quote"] for c in ca["citations"])
            assert ca["score"] is None or 0.0 <= ca["score"] <= 1.0


def test_blind_spots_and_findings_point_at_profile_competences():
    """A blind spot on a competence the vacancy profile does not carry
    renders as a nameless card — the UI resolves the label through the
    profile, not through the fixture."""
    from app.modules.demo.seed_data import VACANCIES

    profile_slugs = {
        c["id"]
        for v in VACANCIES
        for c in (v.get("profile") or {}).get("competences", [])
    }
    # The onboarding sample lays down its own profile — read it from the
    # source rather than restating the slugs here.
    from app.modules.recruitment.onboarding_service import (
        DEMO_PROFILE_COMPETENCES,
    )

    profile_slugs |= {c["id"] for c in DEMO_PROFILE_COMPETENCES}
    for fixture in FIXTURES.values():
        for item in fixture["blind_spots"]:
            assert item["competence_id"] in profile_slugs
        for ca in fixture["competence_assessments"]:
            assert ca["competence_id"] in profile_slugs


# ---------------------------------------------------------------------------
# HRP-680 — the resume-only fixture and the resumes its chips point at
# ---------------------------------------------------------------------------


def _experience_period(entry: dict) -> str:
    """Mirror of the parsed-resume editor's ``data-resume-period``."""
    return " — ".join(
        str(part) for part in (entry.get("start_date"), entry.get("end_date")) if part
    )


def _anchor_exists(excerpt: dict, resume: dict) -> bool:
    """Would ``ParsedResumeEditor`` find a home for this excerpt?

    Mirrors ``findExperienceTarget`` / ``findGenericTarget``
    (parsed-resume-editor.tsx): the experience section matches on
    company + period, every other section on a two-way substring test
    against the rendered item text. ``summary`` renders no items at all,
    so the editor falls back to the section block — a substring check on
    the summary prose is the honest equivalent.
    """
    section = excerpt["section"]
    text = excerpt["excerpt_text"].strip().lower()
    if section == "experience":
        return any(
            (entry.get("company") or "").lower()
            == (excerpt["source_company"] or "").lower()
            and _experience_period(entry) == (excerpt["source_period"] or "")
            for entry in resume.get("experience") or []
        )
    if section == "summary":
        return text in (resume.get("summary") or "").lower()
    items: list[str] = []
    if section == "skills":
        items = [str(s) for s in resume.get("skills") or []]
    elif section == "education":
        items = [
            " ".join(str(v) for v in entry.values() if v)
            for entry in resume.get("education") or []
        ]
    return any(text in i.lower() or i.lower() in text for i in items)


def test_resume_only_fixture_matches_the_writer_schema():
    """``run_resume_only_analysis_task`` writes ``model_dump()`` of this
    shape; a drifted fixture renders an empty AI Insights block."""
    from app.modules.demo.seed_data import PRIYA_RESUME_ANALYSIS
    from app.modules.recruitment.prompts_interview import ResumeOnlyAnalysisResult

    written = ResumeOnlyAnalysisResult.model_validate(PRIYA_RESUME_ANALYSIS)
    assert set(PRIYA_RESUME_ANALYSIS) == set(written.model_dump())
    assert PRIYA_RESUME_ANALYSIS["competence_assessments"]
    assert PRIYA_RESUME_ANALYSIS["blind_spots"]


def test_resume_only_fixture_agrees_with_the_verdict_guard():
    """``recommended`` is unreachable in this mode — a fixture that used
    it would be silently rewritten to ``needs_check`` on any re-analyze
    and the demo would contradict itself."""
    from app.modules.demo.seed_data import PRIYA_RESUME_ANALYSIS
    from app.modules.recruitment.resume_analysis_service import (
        apply_resume_only_verdict_guard,
    )

    verdict = PRIYA_RESUME_ANALYSIS["verdict"]
    assert apply_resume_only_verdict_guard(verdict) == (verdict, False)


def test_resume_only_fixture_scores_the_vacancy_profile():
    from app.modules.demo.seed_data import PRIYA_RESUME_ANALYSIS, VACANCIES

    slugs = {
        c["id"]
        for v in VACANCIES
        if v["key"] == "senior-backend"
        for c in v["profile"]["competences"]
    }
    for ca in PRIYA_RESUME_ANALYSIS["competence_assessments"]:
        assert ca["competence_id"] in slugs
        # Excerpts are evidence — a competence the resume does not cover
        # must not carry any.
        if ca["status"] == "not_covered":
            assert not ca["resume_excerpts"], ca["competence_id"]
        else:
            assert ca["resume_excerpts"], ca["competence_id"]
    for item in PRIYA_RESUME_ANALYSIS["blind_spots"]:
        assert item["competence_id"] in slugs


@pytest.mark.parametrize("locale", ["en", "de", "ru"])
def test_every_resume_citation_lands_in_the_resume(locale: str):
    """HRP-680 acceptance: clicking a citation chip has to open the
    resume on the quoted item, in every locale the demo ships.

    Both halves go through ``localize`` at clone time, so a translation
    that rewrites a description but not the excerpt quoted out of it
    breaks the drill-down — in that locale only.
    """
    from app.modules.demo.seed_data import PARSED_RESUMES, PRIYA_RESUME_ANALYSIS
    from app.modules.demo.seed_i18n import localize

    resume = localize(PARSED_RESUMES["priya.shah@example.com"], locale)
    analysis = localize(PRIYA_RESUME_ANALYSIS, locale)
    seen = set()
    for ca in analysis["competence_assessments"]:
        for excerpt in ca["resume_excerpts"]:
            assert _anchor_exists(excerpt, resume), (
                locale,
                ca["competence_id"],
                excerpt["excerpt_text"],
            )
            seen.add(excerpt["section"])
    # More than one section, or the drill-down demonstrates nothing.
    assert len(seen) > 1


def test_parsed_resumes_are_in_the_parser_payload_shape():
    """Readers of ``parsed_resume_jsonb`` (the editor, the candidates
    table's Last position, ``_denorm_from_parsed``) key off the parser's
    field names — ``position`` with ``role`` as its mirror, newest-first
    experience, no unknown top-level keys."""
    from app.modules.demo.seed_data import PARSED_RESUMES, candidates

    allowed = {
        "summary",
        "current_position",
        "years_of_experience",
        "location",
        "experience",
        "education",
        "skills",
        "languages",
        "certificates",
    }
    emails = {spec["email"] for spec in candidates()}
    for email, resume in PARSED_RESUMES.items():
        assert email in emails, email
        assert set(resume) <= allowed, set(resume) - allowed
        assert resume["experience"] and resume["skills"]
        for entry in resume["experience"]:
            assert entry["position"] == entry["role"]
            assert entry["company"] and entry["description"]
        years = [
            int(entry["start_date"])
            for entry in resume["experience"]
            if entry.get("start_date")
        ]
        assert years == sorted(years, reverse=True), email
        for section, keys in _NESTED_FIELDS.items():
            assert resume[section], (email, section)
            for entry in resume[section]:
                assert set(entry) == keys, (email, section, set(entry) ^ keys)


# The exact field set the editor renders for each nested list. The demo
# fixture, the parser prompt and ``_normalise_resume_entries`` all owe the
# reader these names — HRP-686 shipped after the prompt drifted to
# ``education.year`` / ``certificates.title`` and the editor rendered
# empty fields on real resumes.
_NESTED_FIELDS = {
    "experience": {
        "position",
        "role",
        "company",
        "start_date",
        "end_date",
        "description",
    },
    "education": {"institution", "degree", "field", "start_date", "end_date"},
    "certificates": {"name", "issuer", "issued_at"},
}


def _prompt_object_keys(section: str) -> set[str]:
    """Field names the PARSE_RESUME schema block declares for one array."""
    from app.modules.recruitment.prompts import PARSE_RESUME

    start = PARSE_RESUME.index(f'"{section}": [')
    block = PARSE_RESUME[start : PARSE_RESUME.index("]", start)]
    return set(re.findall(r'"(\w+)":', block)) - {section}


def test_parser_prompt_asks_for_every_field_the_editor_renders():
    """The demo must not lead the product: every nested field the fixture
    fills is a field ``PARSE_RESUME`` asks the model for, so a live resume
    renders the same card the demo does (HRP-686)."""
    for section, keys in _NESTED_FIELDS.items():
        declared = _prompt_object_keys(section)
        assert keys <= declared, (section, keys - declared)
