"""HRP-205: PDF rendering for individual question sets.

Three layouts (Compact / Full / Cards) — see FR-13 / SCR-65. Shares the
underlying reportlab plumbing pattern with the legacy
``pdf_export.export_questions_pdf`` but has no dependency on the
``candidate_questions`` table.
"""

from __future__ import annotations

import io
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# HRP-486: the PDF is an English-only artefact, so it carries its own
# display names rather than going through the UI catalogs. Codes must
# stay in step with ``schemas.QuestionGoal`` / ``QuestionPriority`` /
# ``QuestionSource`` — ``test_question_enum_alignment`` enforces that.
_PRIORITY = {
    "must_ask": "Must ask",
    "should_ask": "Should ask",
    "nice_to_ask": "Nice to ask",
}

_GOAL = {
    "verify_skill": "Verify skill",
    "clarify_experience": "Clarify experience",
    "probe_risk": "Probe risk",
    "explore_motivation": "Explore motivation",
    "assess_fit": "Assess fit",
}

_SOURCE = {
    "ai_generated": "AI",
    "manual": "Manual",
    "from_competency_indicator": "From competency indicator",
    "from_blind_spot": "From blind spot",
}


# HRP-462: the compact layout must fit on a single sheet. We render the
# table at the largest font size from this ladder that still fits the
# frame, then fall back to the smallest one when even that overflows
# (a 60-question set cannot be shrunk indefinitely without becoming
# unreadable, so we stop at 5.5pt and let it spill).
_COMPACT_FONT_SIZES = (9.0, 8.5, 8.0, 7.5, 7.0, 6.5, 6.0, 5.5)

# HRP-483: every card reserves the same writing area regardless of which
# optional blocks the user ticked. Deliberately a module constant — the
# ticket explicitly forbids exposing this as a system/tenant setting.
_NOTES_LINE_COUNT = 3
_NOTES_LINE_HEIGHT = 0.9 * cm


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "Title",
        parent=base["Title"],
        fontSize=18,
        spaceAfter=12,
    )
    h2 = ParagraphStyle(
        "H2",
        parent=base["Heading2"],
        fontSize=12,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "Body",
        parent=base["BodyText"],
        fontSize=10,
        leading=13,
    )
    small = ParagraphStyle(
        "Small",
        parent=base["BodyText"],
        fontSize=8,
        leading=10,
        textColor=colors.grey,
    )
    # HRP-483: the "Notes" caption above the ruled writing area.
    notes = ParagraphStyle(
        "NotesHeading",
        parent=base["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        spaceBefore=2,
        spaceAfter=2,
        textColor=colors.HexColor("#64748b"),
    )
    return {
        "title": title,
        "h2": h2,
        "body": body,
        "small": small,
        "notes": notes,
    }


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    """Paragraph from untrusted text.

    Question bodies are user/LLM authored and reportlab parses paragraph
    content as mini-HTML — an unescaped ``&`` or ``<`` (think "R&D" or
    "latency < 100ms") raises at build time. Escape before wrapping.
    """
    return Paragraph(escape(str(text or "")), style)


def render_question_set_pdf(
    *,
    set_name: str,
    questions: list[dict[str, Any]],
    fmt: str = "compact",
    include_indicators: bool = True,
    include_follow_ups: bool = True,
    include_rationale: bool = False,
    include_resume_anchor: bool = True,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        title=set_name,
    )
    styles = _styles()
    title = _p(set_name, styles["title"])
    flow: list = [title, Spacer(1, 0.2 * cm)]

    if fmt == "compact":
        # HRP-462: the table has to fit the single remaining page, so the
        # size ladder is measured against what is left after the heading.
        _, title_height = title.wrap(doc.width, doc.height)
        body_height = doc.height - title_height - styles["title"].spaceAfter - 0.2 * cm
        flow.extend(
            _compact(
                questions,
                avail_width=doc.width,
                avail_height=max(body_height, 1.0 * cm),
            )
        )
    elif fmt == "cards":
        flow.extend(
            _cards(
                questions,
                styles,
                avail_width=doc.width,
                include_indicators=include_indicators,
                include_follow_ups=include_follow_ups,
                include_rationale=include_rationale,
                include_resume_anchor=include_resume_anchor,
            )
        )
    else:
        flow.extend(
            _full(
                questions,
                styles,
                include_indicators=include_indicators,
                include_follow_ups=include_follow_ups,
                include_rationale=include_rationale,
                include_resume_anchor=include_resume_anchor,
            )
        )

    doc.build(flow)
    return buf.getvalue()


def _badges(q: dict[str, Any]) -> str:
    priority = str(q.get("priority") or "")
    goal = str(q.get("goal") or "")
    source = str(q.get("source") or "")
    parts = [
        _PRIORITY.get(priority, priority),
        _GOAL.get(goal, goal),
        _SOURCE.get(source, source),
    ]
    return " · ".join(p for p in parts if p)


def _compact_table(
    questions: list[dict[str, Any]],
    col_widths: list[float],
    font_size: float,
) -> Table:
    """One compact table rendered at ``font_size``.

    Cells are ``Paragraph`` flowables rather than bare strings: a plain
    string in a reportlab cell is drawn on a single line and simply
    overflows the column, which is exactly the missing word-wrap the
    ticket reports.
    """
    cell = ParagraphStyle(
        "CompactCell",
        fontName="Helvetica",
        fontSize=font_size,
        leading=font_size * 1.25,
    )
    head = ParagraphStyle("CompactHead", parent=cell, fontName="Helvetica-Bold")
    padding = max(1.5, font_size * 0.35)

    rows: list[list[Any]] = [[_p("#", head), _p("Question", head), _p("Tags", head)]]
    for idx, q in enumerate(questions, start=1):
        rows.append(
            [
                _p(idx, cell),
                _p(q.get("text"), cell),
                _p(_badges(q), cell),
            ]
        )
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
            ]
        )
    )
    return table


