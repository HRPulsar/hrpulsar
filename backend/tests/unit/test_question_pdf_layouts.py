"""Question-set PDF layout regressions (HRP-462, HRP-483).

The renderer is pure — no DB, no tenant — so these exercise the layout
helpers directly plus one end-to-end ``render_question_set_pdf`` smoke
per format.
"""

from __future__ import annotations

from app.modules.recruitment.question_pdf import (
    _NOTES_LINE_COUNT,
    _cards,
    _compact,
    _styles,
    render_question_set_pdf,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Table

# A4 portrait minus the 1.6cm margins the document template uses.
AVAIL_W = A4[0] - 3.2 * cm
AVAIL_H = A4[1] - 3.2 * cm

LONG_TEXT = (
    "You wrote that you led the payment-platform migration in 2022 across "
    "four teams and two regions. Walk me through the riskiest call you made "
    "during that project and what the trade-offs were at the time."
)


def _question(idx: int, **over) -> dict:
    q = {
        "text": f"{LONG_TEXT} ({idx})",
        "goal": "verify_skill",
        "priority": "must_ask",
        "source": "ai_generated",
        "resume_anchor_jsonb": {"quote": "Led the migration", "section": "experience"},
        "expected_answer_indicators": ["Names a concrete decision"],
        "follow_ups": ["What would you change?"],
        "rationale": "Verifies claimed ownership.",
    }
    q.update(over)
    return q


def _cell_font_size(table: Table) -> float:
    # First body row, "Question" column.
    return table._cellvalues[1][1].style.fontSize


class TestCompactWordWrap:
    """HRP-462: cells must wrap; the table must fit one portrait page."""

    def test_cells_are_paragraphs_not_bare_strings(self):
        # A bare string in a reportlab cell is laid out on a single line
        # and overflows the column — that was the reported bug.
        table = _compact(
            [_question(i) for i in range(5)],
            avail_width=AVAIL_W,
            avail_height=AVAIL_H,
        )[0]
        for row in table._cellvalues:
            for cell in row:
                assert isinstance(cell, Paragraph)

    def test_table_never_exceeds_printable_width(self):
        table = _compact(
            [_question(i) for i in range(5)],
            avail_width=AVAIL_W,
            avail_height=AVAIL_H,
        )[0]
        assert sum(table._argW) <= AVAIL_W + 0.01

    def test_small_set_fits_on_one_page(self):
        table = _compact(
            [_question(i) for i in range(8)],
            avail_width=AVAIL_W,
            avail_height=AVAIL_H,
        )[0]
        _, height = table.wrap(AVAIL_W, AVAIL_H)
        assert height <= AVAIL_H

    def test_font_shrinks_when_the_set_grows(self):
        small = _compact(
            [_question(i) for i in range(6)],
            avail_width=AVAIL_W,
            avail_height=AVAIL_H,
        )[0]
        large = _compact(
            [_question(i) for i in range(45)],
            avail_width=AVAIL_W,
            avail_height=AVAIL_H,
        )[0]
        assert _cell_font_size(large) < _cell_font_size(small)

    def test_large_set_still_shrinks_to_fit_one_page(self):
        table = _compact(
            [_question(i) for i in range(30)],
            avail_width=AVAIL_W,
            avail_height=AVAIL_H,
        )[0]
        _, height = table.wrap(AVAIL_W, AVAIL_H)
        assert height <= AVAIL_H


class TestCardsNotesArea:
    """HRP-483: every card reserves a Notes block, whatever is ticked."""

    ALL_OFF = {
        "include_indicators": False,
        "include_follow_ups": False,
        "include_rationale": False,
        "include_resume_anchor": False,
    }
    ALL_ON = {
        "include_indicators": True,
        "include_follow_ups": True,
        "include_rationale": True,
        "include_resume_anchor": True,
    }

    def _card_cell(self, flags: dict) -> list:
        flow = _cards([_question(0)], _styles(), avail_width=AVAIL_W, **flags)
        # flow == [KeepTogether(table), Spacer]; unwrap to the card cell.
        return flow[0]._content[0]._cellvalues[0][0]

    def test_notes_present_with_every_checkbox_off(self):
        cell = self._card_cell(self.ALL_OFF)
        assert any(
            isinstance(f, Paragraph) and "Notes" in f.getPlainText() for f in cell
        )

    def test_notes_present_with_every_checkbox_on(self):
        cell = self._card_cell(self.ALL_ON)
        assert any(
            isinstance(f, Paragraph) and "Notes" in f.getPlainText() for f in cell
        )

    def test_notes_area_height_is_identical_across_flag_combos(self):
        def notes_height(flags: dict) -> float:
            cell = self._card_cell(flags)
            ruled = [f for f in cell if isinstance(f, Table)][-1]
            return sum(ruled._argH)

        assert notes_height(self.ALL_OFF) == notes_height(self.ALL_ON)

    def test_notes_area_has_ruled_lines(self):
        cell = self._card_cell(self.ALL_OFF)
        ruled = [f for f in cell if isinstance(f, Table)][-1]
        assert len(ruled._cellvalues) == _NOTES_LINE_COUNT


class TestRenderSmoke:
    def test_every_format_produces_a_pdf(self):
        questions = [_question(i) for i in range(9)]
        for fmt in ("compact", "full", "cards"):
            out = render_question_set_pdf(
                set_name="Pre-interview set",
                questions=questions,
                fmt=fmt,
            )
            assert out.startswith(b"%PDF"), fmt

    def test_markup_characters_do_not_break_the_build(self):
        # reportlab parses paragraph text as mini-HTML — unescaped user
        # text like "R&D" or "latency < 100ms" used to raise on build.
        questions = [
            _question(
                0,
                text="How did R&D handle latency < 100ms & >99.9% uptime?",
                rationale="Tests <b>escaping</b> & ampersands",
                follow_ups=["What about p99 < 50ms?"],
                expected_answer_indicators=["Mentions A&B testing"],
            )
        ]
        for fmt in ("compact", "full", "cards"):
            out = render_question_set_pdf(
                set_name="Set & <name>",
                questions=questions,
                fmt=fmt,
                include_rationale=True,
            )
            assert out.startswith(b"%PDF"), fmt
