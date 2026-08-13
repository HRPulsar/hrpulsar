"""HRP-509 — the UI must quote the action the backend charges.

`GenerationConfirmDialog` used to map `whole_base` to the legacy
`ai.generate_competences` price (75) while the session endpoint charged
`ai_competence_generation.start_whole_base` (200). Nothing tied the two
sides together, so the drift survived until QA compared the numbers on
prod. The frontend keeps its map in `src/lib/billing-actions.ts`; this
test pins it against the Python source of truth.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from app.modules.ai_competence_generation.billing_actions import (
    refine_action_for_scope,
    start_action_for_scope,
)

_SCOPES = (
    "whole_base",
    "group",
    "competence_indicators",
    "specialization_matrix",
)

_FRONTEND_MAP = (
    Path(__file__).resolve().parents[2].parent
    / "frontend"
    / "src"
    / "lib"
    / "billing-actions.ts"
)

pytestmark = pytest.mark.skipif(
    not _FRONTEND_MAP.is_file(),
    reason="frontend tree not present in this checkout",
)


def _parse_map(name: str) -> dict[str, str]:
    """Read one `Record<SessionScope, string>` literal out of the TS module."""
    source = _FRONTEND_MAP.read_text(encoding="utf-8")
    match = re.search(
        rf"export const {name}: Record<SessionScope, string> = \{{(.*?)\}};",
        source,
        re.DOTALL,
    )
    assert match, f"{name} not found in {_FRONTEND_MAP}"
    return {
        key: json.loads(value)
        for key, value in re.findall(r"(\w+):\s*(\"[^\"]+\")", match.group(1))
    }


def test_start_actions_match_backend() -> None:
    frontend = _parse_map("START_ACTION_BY_SCOPE")
    assert frontend == {scope: start_action_for_scope(scope) for scope in _SCOPES}


def test_refine_actions_match_backend() -> None:
    frontend = _parse_map("REFINE_ACTION_BY_SCOPE")
    assert frontend == {scope: refine_action_for_scope(scope) for scope in _SCOPES}


def test_quoted_actions_are_real_price_keys() -> None:
    """A typo'd key resolves to 0 and the dialog silently shows nothing."""
    # Community checkouts carry no price list — nothing to cross-check.
    pricing = pytest.importorskip("ee.pricing")

    for scope in _SCOPES:
        assert start_action_for_scope(scope) in pricing.CREDIT_COSTS_FROM_YAML
        assert refine_action_for_scope(scope) in pricing.CREDIT_COSTS_FROM_YAML
