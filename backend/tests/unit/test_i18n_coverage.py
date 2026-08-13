"""i18n F3/F4 (HRP-477/478): permanent catalog invariants.

A typo'd AppError code or a locale drift must fail CI, not ship a raw
``errors.<key>`` string to a user toast: ``translate`` degrades to the
key on a miss by design, so nothing else would ever crash.

Checks (whole catalog — ``errors.*`` and ``email.*`` alike):
1. Key parity between en.json and de.json (recursive).
2. Placeholder parity: the ``{param}`` sets match per key, so a locale
   can reorder words but never drop or invent a parameter.
3. Every ``AppError("<code>", ...)`` literal in backend/app (+ee when
   present) resolves to an ``errors.*`` catalog entry.
4. Every ``translate("<key>", ...)`` literal resolves to a catalog
   entry (F4: covers the ``email.*`` keys in email_templates.py).
"""

import json
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
I18N = BACKEND / "app" / "i18n"

# Matches AppError("code", ...) / CompetenceCycleError(code="...") call
# sites, including multi-line calls.
CODE_RE = re.compile(
    r"""(?:AppError|CompetenceCycleError)\(\s*\n?\s*"""
    r"""(?:code(?::\s*str\s*)?=\s*)?["']([a-z0-9_.]+)["']"""
)
TRANSLATE_KEY_RE = re.compile(r"""translate\(\s*\n?\s*["']([a-z0-9_.]+)["']""")
PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def _flatten(tree: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in tree.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def _catalog(locale: str) -> dict[str, str]:
    data = json.loads((I18N / f"{locale}.json").read_text(encoding="utf-8"))
    return _flatten(data)


def _catalog_locales() -> list[str]:
    """Every locale shipping a core catalog, read from disk (HRP-511 item v).

    Hard-coding en/de meant a third core catalog would join the tree
    completely unguarded. Enterprise-only catalogs live in ``ee/i18n``
    and are covered by tests/unit/ee/test_i18n_ru.py — this file syncs to
    the public repo and stays ee-agnostic.
    """
    return sorted(path.stem for path in I18N.glob("*.json"))


def _translated_locales() -> list[str]:
    """Catalogs that must mirror the en baseline."""
    return [locale for locale in _catalog_locales() if locale != "en"]


def _scan_source(regex: re.Pattern[str], *, skip_core_helpers: bool) -> set[str]:
    used: set[str] = set()
    for base in (BACKEND / "app", BACKEND / "ee"):
        if not base.exists():  # community build ships without ee/
            continue
        for py in base.rglob("*.py"):
            if (
                skip_core_helpers
                and py.parent.name == "core"
                and py.name
                in (
                    "errors.py",
                    "i18n.py",
                )
            ):
                continue  # docstring usage examples / translate() itself
            used.update(regex.findall(py.read_text(encoding="utf-8")))
    return used


def _codes_in_source() -> set[str]:
    return _scan_source(CODE_RE, skip_core_helpers=True)


def test_catalog_discovery_sees_the_shipped_locales():
    """Tripwire for the disk enumeration itself: a moved directory or a
    renamed file must fail here, not silently reduce the parity matrix to
    zero cases."""
    locales = _catalog_locales()
    assert "en" in locales, f"no en.json in {I18N}"
    assert _translated_locales(), "no locale to compare against en"


@pytest.mark.parametrize("locale", _translated_locales())
def test_locale_key_parity(locale):
    en, other = _catalog("en"), _catalog(locale)
    assert set(en) == set(other), (
        f"only in en.json: {sorted(set(en) - set(other))}; "
        f"only in {locale}.json: {sorted(set(other) - set(en))}"
    )


@pytest.mark.parametrize("locale", _translated_locales())
def test_placeholder_parity(locale):
    en, other = _catalog("en"), _catalog(locale)
    diverged = {}
    for key in set(en) & set(other):
        pe = set(PLACEHOLDER_RE.findall(en[key]))
        po = set(PLACEHOLDER_RE.findall(other[key]))
        if pe != po:
            diverged[key] = {"en": sorted(pe), locale: sorted(po)}
    assert not diverged, f"placeholder sets diverge: {diverged}"


def test_every_apperror_code_is_catalogued():
    en = _catalog("en")
    used = _codes_in_source()
    assert used, "AppError literal scan found nothing — regex or layout broke"
    missing = {code for code in used if f"errors.{code}" not in en}
    assert not missing, f"AppError codes missing from en.json: {sorted(missing)}"


def test_every_translate_key_is_catalogued():
    en = _catalog("en")
    used = _scan_source(TRANSLATE_KEY_RE, skip_core_helpers=True)
    assert used, "translate() literal scan found nothing — regex or layout broke"
    missing = used - set(en)
    assert not missing, f"translate() keys missing from en.json: {sorted(missing)}"


def test_translate_params_match_catalog_placeholders():
    """Literal ``translate(key, ..., a=..., b=...)`` calls must pass exactly
    the placeholders of the catalog string: a missing param makes
    ``str.format`` fail and ship the raw un-interpolated template to the
    user (translate degrades silently by design), an extra one is a typo.
    Calls with ``**dynamic`` params are skipped — they can't be checked
    statically."""
    import ast

    en = _catalog("en")
    problems: list[str] = []
    for base in (BACKEND / "app", BACKEND / "ee"):
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            if py.parent.name == "core" and py.name in ("errors.py", "i18n.py"):
                continue
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "translate"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    continue
                key = node.args[0].value
                if key not in en:
                    continue  # covered by test_every_translate_key_is_catalogued
                if any(kw.arg is None for kw in node.keywords):
                    continue  # **dynamic — not statically checkable
                passed = {kw.arg for kw in node.keywords}
                expected = set(PLACEHOLDER_RE.findall(en[key]))
                if passed != expected:
                    problems.append(
                        f"{py.relative_to(BACKEND)}:{node.lineno} {key}: "
                        f"passes {sorted(passed)}, catalog wants {sorted(expected)}"
                    )
    assert not problems, "translate() params diverge from catalog:\n" + "\n".join(
        problems
    )


def test_template_seed_migrations_target_code_locale():
    """notification_templates is unique on (code, locale) since
    hrp478emaildb01 — a new seed migration reusing the old code-only
    conflict target would crash at deploy time. Pre-F4 migrations run
    before the constraint swap and are allowlisted."""
    pre_f4 = {
        "c3fc300775f8_seed_phase3_statuses_types_scales.py",
        "cr11a1b2c3d4e5f_competence_generation_sessions.py",
        "emp1a1b2c3d4e5_employee_status_email_templates.py",
        "hrp205redo01_question_set_notifications.py",
        "hrp84_assessment_notification_templates.py",
        "r4c1b2c3d4e5_r4c_notifications_onboarding_sharing.py",
    }
    offenders = []
    for py in (BACKEND / "migrations" / "versions").glob("*.py"):
        src = py.read_text(encoding="utf-8")
        if "notification_templates" not in src or py.name in pre_f4:
            continue
        if re.search(r"ON CONFLICT \(code\)", src):
            offenders.append(py.name)
    assert not offenders, (
        "template seed migrations must use ON CONFLICT (code, locale) "
        f"after hrp478emaildb01: {offenders}"
    )


# ---------------------------------------------------------------------------
# i18n F8 (HRP-482): hardcoded-string ratchet
# ---------------------------------------------------------------------------

# Accepted debt (HRP-477): bare ``HTTPException`` sites that stay English on
# purpose — dev/demo 404 guards where an AppError code (and its catalog key)
# would fingerprint a hidden surface, dev-only tooling, and str(exc)
# passthroughs. Everything new must raise AppError with an ``errors.*`` code.
# Exact counts: growth = a new untranslated site; shrink = migrate the
# number down here. Counted as constructions, not raises (HRP-511 item d), so
# building the exception first and raising it later is caught too.
BARE_HTTPEXCEPTION_ALLOWLIST = {
    "app/modules/ai_competence_generation/router.py": 2,
    "app/modules/auth/router.py": 2,
    "app/modules/auth/service.py": 2,
    "app/modules/competence/router.py": 2,
    "app/modules/demo/router.py": 1,
    "app/modules/employee/service.py": 2,
    "app/modules/recruitment/manager_assessment_router.py": 1,
    "app/modules/recruitment/resume_analysis_service.py": 1,
    "app/modules/recruitment/routers/e2e_seed.py": 11,
}

# Accepted debt (HRP-477): dynamic f-string ValueErrors in pydantic
# validators — the reverse-map lookup needs an exact English literal.
DYNAMIC_SCHEMA_VALUEERROR_ALLOWLIST = {
    "app/modules/employee/schemas.py": 2,
}


def _iter_sources() -> "list[tuple[Path, object]]":
    """(path, AST) for every backend module, ee included when present."""
    import ast

    out = []
    for base in (BACKEND / "app", BACKEND / "ee"):
        if not base.exists():  # community build ships without ee/
            continue
        for py in sorted(base.rglob("*.py")):
            out.append((py, ast.parse(py.read_text(encoding="utf-8"))))
    return out


def _is_named(func: object, name: str) -> bool:
    import ast

    return (isinstance(func, ast.Name) and func.id == name) or (
        isinstance(func, ast.Attribute) and func.attr == name
    )


def _count_constructions(name: str, sources) -> dict[str, int]:
    """Count every ``<name>(...)`` construction per file.

    HRP-511 (item d): the original ratchet only looked at ``raise X(...)``, so
    ``exc = HTTPException(...)`` followed by ``raise exc`` — or a helper
    returning a prebuilt exception — walked straight past it. Counting
    constructions instead covers both, and the numbers are identical while
    no indirect construction exists (which is the state this pins).
    """
    import ast
    from collections import Counter

    counts: Counter[str] = Counter()
    for py, tree in sources:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_named(node.func, name):
                counts[str(py.relative_to(BACKEND))] += 1
    return dict(counts)


def test_no_httpexception_aliases():
    """The construction scan matches on the name, so an aliased import
    (``from fastapi import HTTPException as HE``) would make every call
    site invisible to the ratchet below. Ban the alias instead of
    resolving it."""
    import ast

    aliased: list[str] = []
    for py, tree in _iter_sources():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for alias in node.names:
                if alias.asname and alias.name.rsplit(".", 1)[-1] in (
                    "HTTPException",
                    "AppError",
                ):
                    aliased.append(
                        f"{py.relative_to(BACKEND)}:{node.lineno} "
                        f"{alias.name} as {alias.asname}"
                    )
    assert not aliased, (
        "Aliased error-class imports hide call sites from the i18n "
        f"ratchets — import them under their own name: {aliased}"
    )


def test_no_new_bare_httpexceptions():
    """User-facing errors must be ``AppError("<code>")`` so they localize;
    a bare ``HTTPException(status, "some string")`` ships English to every
    locale. The allowlist pins the accepted F3 debt file-by-file.

    Every construction counts, wherever it is raised from — see
    :func:`_count_constructions`.
    """
    counts = _count_constructions("HTTPException", _iter_sources())
    grown = {
        path: n
        for path, n in counts.items()
        if n > BARE_HTTPEXCEPTION_ALLOWLIST.get(path, 0)
    }
    assert not grown, (
        "New bare HTTPException call sites (use AppError + errors.* catalog "
        f"key instead): {grown}; allowlisted: "
        f"{ {p: BARE_HTTPEXCEPTION_ALLOWLIST.get(p, 0) for p in grown} }"
    )
    shrunk = {
        path: counts.get(path, 0)
        for path in BARE_HTTPEXCEPTION_ALLOWLIST
        if counts.get(path, 0) < BARE_HTTPEXCEPTION_ALLOWLIST[path]
    }
    assert not shrunk, (
        "Bare HTTPException debt went down — ratchet the allowlist in this "
        f"test: {shrunk}"
    )


def test_schema_valueerrors_resolve_to_validation_catalog():
    """Custom ``ValueError`` messages in pydantic validators localize via
    the exact-English-string reverse map (F3 decision — schemas stay
    untouched). A new message that is not in ``errors.validation.*`` would
    silently ship English to de users.

    Scope: ``app/modules/**/*schemas.py`` (module convention, including
    suffixed files like ``manager_assessment_schemas.py``) plus the shared
    validators in ``app/core/validators.py``. ``app/config.py`` validators
    are startup config errors (deliberately out), ``ee/`` raises ValueError
    only for operator config. Edge cases: ``raise ValueError()`` with no
    args falls into the dynamic bucket (fail-safe), bare ``raise
    ValueError`` without a call is not matched."""
    import ast
    from collections import Counter

    from app.core.i18n import validation_key_for_message

    uncatalogued: list[str] = []
    dynamic: Counter[str] = Counter()
    scan_files = [
        *(BACKEND / "app" / "modules").rglob("*schemas.py"),
        BACKEND / "app" / "core" / "validators.py",
    ]
    for py in scan_files:
        rel = str(py.relative_to(BACKEND))
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id == "ValueError"
            ):
                continue
            arg = node.exc.args[0] if node.exc.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if validation_key_for_message(arg.value) is None:
                    uncatalogued.append(f"{rel}:{node.lineno} {arg.value!r}")
            else:
                dynamic[rel] += 1
    assert not uncatalogued, (
        "schema ValueError messages missing from errors.validation.* "
        "(add the exact string to en.json + de.json):\n"
        + "\n".join(f"  - {p}" for p in uncatalogued)
    )
    grown = {
        path: n
        for path, n in dynamic.items()
        if n > DYNAMIC_SCHEMA_VALUEERROR_ALLOWLIST.get(path, 0)
    }
    assert not grown, (
        "New dynamic (f-string) ValueError in pydantic validators — use a "
        f"constant message + errors.validation.* entry instead: {grown}"
    )
    shrunk = {
        path: dynamic.get(path, 0)
        for path in DYNAMIC_SCHEMA_VALUEERROR_ALLOWLIST
        if dynamic.get(path, 0) < DYNAMIC_SCHEMA_VALUEERROR_ALLOWLIST[path]
    }
    assert not shrunk, (
        "Dynamic ValueError debt went down — ratchet the allowlist in this "
        f"test: {shrunk}"
    )


