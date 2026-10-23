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
        assert set(_PLACEHOLDER.findall(source)) == set(_PLACEHOLDER.findall(target)), (
            f"placeholder mismatch for {source!r}"
        )


@pytest.mark.parametrize("locale", sorted({"en", "ru", *_catalog_locales()}))
def test_admin_name_splits_into_first_and_last(locale: str):
    # ``service._create_demo_user`` partitions the localized admin name on
    # its first space (HRP-713); an entry that is not exactly two tokens
    # hands the demo admin an empty or wrong last name. ``ru`` ships from
    # ``ee/`` and degrades to the English source on a community build.
    parts = seed_i18n.translate("Ian Steward", locale).split(" ")
    assert len(parts) == 2 and all(parts), parts


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
    assert "Kandidatin: Elena Vogel" in transcript


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
                Interview.title == "Technik + Systemdesign — Elena Vogel",
            )
        )
    ).scalar_one()
    assert "Kandidatin: Elena Vogel" in elena.transcript
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

    # Employee names are display text too — a German demo is staffed by
    # Germans. The email follows the name (it is a column on /employees),
    # which is exactly what could strand the "view as employee" persona:
    # ``switch_demo_view`` resolves NAME_POOL idx 38 through the same
    # ``localized_name_pool`` the seed wrote with.
    from app.modules.auth.models import User as AuthUser
    from app.modules.demo.seed_data_employees import localized_name_pool
    from app.modules.demo.service import DEMO_EMPLOYEE_PERSONA_INDEX

    persona_email = localized_name_pool()[DEMO_EMPLOYEE_PERSONA_INDEX][2]
    assert persona_email == "volker.luecke@demo.example.com"
    persona = (
        await db.execute(
            select(AuthUser).where(
                AuthUser.tenant_id == tenant.id,
                AuthUser.email == persona_email,
            )
        )
    ).scalar_one()
    assert (persona.first_name, persona.last_name) == ("Volker", "Lücke")


# ---------------------------------------------------------------------------
# HRP-1000 — a candidate's email, phone and LinkedIn follow the localized name
# ---------------------------------------------------------------------------

# Lower-case Cyrillic a..ya is the contiguous block U+0430..U+044F (yo sits
# apart); spelt out the way the catalog spells the addresses. Code points,
# not letters: core sources stay ASCII for the public repo.
# fmt: off
_RU_SPELLING = [
    "a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k", "l", "m",
    "n", "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh",
    "shch", "", "y", "", "e", "yu", "ya",
]
# fmt: on
_RU_LATIN = dict(
    zip((chr(code) for code in range(0x430, 0x450)), _RU_SPELLING, strict=True)
)
_RU_LATIN["\u0451"] = "e"
_DE_LATIN = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def _ascii(word: str) -> str:
    """How a name is spelt in an address: umlauts and Cyrillic spelt out,
    accents and apostrophes dropped."""
    import unicodedata

    spelt = "".join(_DE_LATIN.get(ch, _RU_LATIN.get(ch, ch)) for ch in word.lower())
    return (
        unicodedata.normalize("NFKD", spelt)
        .encode("ascii", "ignore")
        .decode()
        .replace("'", "")
    )


@pytest.mark.parametrize("locale", ["en", "de", "ru"])
def test_candidate_contacts_follow_the_name_in_every_locale(locale: str):
    """QA saw a localized name next to elena.volkov@example.com on the ru
    site and "Elena Volkov" on the en one. Every external candidate's
    email spells their name in the seed locale, the LinkedIn handle is
    the same spelling, and no two candidates share an address."""
    from app.modules.demo.seed_data import candidates
    from app.modules.demo.seed_data_recruitment_extras import EXTRA_CANDIDATES

    if locale != "en" and not seed_i18n._load_catalog(locale):
        pytest.skip(f"no {locale} seed catalog in this build")
    emails = []
    for spec in (*candidates(), *EXTRA_CANDIDATES):
        if spec.get("employee_index") is not None:
            continue  # the internal applicant is his employee row (HRP-679)
        first, last = seed_i18n.translate(
            f"{spec['first_name']} {spec['last_name']}", locale
        ).split(" ", 1)
        email = seed_i18n.translate(spec["email"], locale)
        local = f"{_ascii(first)}.{_ascii(last)}"
        assert email == f"{local}@example.com", (locale, first, last, email)
        if spec.get("linkedin"):
            assert seed_i18n.translate(spec["linkedin"], locale) == (
                "linkedin.com/in/" + local.replace(".", "")
            )
        emails.append(email)
    assert len(set(emails)) == len(emails)


def test_the_headline_candidate_is_elena_volkova():
    """The en name QA asked for — a Russian surname takes the feminine form."""
    from app.modules.demo.seed_data import DEMO_FIRST_SCREEN_CANDIDATE_EMAIL, candidates

    elena = next(c for c in candidates() if c["first_name"] == "Elena")
    assert (elena["last_name"], DEMO_FIRST_SCREEN_CANDIDATE_EMAIL) == (
        "Volkova",
        "elena.volkova@example.com",
    )