def _compact(
    questions: list[dict[str, Any]],
    *,
    avail_width: float,
    avail_height: float,
) -> list:
    """Compact layout — every question on one portrait page (HRP-462).

    Column widths are derived from the frame rather than hard-coded, so
    the table can never be wider than the printable area. The font size
    steps down until the whole table fits the page; if even the smallest
    size overflows we keep it and let the document paginate rather than
    render something illegible.
    """
    col_widths = [
        avail_width * 0.06,
        avail_width * 0.72,
        avail_width * 0.22,
    ]
    chosen = _COMPACT_FONT_SIZES[-1]
    for size in _COMPACT_FONT_SIZES:
        _, needed = _compact_table(questions, col_widths, size).wrap(
            avail_width, avail_height
        )
        if needed <= avail_height:
            chosen = size
            break
    # Rebuild at the chosen size: ``wrap`` leaves layout state on the
    # instance it measured, so the one handed to the doc is always fresh.
    return [_compact_table(questions, col_widths, chosen)]


def _question_block(
    q: dict[str, Any],
    idx: int,
    styles: dict,
    *,
    include_indicators: bool,
    include_follow_ups: bool,
    include_rationale: bool,
    include_resume_anchor: bool,
) -> list:
    out: list = [
        _p(f"{idx}. {q.get('text') or ''}", styles["h2"]),
        _p(_badges(q), styles["small"]),
    ]
    anchor = q.get("resume_anchor_jsonb")
    if include_resume_anchor and isinstance(anchor, dict) and anchor.get("quote"):
        out.append(_p(f"Resume: “{anchor.get('quote')}”", styles["small"]))
    indicators = q.get("expected_answer_indicators") or []
    if include_indicators and indicators:
        out.append(_p("Expected indicators:", styles["body"]))
        for i in indicators:
            out.append(_p(f"• {i}", styles["body"]))
    follow_ups = q.get("follow_ups") or []
    if include_follow_ups and follow_ups:
        out.append(_p("Follow-ups:", styles["body"]))
        for f in follow_ups:
            out.append(_p(f"• {f}", styles["body"]))
    if include_rationale and q.get("rationale"):
        out.append(_p(f"Rationale: {q['rationale']}", styles["body"]))
    out.append(Spacer(1, 0.3 * cm))
    return out


def _notes_area(styles: dict, width: float) -> list:
    """Ruled writing area appended to every card (HRP-483).

    Always the same height, whatever the include_* flags produced above
    it, so a printed stack of cards has a predictable place to write.
    """
    lines = Table(
        [[""] for _ in range(_NOTES_LINE_COUNT)],
        colWidths=[width],
        rowHeights=[_NOTES_LINE_HEIGHT] * _NOTES_LINE_COUNT,
    )
    lines.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [_p("Notes", styles["notes"]), lines]


def _full(
    questions: list[dict[str, Any]],
    styles: dict,
    *,
    include_indicators: bool,
    include_follow_ups: bool,
    include_rationale: bool,
    include_resume_anchor: bool,
) -> list:
    flow: list = []
    for idx, q in enumerate(questions, start=1):
        flow.extend(
            _question_block(
                q,
                idx,
                styles,
                include_indicators=include_indicators,
                include_follow_ups=include_follow_ups,
                include_rationale=include_rationale,
                include_resume_anchor=include_resume_anchor,
            )
        )
    return flow


def _cards(
    questions: list[dict[str, Any]],
    styles: dict,
    *,
    avail_width: float,
    include_indicators: bool,
    include_follow_ups: bool,
    include_rationale: bool,
    include_resume_anchor: bool,
) -> list:
    _CARD_PADDING = 8
    inner_width = avail_width - 2 * _CARD_PADDING
    flow: list = []
    for idx, q in enumerate(questions, start=1):
        card_flow = _question_block(
            q,
            idx,
            styles,
            include_indicators=include_indicators,
            include_follow_ups=include_follow_ups,
            include_rationale=include_rationale,
            include_resume_anchor=include_resume_anchor,
        )
        # HRP-483: unconditional — the Notes block does not depend on any
        # include_* flag, so an all-unchecked export still leaves room to
        # write.
        card_flow.extend(_notes_area(styles, inner_width))
        # Wrap each card in a one-cell table for the bordered look.
        table = Table(
            [[card_flow]],
            colWidths=[avail_width],
        )
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("LEFTPADDING", (0, 0), (-1, -1), _CARD_PADDING),
                    ("RIGHTPADDING", (0, 0), (-1, -1), _CARD_PADDING),
                    ("TOPPADDING", (0, 0), (-1, -1), _CARD_PADDING),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), _CARD_PADDING),
                ]
            )
        )
        flow.append(KeepTogether(table))
        flow.append(Spacer(1, 0.4 * cm))
    return flow