def test_ai_preset_descriptions_match_frontend_catalog():
    """i18n F7 (HRP-481): the tier descriptions the ai-settings API
    returns are static English copy; the UI renders the catalog keys
    settings.aiPreset*Description instead. Keep both in sync so a
    backend wording change cannot silently diverge from what users see."""
    import json

    from app.modules.ai_settings.service import EFFORT_PRESETS

    en = json.loads(
        (BACKEND.parent / "frontend" / "messages" / "en.json").read_text(
            encoding="utf-8"
        )
    )["settings"]
    for tier, key in [
        ("fast", "aiPresetFastDescription"),
        ("balanced", "aiPresetBalancedDescription"),
        ("thorough", "aiPresetThoroughDescription"),
    ]:
        assert EFFORT_PRESETS[tier]["description"] == en[key], (
            f"ai_settings EFFORT_PRESETS[{tier!r}] description diverged "
            f"from settings.{key} in frontend/messages/en.json"
        )


# ---------------------------------------------------------------------------
# AppError ratchets (HRP-511 item d)
# ---------------------------------------------------------------------------

# AppError kwargs that are not catalog placeholders (see core/errors.py).
APPERROR_NON_PARAM_KWARGS = {
    "code",
    "status_code",
    "headers",
    "detail_extra",
    "detail_code_key",
    "detail_code",
}

