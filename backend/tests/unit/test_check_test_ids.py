"""scripts/check_test_ids.py: matcher and collector shapes (HRP-848).

The script lives in the monorepo root ``scripts/`` (not synced to public),
so the test skips when it is absent.
"""

import importlib.util
import pathlib

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "check_test_ids.py"
if not _SCRIPT.exists():
    pytest.skip("scripts/check_test_ids.py is monorepo-only", allow_module_level=True)

_spec = importlib.util.spec_from_file_location("check_test_ids", _SCRIPT)
assert _spec and _spec.loader
cti = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cti)


def test_wildcard_only_patterns_match_nothing() -> None:
    assert cti.is_wildcard_only("*")
    assert cti.is_wildcard_only("*-*")
    assert cti.is_wildcard_only("*_*.*")
    assert not cti.is_wildcard_only("foo-*-row")
    assert not cti.is_wildcard_only("*-accept")

    blind = {"*", "*-*"}
    assert not cti.matches("gone-button", blind)
    assert not cti.matches("gone-*-row", blind)
    assert not cti.matches("*-*", blind)


def test_regular_patterns_still_match() -> None:
    haystack = {"foo-*-row", "*-*"}
    assert cti.matches("foo-42-row", haystack)
    assert cti.matches("foo-*-row", haystack)
    assert not cti.matches("bar-42-row", haystack)


def test_leading_wildcard_entries_vouch_for_nothing() -> None:
    # ``${prefix}-hint`` in a shared component is not evidence for any
    # ``<anything>-hint``; it counts once composed with the caller's value.
    haystack = {"*-hint", "*-load-failed", "*-step-*", "header-btn-theme"}
    assert not cti.matches("totally-bogus-hint", haystack)
    assert not cti.matches("totally-bogus-load-failed", haystack)
    assert not cti.matches("totally-bogus-step-9", haystack)
    assert not cti.matches("header-bogus-thing", haystack)
    assert cti.matches("header-btn-theme", haystack)


def test_suffix_only_selector_needs_an_anchored_pattern() -> None:
    # ``row.locator('[data-testid$="-capability-P1"]')``
    assert cti.matches("*-capability-P1", {"coverage-row-*-capability-*"})
    assert not cti.matches("*-capability-P1", {"auth-menu-language-*"})


def test_code_collector_sees_ids_passed_through_props() -> None:
    src = """
      <Tab testId="tab-a" />
      const tabs = [{ testId: "tab-b" }];
      <div data-testid={ok ? "plate-ok" : "plate-bad"} />
      <div data-testid={mode === "select" ? "modal-mode" : "modal-create"} />
      let testId = on ? "btn-on" : "btn-off";
      const id = `field-${name}`;
      <Input data-testid={id} />
      selectAll={{ testId: testId ? `${testId}-select-all` : undefined }}
    """
    ids = cti._code_ids_in(src, {})
    assert {"tab-a", "tab-b", "plate-ok", "plate-bad", "modal-mode"} <= ids
    assert {"modal-create", "btn-on", "btn-off", "field-*", "*-select-all"} <= ids
    assert "select" not in ids  # comparison operand, not an id


def test_prefix_prop_composes_with_the_receiving_component() -> None:
    components = {"LoadError": "data-testid={`${testIdPrefix}-load-failed`}"}
    ids = cti._code_ids_in('<LoadError testIdPrefix="employees" />', components)
    assert ids == {"employees-load-failed"}  # not a blanket ``employees-*``

    # Unknown component: nothing, never a blanket ``stage-*``.
    assert cti._code_ids_in('<Missing testIdPrefix="stage" />', {}) == set()


def test_default_prefix_composes_with_its_own_component() -> None:
    src = """
    export function LanguageSwitcher({ testIdPrefix = "header" }: Props) {
      return <button data-testid={`${testIdPrefix}-btn-language`} />;
    }
    """
    assert cti._code_ids_in(src, {}) == {"header-btn-language", "*-btn-language"}


def test_literal_testid_composes_through_the_receiver() -> None:
    components = {
        "SummaryLine": "data-testid={testId} data-testid={`${testId}-name`}",
        "Filter": '{ "data-testid": testId, x } data-testid={`${testId}-option-${v}`}',
    }
    ids = cti._code_ids_in('<SummaryLine testId="emp-summary" />', components)
    assert {"emp-summary", "emp-summary-name"} <= ids
    ids = cti._code_ids_in('<Filter data-testid="emp-multi" />', components)
    assert {"emp-multi", "emp-multi-option-*"} <= ids

    # object key read back through member access: ``${stage.testid}-hint``
    src = (
        'const s = [{ testid: "dash-dyn" }]; <H data-testid={`${stage.testid}-hint`} />'
    )
    assert "dash-dyn-hint" in cti._code_ids_in(src, {})


def test_literal_union_expands_template() -> None:
    src = 'mode: "compact" | "fullscreen"; <div data-testid={`canvas-${mode}`} />'
    ids = cti._code_ids_in(src, {})
    assert {"canvas-compact", "canvas-fullscreen"} <= ids
    assert not cti.matches("canvas-bogus", ids)


def test_doc_brace_alternatives_expand() -> None:
    assert cti._expand_braces("a-{b,c}-row-{id}") == ["a-b-row-{id}", "a-c-row-{id}"]
