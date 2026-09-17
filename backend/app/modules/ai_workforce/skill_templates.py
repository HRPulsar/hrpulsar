"""``SKILL.md`` skeletons, one per built-in pack (REFACTOR_PLAN §2.4, §4.4).

A skeleton is a frame with placeholders, not a finished file: the step
skill generator (W4) fills it with the company's own context — the step,
its indicators, the reference data, who accepts the result. Handing a
client the bare skeleton would be pointless; a generic "drafting skill" is
available in any chat.

The construction is dictated by the catalog section "Designing an agent
for a step", so it is not chosen per pack:

* ``PIPELINE_PACKS`` — codes with a "strong" / "better than human" verdict
  (P1 / P2 / P3) and the v1.1 "yes" codes (P11 / P12): a deterministic
  pipeline — input, rules, output — with a mandatory verification against
  a reference set.
* ``ACCEPTANCE_PACKS`` — "draft" verdicts (P4 / P5 / P9 / P10): generation
  with a mandatory acceptance section — what a person checks, by which
  criteria, who accepts.

P6 / P7 / P8 and B1–B4 have no skeleton: there the platform designs
support for a person, not an agent.

English only: this file reaches the public tree.
"""

from __future__ import annotations

from app.modules.ai_workforce.pack_data import PACKS

PIPELINE_PACKS = (
    "extraction",
    "compliance_check",
    "triage_router",
    "coordinator",
    "scripted_dialogue",
)
ACCEPTANCE_PACKS = (
    "drafting",
    "investigation",
    "artifact_builder",
    "experiment_design",
)

# Pack-specific line under "Focus": the one thing that distinguishes this
# pack's agent from the generic construction.
_FOCUS = {
    "extraction": (
        "Extract exactly the fields listed under Output; never infer a value "
        "the source does not state - leave it empty and flag it."
    ),
    "compliance_check": (
        "Compare every item of the input against the reference; report each "
        "discrepancy with the reference clause it violates. Anything outside "
        "the reference that would still stop the owner from accepting the "
        "result - a security hole, a wrong result, a missing test, a "
        "performance trap - goes under Beyond the reference, as a finding. "
        "Never judge whether a discrepancy is acceptable - that is the "
        "owner's call."
    ),
    "triage_router": (
        "Apply the routing rules in order; the first matching rule wins. An "
        "item matching no rule goes to the fallback queue, never to a guess."
    ),
    "coordinator": (
        "Act only on the calendar, the triggers and the lists below: send "
        "the reminder, collect the status, move the item. Never decide "
        "priority between people - escalate a conflict instead."
    ),
    "scripted_dialogue": (
        "Follow the script or the question tree; ask each question once and "
        "record the answer verbatim. The moment the conversation leaves the "
        "script (a complaint, a negotiation, an unexpected request), hand "
        "over to a person with the transcript."
    ),
    "drafting": (
        "Write in the register and the conventions below; keep every fact "
        "traceable to the input and mark each assumption in the draft."
    ),
    "investigation": (
        "Assemble the timeline from every source listed under Input, then "
        "state the most likely cause and the evidence for and against it. "
        "The hypothesis is a draft; naming the cause is the person's job."
    ),
    "artifact_builder": (
        "Build from the specification; when the specification is silent, "
        "choose the simplest option and list the choice under Assumptions. "
        "The artifact is accepted by whether it works, not by how it reads."
    ),
    "experiment_design": (
        "Propose the metric, the sample, the control and the stopping rule; "
        "state what result would falsify the hypothesis. A person approves "
        "the design before anything is measured."
    ),
}

_HEADER = """---
name: "{{{{skill_slug}}}}"
description: "{title} skill for the step {{{{step_title}}}} at {{{{company}}}}"
pack: {code}
construction: {construction}
---

# {{{{step_title}}}}

## Purpose
{{{{purpose}}}} - what this step produces, for whom, and how often.

## Focus
{focus}

## Input
- Source: {{{{input_source}}}} (format, where it arrives, typical volume)
- Reference data: {{{{reference_data}}}}
- Out of scope: {{{{out_of_scope}}}} - hand these to a person
"""

_PIPELINE_BODY = """
## Rules
1. {{rule_1}}
2. {{rule_2}}
3. {{rule_3}}

## Output
- Shape: {{output_shape}}
- Destination: {{output_destination}}

## Verification against the reference
- Reference set: {{reference_set}} (owner: {{reference_owner}})
- Run the reference set before every change to the rules; the pass rate
  must not drop below {{pass_rate}}.
- Sample {{sample_size}} live outputs per {{period}} and compare them to
  the reference; log every mismatch.

## Beyond the reference
- The reference limits what you certify, not what you notice: report
  anything that would stop {{acceptance_owner}} from accepting the result
  even though no reference clause covers it - {{beyond_examples}}.
- State each such finding with the evidence and its consequence; leave the
  verdict to the owner.

## Escalation
- Input that fits no rule: {{escalation_path}}
"""

_ACCEPTANCE_BODY = """
## Draft
- Produce: {{draft_shape}}
- Conventions: {{conventions}}
- Mark every place where the draft relies on an assumption.

## Acceptance by a human
- Accepted by: {{acceptor_role}}
- Checks before acceptance:
  1. {{check_1}}
  2. {{check_2}}
  3. {{check_3}}
- Criteria: {{criteria}}
- The draft is never sent, merged, published or acted on before acceptance.

## Escalation
- Draft the acceptor cannot judge: {{escalation_path}}
"""

_TITLES = {p["code"]: p["title_en"] for p in PACKS}


def _build(code: str) -> str:
    pipeline = code in PIPELINE_PACKS
    head = _HEADER.format(
        title=_TITLES[code],
        code=code,
        construction="pipeline" if pipeline else "acceptance",
        focus=_FOCUS[code],
    )
    return head + (_PIPELINE_BODY if pipeline else _ACCEPTANCE_BODY)


SKELETONS: dict[str, str] = {code: _build(code) for code in _FOCUS}


def skeleton_for(pack_code: str) -> str:
    """The skeleton of a built-in pack; ``KeyError`` for a code without one."""
    return SKELETONS[pack_code]
