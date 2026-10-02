"""HRP-961: the conventions are one source, and nothing that states a rule
drifts from it - the catalog a client reads, the decomposition prompt, the
mapping prompt and the few-shot corpus."""

import json
import re
from pathlib import Path

import pytest
from app.modules.primitives import catalog_data, conventions
from app.modules.primitives.mapping_service import (
    build_system_prompt as build_mapping_prompt,
)
from app.modules.work import _examples, prompts

MESSAGES = Path(__file__).resolve().parents[3] / "frontend" / "messages"
CODES = {p["code"] for p in catalog_data.PRIMITIVES}
CODE_RE = re.compile(r"\b[PB]\d{1,2}\b")


def test_every_catalog_code_has_a_convention_and_nothing_else():
    assert set(conventions.CONVENTIONS) == CODES
    for code, c in conventions.CONVENTIONS.items():
        assert c.definition and c.assign_if and c.not_when, code
        assert 2 <= len(c.examples) <= 3, code


def test_rules_name_only_catalog_codes():
    text = conventions.render_rules()
    assert set(CODE_RE.findall(text)) <= CODES
    for codes, _question in conventions.BOUNDARIES:
        assert set(codes) <= CODES, codes


def test_catalog_description_is_the_convention_definition():
    for row in catalog_data.PRIMITIVES:
        assert row["scope_en"] == conventions.CONVENTIONS[row["code"]].definition, row[
            "code"
        ]
    block = json.loads((MESSAGES / "en.json").read_text())["reference"]["primitive"]
    for code, c in conventions.CONVENTIONS.items():
        assert block[code.lower()]["description"] == c.definition, code


def test_both_prompts_embed_the_same_rules():
    rules = conventions.render_rules()
    decomposition = prompts.build_system_prompt(catalog_data.PRIMITIVES)
    mapping = build_mapping_prompt([])
    assert rules in decomposition
    assert rules in mapping
    # The rules follow the catalog lines they refer to.
    assert decomposition.index("Catalog:") < decomposition.index(rules)
    # The hand-written boundaries the conventions replace are gone.
    for stale in (
        "Boundaries between codes that are easy to confuse",
        "Secondary codes most steps",
    ):
        assert stale not in decomposition, stale
    assert "escalation by rule is P11" not in mapping


def test_decisions_of_2026_09_28_are_in_the_rules():
    text = conventions.render_rules()
    for phrase in (
        # 1: P6 narrow
        "P6 needs a choice that costs money or risk and that the step itself makes",
        # answers of 2026-09-29: a negotiation that chooses the concession
        # carries P6; a check whose point is to pull or let the material
        # through carries P6 - and a check a reference settles stays P2
        "a negotiation itself chooses the concession (then P6 goes next to P7)",
        "pulling or letting the checked material through is the main point",
        "a check whose verdict follows from a reference is P2",
        "P6 goes next to P2",
        # 2: P11 only when the work is to follow up
        "A deadline mentioned in the description is not P11",
        # 3: escalation by rule is P3
        "Escalation by a rule - a threshold, a deadline, a request type - is P3",
        # 4: three questions
        "A step that does several of these gets several codes",
        # 5: external dialogue
        "Inside the company there is no P7 and no P12",
        # 6: approvals
        "A signature under a decision made earlier gets no capability",
        # 7: people
        "Assigning by a rule - a queue, a duty rota, a free slot - P3",
        # 8: secondary codes
        "A minor action without a result of its own gets no code",
        # review 29.09: a risk the rule does not name adds P6 next to P3,
        # checking someone else's work is named under P2
        "adds P6 next to P3",
        "checking someone else's work",
        # accepted formulation 2 (28.09): creative rounds stay P13
        "including the further rounds until the direction is accepted",
        "a correction of text or a layout after feedback is P5",
        # accepted formulation 3: the service-desk requester is the outside party
        "the employee who raised the request counts as the party outside",
    ):
        assert phrase in text, phrase


def test_examples_are_printed_compactly():
    system = prompts.build_system_prompt(catalog_data.PRIMITIVES)
    assert '"steps": [' in system
    assert '\n  "steps"' not in system


def test_corpus_covers_the_rare_codes():
    seen = {
        code
        for _q, answer in _examples.EXAMPLES
        for step in answer["steps"]
        for code in step["primitives"]
    }
    assert {"P11", "P12", "P13", "B4"} <= seen, seen


# The six few-shot processes are translations of library rows; their codes
# must be the library's, or the prompt teaches one thing and the reference
# scores another. The library is not in the public tree.
LIBRARY = Path(__file__).resolve().parents[3] / "docs" / "plans" / "process-library"
EXAMPLE_SOURCES = {
    "Contract review": "legal-1-contract-review",
    "Goods receipt at the warehouse": "4.4.2-goods-receipt",
    "KYC/CDD at account opening": "11.2.2-kyc-cdd-onboarding",
    "Feature development and release": "8.5.4-feature-development",
    "Product hypothesis check with an A/B test": "2.3.2-ab-test",
    "Rebranding": "brand-1-rebranding",
}


def test_examples_carry_the_library_codes():
    if not LIBRARY.exists():
        pytest.skip("docs/ is not part of the public tree")
    yaml = pytest.importorskip("yaml")
    assert {q["title"] for q, _a in _examples.EXAMPLES} == set(EXAMPLE_SOURCES)
    for question, answer in _examples.EXAMPLES:
        doc = yaml.safe_load(
            (LIBRARY / f"{EXAMPLE_SOURCES[question['title']]}.yaml").read_text()
        )
        library = [set(s["primitives"] or []) for s in doc["steps"]]
        corpus = [set(s["primitives"]) for s in answer["steps"]]
        assert corpus == library, question["title"]


def test_mapping_keeps_its_competence_rules():
    """The move to the shared block must not drop what only competences
    need (kickoff: competence-specific rules stay), and the accepted
    doubtful-code rule is about P6 only."""
    mapping = build_mapping_prompt([])
    assert "a spoken presentation adds no code" in mapping
    assert "explicitly about following a script" in mapping
    assert "A doubtful P6 stays in the set" in mapping
    assert "A doubtful code stays in the set" not in mapping


def test_p3_keeps_p3_when_a_risk_adds_p6():
    """The not-when list names the cases a neighbour takes instead; a risk
    the rule does not name adds P6 but does not take P3 away."""
    assert "P6 is added" not in conventions.CONVENTIONS["P3"].not_when
