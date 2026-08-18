"""Locale overlay for the demo seed fixtures.

The English fixtures in ``seed_data*.py`` stay the single source of
truth for the demo's *structure*; this module translates their
display strings at clone time so white-label deployments with a
non-English ``DEFAULT_LOCALE`` hand demo visitors localized content.

Mechanics:

* Per-locale catalogs live in ``seed_assets/seed_i18n_<locale>.json``
  as a flat ``{english string: translated string}`` map. A missing
  entry (or a missing catalog) degrades to the English source — the
  seed can never break because of a translation gap.
* :func:`localize` deep-copies a fixture structure and rewrites the
  string values under :data:`TRANSLATABLE_KEYS`. Everything else —
  ``key`` slugs, emails, enum codes, and the titles that resolve
  origin rows by name (``GRADES``, ``SKILL_LEVELS``) — must stay
  byte-identical to the English source, so those structures are never
  passed through :func:`localize` at all.
* ``language`` fields carrying ``"en"`` (vacancy content language) are
  rewritten to the active seed locale so the stored rows describe
  their own content truthfully.
* :func:`collect_translatable_strings` walks every localized fixture
  with the same key set; the coverage guard test uses it to fail when
  a new English string lands without a catalog entry. Deliberate
  keep-as-is strings (proper nouns, code snippets, book titles) get an
  identity entry in the catalog.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_CATALOG_DIR = Path(__file__).resolve().parent / "seed_assets"


# Dict keys whose string (or list-of-string) values are human-readable
# display text in the seed fixtures. ``title`` deliberately covers exam
# question/option titles too — technical option values ("main",
# "pytest", code snippets) carry identity entries in the catalog.
TRANSLATABLE_KEYS = frozenset(
    {
        "title",
        "name",
        "description",
        "location",
        "current_position",
        "ai_summary",
        "ai_strength",
        "ai_risk",
        "ai_mitigation",
        "verdict_summary",
        "key_strength",
        "key_risk",
        "risk_mitigation",
        "evidence",
        "competence",
        "subject_data",
        "transcript",
        "title_prefix",
        "soft_competences",
        "disqualifiers",
        "process_findings",
        "blind_spots",
        "red_flags",
        # Nested inside ``blind_spots`` items (BlindSpot schema).
        "suggested_question",
    }
)


# Inline literals from ``seed.py`` that go through :func:`translate`
# directly (interview titles, notes templates). Kept here so the
# coverage guard sees them alongside the fixture strings.
EXTRA_STRINGS: tuple[str, ...] = (
    "Technical + system design — Elena Volkov",
    "Recruiter screen — Tomás Becker",
    "[Transcript redacted for demo brevity.]",
    "Investor demo interview.",
    "Investor demo interview (S7 extras).",
    "Investor demo candidate ({key}).",
)


def catalog_path(locale: str) -> Path:
    return _CATALOG_DIR / f"seed_i18n_{locale}.json"


def ee_asset_path(name: str) -> Path | None:
    """Enterprise-only seed asset (open-core mechanism 3).

    Locales offered only on white-label installations (``ru``) keep
    their seed catalogs and transcripts in ``backend/ee/demo_seed/`` —
    the public-repo sync blocks Cyrillic, so the content must never
    live under ``seed_assets/``. Community builds have no ``ee``
    package and fall through to the English source.
    """
    try:
        from ee.i18n_catalogs import demo_seed_dir
    except ImportError:
        return None
    return demo_seed_dir() / name


@lru_cache(maxsize=8)
def _load_catalog(locale: str) -> dict[str, str]:
    name = f"seed_i18n_{locale}.json"
    for path in (catalog_path(locale), ee_asset_path(name)):
        if path is None:
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        except ValueError:
            logger.warning("demo seed i18n: catalog at %s is not valid JSON", path)
            continue
        return {
            key: value
            for key, value in raw.items()
            if isinstance(key, str) and isinstance(value, str)
        }
    return {}


def seed_locale() -> str:
    """Locale the demo seed renders in: the deployment default when a
    catalog ships for it, English otherwise."""
    locale = settings.default_locale
    if locale == "en" or not _load_catalog(locale):
        return "en"
    return locale


def translate(text: str, locale: str | None = None) -> str:
    """Translate a single display string, falling back to the source."""
    loc = seed_locale() if locale is None else locale
    if loc == "en":
        return text
    return _load_catalog(loc).get(text, text)


def localize(value: Any, locale: str | None = None) -> Any:
    """Deep-copy a fixture structure with display strings translated.

    For the English locale the input is returned as-is (the seeders
    never mutate the fixture specs, so sharing is safe).
    """
    loc = seed_locale() if locale is None else locale
    if loc == "en":
        return value
    return _walk(deepcopy(value), loc)


def _walk(node: Any, loc: str) -> Any:
    if isinstance(node, dict):
        return {key: _walk_value(key, value, loc) for key, value in node.items()}
    if isinstance(node, list):
        return [_walk(item, loc) for item in node]
    return node


def _walk_value(key: Any, value: Any, loc: str) -> Any:
    # Vacancy content-language marker: the localized rows must describe
    # their own content, not the English source's.
    if key == "language" and value == "en":
        return loc
    if key in TRANSLATABLE_KEYS:
        if isinstance(value, str):
            return translate(value, loc)
        if isinstance(value, list):
            return [
                translate(item, loc) if isinstance(item, str) else _walk(item, loc)
                for item in value
            ]
    if isinstance(value, (dict, list)):
        return _walk(value, loc)
    return value


def _collect(node: Any, out: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "language":
                continue
            if key in TRANSLATABLE_KEYS:
                if isinstance(value, str):
                    out.add(value)
                    continue
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            out.add(item)
                        else:
                            _collect(item, out)
                    continue
            _collect(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect(item, out)


def localized_structures() -> list[Any]:
    """Every fixture structure the seed passes through :func:`localize`.

    Imported lazily to keep this module importable without dragging the
    full fixture pack in at bootstrap. ``GRADES``, ``SKILL_LEVELS``,
    ``NAME_POOL`` and ``EMPLOYEE_ASSIGNMENTS`` are deliberately absent:
    the first two resolve origin rows by title, the last two carry no
    display text.
    """
    from app.modules.demo.seed_data import (
        ELENA_INTERVIEW_ANALYSIS,
        TOMAS_INTERVIEW_ANALYSIS,
        VACANCIES,
        candidates,
    )
    from app.modules.demo.seed_data_assessments import ASSESSMENTS, PDPS
    from app.modules.demo.seed_data_company import (
        DIVISIONS,
        GRADE_SPECIALIZATIONS,
        POSITIONS,
        SPECIALIZATIONS,
    )
    from app.modules.demo.seed_data_competences import (
        COMPETENCE_GROUPS,
        COMPETENCES,
        INDICATORS,
        MATERIALS,
    )
    from app.modules.demo.seed_data_exams import MASS_EXAMS
    from app.modules.demo.seed_data_misc import CUSTOM_DICTIONARIES, NOTIFICATIONS
    from app.modules.demo.seed_data_recruitment_extras import (
        EXTRA_CANDIDATES,
        EXTRA_VACANCIES,
        INTERVIEW_SHAPES,
    )
    from app.modules.demo.seed_data_talent_market import TALENT_CARDS

    return [
        VACANCIES,
        candidates(),
        ELENA_INTERVIEW_ANALYSIS,
        TOMAS_INTERVIEW_ANALYSIS,
        DIVISIONS,
        SPECIALIZATIONS,
        POSITIONS,
        GRADE_SPECIALIZATIONS,
        COMPETENCE_GROUPS,
        COMPETENCES,
        INDICATORS,
        MATERIALS,
        ASSESSMENTS,
        PDPS,
        MASS_EXAMS,
        CUSTOM_DICTIONARIES,
        NOTIFICATIONS,
        EXTRA_VACANCIES,
        EXTRA_CANDIDATES,
        INTERVIEW_SHAPES,
        TALENT_CARDS,
    ]


def collect_translatable_strings() -> set[str]:
    """All display strings a locale catalog must cover."""
    out: set[str] = set()
    for structure in localized_structures():
        _collect(structure, out)
    out.update(EXTRA_STRINGS)
    return out
