"""HRP-379 / HRP-714: two notification templates reworded after QA.

The unit database is built from model metadata, so migrations never run
here. These tests pin the ``hrp379714tplcopy`` swap table against the
seeds as they shipped: (a) every shipped fragment is really in the seed,
so the UPDATE hits instead of silently doing nothing; (b) the reworded
template renders what QA asked for, in the letter and in the bell;
(c) swapping back gives the shipped text, which is what ``downgrade`` does.
"""

from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType

from app.modules.notification.models import NotificationTemplate
from app.modules.notification.service import (
    render_db_template,
    render_db_template_preview,
)
from jinja2 import Template

_VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
_SUBMITTED = "recruitment.assessment_evaluator_submitted"
_PLAN = "talent_market.plan_requested"


def _module(filename: str) -> ModuleType:
    path = _VERSIONS / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _swaps() -> tuple:
    return _module("hrp379714tplcopy_notification_template_wording.py").SWAPS


def _reword(code: str, locale: str, column: str, text: str, *, back=False) -> str:
    """Apply the migration's swaps for one row/column, as its SQL would."""
    swaps = [s for s in _swaps() if s[:3] == (code, locale, column)]
    for _code, _locale, _column, shipped, new in swaps[::-1] if back else swaps:
        old, repl = (new, shipped) if back else (shipped, new)
        assert old in text, f"{old!r} is not in the {code}/{locale} {column}"
        text = text.replace(old, repl)
    return text


def _submitted_seed() -> dict[str, tuple[str, str]]:
    seed = _module("hrp379submittpl01_evaluator_submitted_template.py")
    return {locale: (subject, body) for locale, subject, body in seed._TEMPLATES}


def _plan_seed() -> dict[str, tuple[str, str]]:
    seed = _module("hrp714tmreactiongap_talent_market_reaction_gap_templates.py")
    return {
        locale: (subject, body)
        for code, locale, subject, body in seed._TEMPLATES
        if code == _PLAN
    }


class TestEvaluatorSubmittedLink:
    """HRP-379 (QA 14.09): the link says it opens the assessments."""

    _LINKS = {
        "en": ("Open the candidate", "Open candidate's assessments"),
        "de": ("Kandidat öffnen", "Bewertungen des Kandidaten öffnen"),
    }

    def test_only_the_link_text_changes(self) -> None:
        for locale, (subject, body) in _submitted_seed().items():
            shipped_link, new_link = self._LINKS[locale]
            new_body = _reword(_SUBMITTED, locale, "body_template", body)
            assert f">{new_link}</a>" in new_body
            assert shipped_link not in new_body
            # Everything but the anchor text is the letter as it shipped.
            assert new_body.replace(new_link, shipped_link) == body
            assert _reword(_SUBMITTED, locale, "subject_template", subject) == subject

    def test_rendered_letter_links_to_the_assessments(self) -> None:
        _subject, body = _submitted_seed()["en"]
        rendered = Template(_reword(_SUBMITTED, "en", "body_template", body)).render(
            candidate_name="Jane Doe",
            evaluator_name="Ext Eval",
            vacancy_title="QA Engineer",
            round_type="interview",
            round_number=2,
            link_url="https://app.example.com/recruitment/candidates/x",
        )
        assert (
            '<a href="https://app.example.com/recruitment/candidates/x">'
            "Open candidate's assessments</a>" in rendered
        )
        assert "QA Engineer" in rendered and "Interview 2" in rendered


class TestPlanRequestedWording:
    """HRP-714 (QA 10.09): "{name} requests a development plan for {card}"
    in the bell and the letter; the letter's link opens the matches."""

    _EXPECTED = {
        "en": (
            "Jane Doe requests a development plan for Platform Architect",
            "View candidate matches",
        ),
        "de": (
            "Jane Doe bittet um einen Entwicklungsplan für Platform Architect",
            "Übereinstimmungen des Kandidaten ansehen",
        ),
    }
    _CONTEXT = {"employee_name": "Jane Doe", "card_title": "Platform Architect"}

    def _template(self, locale: str) -> NotificationTemplate:
        subject, body = _plan_seed()[locale]
        return NotificationTemplate(
            code=_PLAN,
            locale=locale,
            subject_template=_reword(_PLAN, locale, "subject_template", subject),
            body_template=_reword(_PLAN, locale, "body_template", body),
            notification_type="email",
        )

    def test_bell_title_and_text_name_the_card(self) -> None:
        # The bell renders without ``link_url`` (the row is the link).
        for locale, (sentence, link_text) in self._EXPECTED.items():
            title, message = render_db_template_preview(
                self._template(locale), {**self._CONTEXT, "link_url": None}
            )
            assert title == sentence
            assert message == f"{sentence}."
            assert link_text not in message

    def test_letter_says_the_same_and_links_to_the_matches(self) -> None:
        for locale, (_sentence, link_text) in self._EXPECTED.items():
            body = Template(self._template(locale).body_template).render(
                **self._CONTEXT, link_url="https://app.example.com/talent-market/c"
            )
            assert (
                f'<a href="https://app.example.com/talent-market/c">{link_text}</a>'
                in body
            )

    def test_downgrade_restores_the_shipped_text(self) -> None:
        for locale, (subject, body) in _plan_seed().items():
            template = self._template(locale)
            assert (
                _reword(
                    _PLAN,
                    locale,
                    "subject_template",
                    template.subject_template,
                    back=True,
                )
                == subject
            )
            assert (
                _reword(
                    _PLAN, locale, "body_template", template.body_template, back=True
                )
                == body
            )

    def test_swap_table_touches_only_the_two_codes_in_core_locales(self) -> None:
        assert {(code, locale) for code, locale, *_ in _swaps()} == {
            (_SUBMITTED, "en"),
            (_SUBMITTED, "de"),
            (_PLAN, "en"),
            (_PLAN, "de"),
        }


