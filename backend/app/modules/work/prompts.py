"""Decomposition prompts (HRP-755, HRP-775): the catalog with its scopes,
the step attributes S1-S4 and the four rules of the process library, then
the few-shot examples. Templates stay English; the tenant's content
language is a directive the worker appends (HRP-480).

Since ``v2work.v5`` a breakdown is two calls (decision 2026-09-10): the
first splits the description into steps with the v4 prompt as it was, the
second classifies the fixed list in one call with the whole description as
context - the split-then-classify separation is what lifts recall, not
attention to one step at a time. The same second-pass prompt, narrowed to
one step and given the company's comment, reclassifies a step on request.

Since ``v2work.v7`` (W6, decision 2026-09-11) the first call also estimates
the step's ``hours_per_run`` and ``runs_per_year`` - the ordinal frequency
and effort scales are gone. ``_RULES`` is shared by both calls, so the
estimate directive rides in the second prompt too; its schema simply does
not ask for the numbers.

Since ``v2work.v8`` the second call says so itself: its answer drops the
numbers and must carry ``evidence`` - the schema requires the key, so an
answer shaped like the examples fails validation instead of landing with
every confidence empty.

Since ``v2work.v9`` (HRP-961) the rules that decide which code a step gets
are not written here: both calls embed ``conventions.render_rules()`` after
the catalog, the same block the competence mapping prompt embeds, so a step
and a person are judged by one text. What stays here is what only a
breakdown needs - how to cut steps, responsibility, hours, the schema. The
few-shot examples are printed as compact JSON.

Since ``v2work.v10`` (HRP-961, product answers of 2026-09-29) the P6 rule
also covers a check whose point is to pull or let the material through and
a negotiation that chooses the concession; the contract example carries it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.modules.primitives.conventions import render_rules
from app.modules.work._examples import EXAMPLES
from app.modules.work.models import OUTPUT_TYPES, RESPONSIBILITIES

# Bumped on every change of this text; stamped on each session row.
PROMPT_VERSION = "v2work.v10"

_RULES = """You break a described process or initiative into the ordered list of steps it consists of, and tag every step with the capability primitives it requires, from a fixed catalog.

Rules of decomposition:
- Reproduce the steps as the source describes them; do not improve, merge, reorder or complete the process. One step per unit of work that has its own output. Ten steps is typical; twenty is a lot.
- A sign-off, approval or hand-over that concludes a step stays inside that step. Split it into a step of its own only when the source names it as its own step.
- Tag every step by the conventions that follow the catalog: every capability the step exercises, only codes from the catalog, an empty list where the conventions say so. Usually one to three codes.
- Responsibility is a property of the step, not of the capability: `responsibility` names who answers for the outcome, whatever the capabilities are. `formal` when someone other than the doer signs the step off - a review, an acceptance, a mobilisation, a booking that the books depend on; `regulatory` for a step the law or a regulator can audit - a statutory deadline, a filing, a permit, a decision the regulator may review; `reputational` when the company's face is at stake with an outside party - a dispute, a negotiation, a public status; `none` for internal work nobody signs off, including analyses, postmortems and reviews of history.

Step attributes:
- `primitives`: every capability the step exercises; only codes from the catalog.
- `output_type`: `draft` when the step produces something a person or the next step reviews; `external_change` when it changes the world outside the process - a system record, a shipment, a signed document, a decision communicated.
- `reversibility` (`reversible`, `costly`, `irreversible`): only when the description states it, otherwise null. The company knows it; you do not.
- `hours_per_run` and `runs_per_year`: always give both, as numbers - your estimate of the person-hours one execution of the step takes and of how many times a year the step runs, for a typical company of this kind. Take what the description states (a monthly close runs 12 times a year; a step that happens only on a discrepancy runs less often than the rest) and estimate the remainder from the kind of work. The company will correct the numbers. The estimate is separate from the tagging: list every capability the step exercises exactly as you would without it.
- `title`: a short phrase naming the work, as in the source; `description`: one sentence only when the title is not enough.