# Accepted debt: AppError raised with a computed code, invisible to the
# literal scan in test_every_apperror_code_is_catalogued. The codes reach
# these helpers from their callers, so the catalog entry is only pinned by
# review. Exact counts — growth means a new blind spot.
DYNAMIC_APPERROR_CODE_ALLOWLIST = {
    "app/core/url_guard.py": 6,
}

# Catalog strings whose braces are literal text rather than parameters, so
# the call site correctly passes nothing (an API path in the message).
BRACES_ARE_LITERAL_TEXT = {"vacancy_if_match_required"}


def _apperror_calls(sources):
    """(path, node, code) for every AppError/CompetenceCycleError call;
    ``code`` is the literal string, or None when it is computed."""
    import ast

    for py, tree in sources:
        if py.parent.name == "core" and py.name == "errors.py":
            continue  # docstring examples and the class itself
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and (
                    _is_named(node.func, "AppError")
                    or _is_named(node.func, "CompetenceCycleError")
                )
            ):
                continue
            supplied = None
            if node.args:
                supplied = node.args[0]
            else:
                for kw in node.keywords:
                    if kw.arg == "code":
                        supplied = kw.value
            if supplied is None:
                continue  # subclass with its own literal default
            literal = (
                supplied.value
                if isinstance(supplied, ast.Constant)
                and isinstance(supplied.value, str)
                else None
            )
            yield py, node, literal