class TestPlanRequestedSubjectBack:
    """HRP-714 (QA 21.10): ``hrp714plansubject`` puts the seed subject
    back - the bell's title and the letter's subject read "{name} asked
    for a development plan" again - while the body keeps the
    ``hrp379714tplcopy`` wording that names the card."""

    _EXPECTED = {
        "en": (
            "Jane Doe asked for a development plan",
            "Jane Doe requests a development plan for Platform Architect.",
            "View candidate matches",
        ),
        "de": (
            "Jane Doe hat um einen Entwicklungsplan gebeten",
            "Jane Doe bittet um einen Entwicklungsplan für Platform Architect.",
            "Übereinstimmungen des Kandidaten ansehen",
        ),
    }
    _CONTEXT = {"employee_name": "Jane Doe", "card_title": "Platform Architect"}

    @staticmethod
    def _back(locale: str, column: str, text: str, *, undo: bool = False) -> str:
        """Apply ``hrp714plansubject`` to one row/column, as its SQL would."""
        module = _module("hrp714plansubject_plan_requested_subject_back.py")
        swaps = [s for s in module.SWAPS if s[:3] == (_PLAN, locale, column)]
        for _code, _locale, _column, current, new in swaps[::-1] if undo else swaps:
            old, repl = (new, current) if undo else (current, new)
            assert old in text, f"{old!r} is not in the {locale} {column}"
            text = text.replace(old, repl)
        return text

    def _template(self, locale: str) -> NotificationTemplate:
        subject, body = _plan_seed()[locale]
        return NotificationTemplate(
            code=_PLAN,
            locale=locale,
            subject_template=self._back(
                locale,
                "subject_template",
                _reword(_PLAN, locale, "subject_template", subject),
            ),
            body_template=self._back(
                locale, "body_template", _reword(_PLAN, locale, "body_template", body)
            ),
            notification_type="email",
        )

    def test_subject_is_the_seed_one_and_the_body_keeps_the_rewording(self) -> None:
        for locale, (subject, body) in _plan_seed().items():
            template = self._template(locale)
            assert template.subject_template == subject
            assert template.body_template == _reword(
                _PLAN, locale, "body_template", body
            )

    def test_bell_and_letter_read_as_qa_asked(self) -> None:
        for locale, (title, text, link_text) in self._EXPECTED.items():
            template = self._template(locale)
            bell_title, bell_text = render_db_template_preview(
                template, {**self._CONTEXT, "link_url": None}
            )
            assert (bell_title, bell_text) == (title, text)

            subject, letter = render_db_template(
                template, {**self._CONTEXT, "link_url": "https://app.example.com/c"}
            )
            assert subject == title
            assert f'<a href="https://app.example.com/c">{link_text}</a>' in letter
            assert "Platform Architect</b>" in letter

    def test_downgrade_restores_the_hrp379714tplcopy_subject(self) -> None:
        for locale, (subject, _body) in _plan_seed().items():
            reworded = _reword(_PLAN, locale, "subject_template", subject)
            assert (
                self._back(
                    locale,
                    "subject_template",
                    self._template(locale).subject_template,
                    undo=True,
                )
                == reworded
            )

    def test_swap_table_touches_only_the_plan_subject_in_core_locales(self) -> None:
        module = _module("hrp714plansubject_plan_requested_subject_back.py")
        assert {s[:3] for s in module.SWAPS} == {
            (_PLAN, "en", "subject_template"),
            (_PLAN, "de", "subject_template"),
        }