Catalog:"""


_CLASSIFY_TASK = """Task of this call:
- The steps of the process are already fixed and listed in the request. Do not split, merge, rename or reorder them: return exactly one entry per step, in the order given.
- For every step give its `primitives` (every capability the step exercises, by the rules and boundaries above), `responsibility` and `output_type`. Use the whole description and the neighbouring steps as context: a capability exercised by a neighbouring step is not exercised by this one.
- When the request names a single step to classify, classify only that one. A comment from the company on that step is authoritative about what the step really is: classify by the comment, not by the title alone.
- The examples above show the answer of the first call. This call's answer has no `hours_per_run` or `runs_per_year`, and it carries `evidence` on every step - an answer without `evidence` is rejected.
- For every code in `primitives` add one entry to `evidence`: the code, a verbatim fragment of the description (the `quote`) that shows the step exercises that capability, and your `confidence` from 0 to 1 that the code belongs on the step. A code you cannot tie to a fragment of the description gets confidence 0.5 or lower. `primitives` and `evidence` list the same codes.
- A doubtful code stays in `primitives` with a low confidence; do not drop it. A missing capability costs more than a doubtful one: it lets a step look coverable by an agent that cannot do it."""


def _catalog_lines(primitives: Sequence[Mapping[str, Any] | Any]) -> list[str]:
    lines = []
    for p in primitives:
        get = p.get if isinstance(p, Mapping) else lambda k, _p=p: getattr(_p, k, None)
        scope = f" Scope: {get('scope_en')}." if get("scope_en") else ""
        lines.append(
            f"- {get('code')} - {get('title_en')}.{scope} (kind: {get('kind')}, "
            f"AI verdict: {get('ai_verdict')})"
        )
    return lines


def _format_examples() -> list[str]:
    # Compact JSON: the six examples are the bulk of the prompt, and
    # indentation was a few thousand characters of whitespace per call.
    lines = ["Examples:"]
    for i, (question, answer) in enumerate(EXAMPLES, start=1):
        lines.append(f"Example {i} input:")
        lines.append(json.dumps(question, ensure_ascii=False))
        lines.append(f"Example {i} output:")
        lines.append(json.dumps(answer, ensure_ascii=False))
    return lines


def build_system_prompt(primitives: Sequence[Mapping[str, Any] | Any]) -> str:
    """``primitives`` are catalog rows or ``catalog_data.PRIMITIVES`` dicts,
    in catalog order, retired codes excluded by the caller."""
    return "\n".join(
        [
            _RULES,
            *_catalog_lines(primitives),
            "",
            render_rules(),
            "",
            *_format_examples(),
        ]
    )


def build_user_prompt(container: Mapping[str, Any]) -> str:
    payload = {
        key: container.get(key) for key in ("type", "title", "description", "goal")
    }
    return "Inputs:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def classify_system_blocks(primitives: Sequence[Mapping[str, Any] | Any]) -> list[str]:
    """The second pass as two blocks: the rules, catalog and examples the
    first pass sends byte for byte - the block the provider caches between
    the two calls (HRP-951) - then the task that pins the step list."""
    return [build_system_prompt(primitives), _CLASSIFY_TASK]


def build_classify_system_prompt(primitives: Sequence[Mapping[str, Any] | Any]) -> str:
    """The two blocks as one string."""
    return "\n\n".join(classify_system_blocks(primitives))


def build_classify_user_prompt(
    container: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    *,
    only: int | None = None,
    comment: str | None = None,
) -> str:
    """``steps`` are the fixed list (title, optional description) in order;
    ``only`` is the 0-based index of the one step to classify, with the
    company's ``comment`` on it, when the call is a reclassification."""
    listing = [
        f"{i}. {s['title']}"
        + (f" - {s['description']}" if s.get("description") else "")
        for i, s in enumerate(steps, start=1)
    ]
    parts = [build_user_prompt(container), "", "Steps:", *listing, ""]
    if only is None:
        parts.append(f"Classify all {len(steps)} steps.")
    else:
        parts.append(f"Classify only step {only + 1}: {steps[only]['title']}")
        if comment:
            parts.append(f"Comment from the company on this step: {comment}")
    return "\n".join(parts)


__all__ = [
    "OUTPUT_TYPES",
    "PROMPT_VERSION",
    "RESPONSIBILITIES",
    "build_classify_system_prompt",
    "build_classify_user_prompt",
    "build_system_prompt",
    "build_user_prompt",
    "classify_system_blocks",
]