def test_dynamic_apperror_codes_are_ratcheted():
    """An ``AppError(code_variable)`` cannot be checked against the
    catalog, so a typo in the caller ships ``errors.<typo>`` to the user.
    New ones must be justified into the allowlist, not appear silently."""
    from collections import Counter

    counts: Counter[str] = Counter()
    for py, _node, literal in _apperror_calls(_iter_sources()):
        if literal is None:
            counts[str(py.relative_to(BACKEND))] += 1
    counts = dict(counts)

    grown = {
        path: n
        for path, n in counts.items()
        if n > DYNAMIC_APPERROR_CODE_ALLOWLIST.get(path, 0)
    }
    assert not grown, (
        "AppError raised with a computed code — the catalog key is then "
        f"unverifiable: {grown}"
    )
    shrunk = {
        path: counts.get(path, 0)
        for path in DYNAMIC_APPERROR_CODE_ALLOWLIST
        if counts.get(path, 0) < DYNAMIC_APPERROR_CODE_ALLOWLIST[path]
    }
    assert (
        not shrunk
    ), f"Dynamic AppError debt went down — ratchet the allowlist: {shrunk}"


def test_apperror_params_match_catalog_placeholders():
    """AppError interpolates its extra kwargs into the catalog string.

    A missing one makes ``str.format`` fail and ship the raw template
    (``translate`` degrades silently by design); an extra one is a typo
    that never renders. Same contract as the translate() check, on the
    other half of the catalog.
    """
    en = _catalog("en")
    problems: list[str] = []
    for py, node, literal in _apperror_calls(_iter_sources()):
        if literal is None:
            continue  # covered by the dynamic-code ratchet
        key = f"errors.{literal}"
        if key not in en:
            continue  # covered by test_every_apperror_code_is_catalogued
        if literal in BRACES_ARE_LITERAL_TEXT:
            continue
        if any(kw.arg is None for kw in node.keywords):
            continue  # **dynamic — not statically checkable
        passed = {
            kw.arg for kw in node.keywords if kw.arg not in APPERROR_NON_PARAM_KWARGS
        }
        expected = set(PLACEHOLDER_RE.findall(en[key]))
        if passed != expected:
            problems.append(
                f"{py.relative_to(BACKEND)}:{node.lineno} {literal}: "
                f"passes {sorted(passed)}, catalog wants {sorted(expected)}"
            )
    assert not problems, "AppError params diverge from catalog:\n" + "\n".join(problems)


def test_template_seed_migrations_use_brand_placeholder():
    """HRP-515 rewrote the seeded 'HRPulsar' literals to {{ brand_name }}
    via one-shot REPLACE migrations that never run again — a new locale
    seed copied from an old wave (as ee011 was copied from hrp481) would
    silently reintroduce the literal on branded installs. Historical
    seeds (rewritten in place by the REPLACE) and the REPLACE migrations
    themselves are allowlisted; every other template migration must use
    the placeholder."""
    allowed = {
        "c3fc300775f8_seed_phase3_statuses_types_scales.py",
        "hrp481detemplates01_german_notification_templates.py",
        "ee011_russian_notification_templates.py",
        "hrp515_brand_template_placeholder.py",
        "ee012_brand_template_placeholder.py",
    }
    offenders = []
    for py in (BACKEND / "migrations" / "versions").rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        if "notification_templates" not in src or py.name in allowed:
            continue
        if "HRPulsar" in src:
            offenders.append(py.name)
    assert not offenders, (
        "template migrations must reference {{ brand_name }} instead of "
        f"the hardcoded brand (HRP-515): {offenders}"
    )
