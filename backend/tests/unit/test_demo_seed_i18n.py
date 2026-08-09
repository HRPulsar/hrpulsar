"""Demo seed localization — catalog coverage guard + de clone.

The demo seed stays English single-source; ``seed_i18n`` overlays a
per-locale catalog at clone time so white-label deployments hand demo
visitors localized content. Three layers under test:

1. Coverage guard: every display string the fixtures carry must have an
   explicit entry in ``seed_i18n_de.json`` (identity entries mark
   deliberate keep-as-is decisions). Fails when a new English fixture
   string lands without a catalog decision.
2. Walker semantics: English passthrough, catalog lookup, the
   ``language: "en"`` → seed-locale rewrite, unsupported-locale
   fallback.
3. End-to-end: ``clone_seed_into_demo_tenant`` under
   ``DEFAULT_LOCALE=de`` produces German rows (vacancies, divisions,
   competences, interview analysis, transcript) and pins notification
   templates to the de rows when they exist.
"""

from __future__ import annotations

import re

import pytest
from app.config import settings
from app.modules.company.models import Division
from app.modules.competence.models import Competence
from app.modules.demo import seed_i18n
from app.modules.demo.seed import clone_seed_into_demo_tenant
from app.modules.demo.seed_data import VACANCIES, load_transcript
from app.modules.notification.models import Notification, NotificationTemplate
from app.modules.recruitment.models import Interview, Vacancy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def _catalog_locales() -> list[str]:
    """Every locale that ships a seed catalog — new languages join the
    coverage guard just by adding their ``seed_i18n_<locale>.json``."""
    return sorted(
        path.stem.removeprefix("seed_i18n_")
        for path in seed_i18n._CATALOG_DIR.glob("seed_i18n_*.json")
    )


def test_de_catalog_ships():
    assert "de" in _catalog_locales()


@pytest.mark.parametrize("locale", _catalog_locales())
def test_catalog_covers_every_translatable_string(locale: str):
    collected = seed_i18n.collect_translatable_strings()
    catalog = seed_i18n._load_catalog(locale)
    assert catalog, f"seed_i18n_{locale}.json missing or empty"

    missing = sorted(collected - set(catalog))
    assert not missing, (
        f"New demo-seed display strings without a {locale} catalog entry "
        f"(add them to seed_i18n_{locale}.json, identity value if "
        f"deliberately kept English): {missing}"
    )

    stale = sorted(set(catalog) - collected)
    assert not stale, (
        f"seed_i18n_{locale}.json carries entries no fixture references: {stale}"
    )


@pytest.mark.parametrize("locale", _catalog_locales())
def test_catalog_preserves_placeholders(locale: str):
    for source, target in seed_i18n._load_catalog(locale).items():
        assert set(_PLACEHOLDER.findall(source)) == set(
            _PLACEHOLDER.findall(target)
        ), f"placeholder mismatch for {source!r}"


def test_localize_is_passthrough_for_english():
    assert seed_i18n.seed_locale() == "en"
    assert seed_i18n.localize(VACANCIES) is VACANCIES
    assert seed_i18n.translate("Distributed systems") == "Distributed systems"


def test_localize_translates_and_rewrites_language(monkeypatch):
    monkeypatch.setattr(settings, "available_locales", "de,en")
    monkeypatch.setattr(settings, "default_locale", "de")

    localized = seed_i18n.localize(VACANCIES)
    assert localized is not VACANCIES
    senior = next(v for v in localized if v["key"] == "senior-backend")
    assert senior["language"] == "de"
    assert senior["description"].startswith("Verantworte die Merchant-Settlement")
    names = {c["name"] for c in senior["profile"]["competences"]}
    assert "Verteilte Systeme" in names
    # The English source must stay untouched (deep copy).
    original = next(v for v in VACANCIES if v["key"] == "senior-backend")
    assert original["language"] == "en"


def test_seed_locale_falls_back_without_catalog(monkeypatch):
    monkeypatch.setattr(settings, "available_locales", "fr,en")
    monkeypatch.setattr(settings, "default_locale", "fr")
    assert seed_i18n.seed_locale() == "en"
    assert seed_i18n.localize(VACANCIES) is VACANCIES


def test_load_transcript_picks_de_variant(monkeypatch):
    monkeypatch.setattr(settings, "available_locales", "de,en")
    monkeypatch.setattr(settings, "default_locale", "de")
    transcript = load_transcript()
    assert "Kandidatin: Elena Volkov" in transcript


@pytest.mark.asyncio
async def test_clone_seed_localizes_content_de(
    db: AsyncSession, tenant, user, skill_levels, monkeypatch
):
    monkeypatch.setattr(settings, "available_locales", "de,en")
    monkeypatch.setattr(settings, "default_locale", "de")

    tenant.is_demo = True
    await db.commit()

    result = await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()
    assert result["skipped"] is False

    # Vacancy: title deliberately stays English (German job-market
    # convention), the prose description must be German and the row must
    # declare its content language truthfully.
    senior = (
        await db.execute(
            select(Vacancy).where(
                Vacancy.tenant_id == tenant.id,
                Vacancy.title == "Senior Backend Engineer — Payments",
            )
        )
    ).scalar_one()
    assert senior.description.startswith("Verantworte die Merchant-Settlement")
    assert senior.language == "de"

    engineering = (
        await db.execute(
            select(Division).where(
                Division.tenant_id == tenant.id,
                Division.name == "Engineering",
            )
        )
    ).scalar_one()
    assert engineering.description == "Baut und betreibt die HRPulsar-Plattform."

    distributed = (
        await db.execute(
            select(Competence).where(
                Competence.tenant_id == tenant.id,
                Competence.title == "Verteilte Systeme",
            )
        )
    ).scalar_one_or_none()
    assert distributed is not None

    elena = (
        await db.execute(
            select(Interview).where(
                Interview.tenant_id == tenant.id,
                Interview.title == "Technik + Systemdesign — Elena Volkov",
            )
        )
    ).scalar_one()
    assert "Kandidatin: Elena Volkov" in elena.transcript
    assert elena.analysis_data["verdict_summary"].startswith("Klare Empfehlung.")

    # Notification templates: pinned to the de row per code when the
    # i18n migrations shipped one, English fallback otherwise.
    rows = (
        await db.execute(
            select(NotificationTemplate.code, NotificationTemplate.locale)
            .join(Notification, Notification.template_id == NotificationTemplate.id)
            .where(Notification.tenant_id == tenant.id)
        )
    ).all()
    de_codes = set(
        (
            await db.execute(
                select(NotificationTemplate.code).where(
                    NotificationTemplate.locale == "de"
                )
            )
        ).scalars()
    )
    for code, locale in rows:
        expected = "de" if code in de_codes else "en"
        assert locale == expected, f"template {code} pinned to {locale}"
