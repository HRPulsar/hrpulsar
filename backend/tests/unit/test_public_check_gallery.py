"""The gallery data of the public check (HRP-930), as committed.

The generator lives in the internal process library, which the public tree
does not carry; what ships is its JSON, so this reads the JSON: the 35
public processes (HRPulsar's own, ``industry: internal``, never), each a valid result of the anonymous check, nothing internal in
it (no ``note`` - decisions and links to internal documents), no Cyrillic,
and only codes of the catalog the engine reads.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.modules.primitives.catalog_data import PRIMITIVES
from app.modules.public_check.schemas import CheckResult

_GALLERY = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "lib"
    / "public-check-gallery.json"
)
_CODES = {p["code"] for p in PRIMITIVES}


def _load() -> list[dict]:
    return json.loads(_GALLERY.read_text(encoding="utf-8"))


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(v) for v in value))
    return set()


def test_the_gallery_holds_35_processes_with_unique_slugs():
    processes = _load()
    assert len(processes) == 35
    slugs = [p["slug"] for p in processes]
    assert len(set(slugs)) == 35
    assert all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s) for s in slugs)
    for process in processes:
        assert process["title"] and process["domain"]


def test_every_process_is_a_result_of_the_check_without_hours():
    for process in _load():
        result = CheckResult.model_validate(process["result"])
        # The library carries no hour estimates: lists, no percentages.
        assert result.shares is None and result.money is None
        assert result.hours.total == 0
        assert not result.preliminary
        steps = [
            *result.buckets.moves,
            *result.buckets.to_review,
            *result.buckets.stays,
        ]
        assert steps, process["slug"]
        assert result.hours.unestimated == len(steps)


def test_no_process_of_hrpulsar_itself_is_in_the_gallery():
    # Our release pipeline, sync guards, Jira workflow and lead handling are
    # a calibration set of the library, not public pages (HRP-930 review).
    processes = _load()
    assert all(p["industry"] != "internal" for p in processes)
    assert not {"release-cycle", "bug-triage", "pr-review", "lead-response"} & {
        p["slug"] for p in processes
    }


def test_nothing_internal_leaks_into_the_gallery():
    text = _GALLERY.read_text(encoding="utf-8")
    assert not re.search("[\\u0400-\\u04ff]", text)
    processes = _load()
    assert "note" not in _keys(processes)
    for process in processes:
        for source in process["sources"]:
            assert set(source) == {"url", "kind"}
            assert source["kind"] not in ("internal", "vendor")
            assert re.match(r"https?://", source["url"])


def test_every_code_is_a_code_of_the_catalog():
    for process in _load():
        result = process["result"]
        steps = [*sum(result["buckets"].values(), []), *result["out_of_scope"]]
        for step in steps:
            assert set(step["codes"]) <= _CODES, (process["slug"], step["title"])
            assert set(step["reason"]["codes"]) <= set(step["codes"])
