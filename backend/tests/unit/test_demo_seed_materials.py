"""Demo learning materials — the link has to be the thing the title names.

HRP-767: on demo, every development plan carrying content opened the
wrong page. The worst of it was an internal product tour, formatted as a
Course, linking to ``hrpulsar.com/docs/features`` — the product's own
documentation standing in for a course that does not exist. The quieter
half was a book pointing at an encyclopedia entry about its author.

The seed has no real course catalogue behind it, so the rule is not
"every material has a link". It is: a material either links to the
resource its own title and format promise, or it carries no link at all
and the card says so (HRP-712).
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest
from app.modules.demo.seed_data_assessments import PDPS
from app.modules.demo.seed_data_competences import GRADE_COMPETENCE_LINKS, MATERIALS

# The product's own site is never a learning resource for the demo
# company: a "course" that opens our documentation is the reported bug.
_PRODUCT_DOMAIN = "hrpulsar.com"
# A video material must point at something that plays.
_VIDEO_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "vimeo.com"}
# An encyclopedia entry about a book (or its author) is not the book.
_REFERENCE_HOSTS = {"en.wikipedia.org", "wikipedia.org"}


def _host(link: str) -> str:
    return (urlparse(link).hostname or "").lower()


def _linked() -> list[dict]:
    return [m for m in MATERIALS if m["link"]]


def test_the_fixture_still_carries_linked_materials():
    """Tripwire: the assertions below all pass vacuously on an empty set."""
    assert len(_linked()) >= 20, "the demo lost its linked materials"


@pytest.mark.parametrize("material", _linked(), ids=lambda m: m["title"][:40])
def test_link_is_an_absolute_public_url(material: dict):
    parsed = urlparse(material["link"])
    assert parsed.scheme == "https", material["link"]
    assert parsed.hostname, material["link"]
    assert not (parsed.hostname or "").endswith(_PRODUCT_DOMAIN), (
        f"{material['title']!r} points at our own site instead of the "
        f"resource it names: {material['link']}"
    )


@pytest.mark.parametrize("material", MATERIALS, ids=lambda m: m["title"][:40])
def test_internal_material_carries_no_public_link(material: dict):
    """An in-house workshop has no public URL. Inventing one is how the
    product tour ended up pointing at the docs site."""
    if material["material_type"] == "internal":
        assert material["link"] is None, (
            f"{material['title']!r} is an internal material with a public link"
        )


@pytest.mark.parametrize("material", MATERIALS, ids=lambda m: m["title"][:40])
def test_external_material_carries_a_link(material: dict):
    """The other half of the rule (review follow-up).

    ``internal`` with no link is a material the reader can still act on --
    it names an in-house session. ``external`` with no link is a dead end:
    the card promises a public resource and then offers no way to reach
    it. A title that names nothing public belongs on the internal side.
    """
    if material["material_type"] == "external":
        assert material["link"], (
            f"{material['title']!r} is external but opens nothing -- give it "
            f"the URL its title names, or mark it internal"
        )


@pytest.mark.parametrize("material", _linked(), ids=lambda m: m["title"][:40])
def test_link_matches_the_declared_format(material: dict):
    host = _host(material["link"])
    if material["format"] == "video":
        assert host in _VIDEO_HOSTS, (
            f"{material['title']!r} is a video pointing at {host}"
        )
    if material["format"] == "book":
        assert host not in _REFERENCE_HOSTS, (
            f"{material['title']!r} is a book pointing at an encyclopedia "
            f"article ({material['link']}) rather than the book"
        )


# HRP-767 REDO: the product owner wants every plan in progress on the demo to
# show what a plan can carry -- a book, a course, an article and a video, each
# opening. The seed attaches a competence's materials up to the plan grade's
# rung on the ladder (``_seed_assessments_and_pdps``), so this recomputes that
# selection from the fixtures alone and asks the four kinds of it.
_ALL_KINDS = {"book", "course", "article", "video"}


def _rung(skill_level_key: str) -> int:
    """``sl-l3`` -> 3: the seeded ladder keys carry their sort order."""
    return int(skill_level_key.rsplit("-l", 1)[1])


def _materials_of_in_progress_plan(plan: dict) -> list[dict]:
    ladder = {
        (link["grade_key"], link["specialization_key"], link["competence_key"]): (
            _rung(link["skill_level_key"])
        )
        for link in GRADE_COMPETENCE_LINKS
    }
    out: list[dict] = []
    for item in plan["items"]:
        competence_key = item.get("competence_key")
        if not competence_key:
            continue
        cap = ladder.get(
            (plan["grade_key"], plan["specialization_key"], competence_key)
        )
        out.extend(
            m
            for m in MATERIALS
            if m["competence_key"] == competence_key
            and (cap is None or _rung(m["skill_level_key"]) <= cap)
        )
    return out


_IN_PROGRESS = [p for p in PDPS if p["status"] == "in_progress"]


def test_the_demo_still_has_plans_in_progress():
    assert len(_IN_PROGRESS) >= 3, "the demo lost its in-progress plans"


@pytest.mark.parametrize("plan", _IN_PROGRESS, ids=lambda p: p["title"][:40])
def test_every_in_progress_demo_plan_offers_all_four_kinds_with_a_link(plan: dict):
    linked_kinds = {
        m["format"] for m in _materials_of_in_progress_plan(plan) if m["link"]
    }
    assert linked_kinds >= _ALL_KINDS, (
        f"{plan['title']!r} opens without a linked "
        f"{sorted(_ALL_KINDS - linked_kinds)} among its materials"
    )