@pytest.mark.asyncio
async def test_clone_seed_builds_the_candidate_card_in_the_seed_locale(
    db: AsyncSession, tenant, user, monkeypatch
):
    """HRP-1000: the stored row and its parsed resume agree with the name."""
    from app.modules.recruitment.models import Candidate

    monkeypatch.setattr(settings, "available_locales", "de,en")
    monkeypatch.setattr(settings, "default_locale", "de")
    tenant.is_demo = True
    await db.commit()
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    elena = (
        await db.execute(
            select(Candidate).where(
                Candidate.tenant_id == tenant.id,
                Candidate.full_name == "Elena Vogel",
            )
        )
    ).scalar_one()
    assert elena.email == "elena.vogel@example.com"
    assert elena.linkedin_url == "linkedin.com/in/elenavogel"
    assert elena.location == "Berlin, Deutschland"
    contacts = elena.parsed_resume_jsonb["contacts"]
    assert contacts == {
        "email": "elena.vogel@example.com",
        "phone": elena.phone,
        "linkedin": "linkedin.com/in/elenavogel",
    }
    # The extras follow the same rule.
    assert (
        await db.execute(
            select(Candidate.email).where(
                Candidate.tenant_id == tenant.id,
                Candidate.full_name == "Isabell Färber",
            )
        )
    ).scalar_one() == "isabell.faerber@example.com"


@pytest.mark.parametrize("locale", ["en", "de", "ru"])
async def test_seeded_interviews_carry_their_candidate_name_and_none_awaits_an_upload(
    db: AsyncSession, tenant, user, skill_levels, monkeypatch, locale: str
):
    """HRP-980 (QA 21.10): the screen of the candidate the ru catalog calls
    Helena Brennan sat "in_progress" with nothing uploaded, so it read as
    an upload that never comes - it is scheduled. The name in every
    interview title is the candidate's own, in every seed locale, and every
    interview has a recording type the page can name ("technical" was
    none: Details read "Type -")."""
    from app.modules.recruitment.models import Candidate, CandidateVacancy

    if locale != "en" and not seed_i18n._load_catalog(locale):
        pytest.skip(f"no {locale} seed catalog in this build")
    monkeypatch.setattr(settings, "available_locales", f"{locale},en")
    monkeypatch.setattr(settings, "default_locale", locale)
    tenant.is_demo = True
    await db.commit()
    await clone_seed_into_demo_tenant(db, tenant.id, owner_user_id=user.id)
    await db.commit()

    rows = (
        await db.execute(
            select(Interview, Candidate.full_name)
            .join(
                CandidateVacancy, CandidateVacancy.id == Interview.candidate_vacancy_id
            )
            .join(Candidate, Candidate.id == CandidateVacancy.candidate_id)
            .where(Interview.tenant_id == tenant.id)
        )
    ).all()
    assert rows
    for interview, name in rows:
        assert interview.title.endswith(f" — {name}"), (interview.title, name)
        if not (
            interview.audio_file_id
            or interview.video_file_id
            or interview.transcript_file_id
            or interview.transcript
        ):
            assert interview.status == "scheduled", interview.title
            assert interview.type == "undecided", interview.title
        elif not interview.audio_file_id:
            assert interview.type == "text_transcript", interview.title
    helena = seed_i18n.translate("Helena Brennan", locale)
    assert [i.status for i, name in rows if name == helena] == ["scheduled"]


@pytest.mark.parametrize("locale", ["en", "de", "ru"])
def test_the_recording_speaks_the_transcript_of_its_locale(locale: str, monkeypatch):
    """HRP-980 (QA 21.10): Elena's recording is voiced from the transcript
    of the seed locale, line by line - each [HH:MM:SS] is where its line
    starts, so they all fall inside the recording, which is no longer than
    the conversation (no silence padding it to a round length), and the
    header's duration is the recording's own. The recordings are
    enterprise-only (``ee/demo_seed/``)."""
    pytest.importorskip("ee.i18n_catalogs")
    from app.modules.demo.seed import elena_recording
    from app.modules.demo.seed_data import parse_transcript_segments
    from app.modules.recruitment.media_duration import get_audio_duration_seconds

    if locale != "en" and not seed_i18n._load_catalog(locale):
        pytest.skip(f"no {locale} seed catalog in this build")
    monkeypatch.setattr(settings, "available_locales", f"{locale},en")
    monkeypatch.setattr(settings, "default_locale", locale)

    recording = elena_recording()
    suffix = "" if locale == "en" else f".{locale}"
    assert recording is not None
    assert recording.name == f"interview-recording-elena{suffix}.mp3"
    assert recording.parent.name == "demo_seed"
    seconds = get_audio_duration_seconds(str(recording))
    assert seconds

    transcript = load_transcript()
    starts = [row["start_sec"] for row in parse_transcript_segments(transcript)]
    assert len(starts) > 40 and starts == sorted(set(starts))
    assert starts[-1] < seconds < starts[-1] + 30
    assert f": {round(seconds / 60)} " in transcript.splitlines()[4]
