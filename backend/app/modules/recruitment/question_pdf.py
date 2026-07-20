"""HRP-205: PDF rendering for individual question sets.

Three layouts (Compact / Full / Cards) — see FR-13 / SCR-65. Shares the
underlying reportlab plumbing pattern with the legacy
``pdf_export.export_questions_pdf`` but has no dependency on the
``candidate_questions`` table.
"""

from __future__ import annotations

import io
from typing import Any

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

_PRIORITY = {
    "must": "Must",
    "should": "Should",
    "nice_to_ask": "Nice to ask",
}

_GOAL = {
    "clarification": "Clarification",
    "depth": "Depth",
    "risk": "Risk",
    "motivation": "Motivation",
    "fit": "Fit",
}

_SOURCE = {
    "ai_generated": "AI",
    "manual": "Manual",
    "from_competency_indicator": "Indicator",
    "from_blind_spot": "Blind spot",
}


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
    return {"title": title, "h2": h2, "body": body, "small": small}


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
    flow: list = [Paragraph(set_name, styles["title"]), Spacer(1, 0.2 * cm)]

    if fmt == "compact":
        flow.extend(_compact(questions, styles))
    elif fmt == "cards":
        flow.extend(
            _cards(
                questions,
                styles,
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


def _compact(questions: list[dict[str, Any]], styles: dict) -> list:
    rows = [["#", "Question", "Tags"]]
    for idx, q in enumerate(questions, start=1):
        rows.append([str(idx), q.get("text") or "", _badges(q)])
    table = Table(rows, colWidths=[1 * cm, 13 * cm, 4 * cm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return [table]


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
        Paragraph(
            f"{idx}. {q.get('text') or ''}",
            styles["h2"],
        ),
        Paragraph(_badges(q), styles["small"]),
    ]
    anchor = q.get("resume_anchor_jsonb")
    if include_resume_anchor and isinstance(anchor, dict) and anchor.get("quote"):
        out.append(
            Paragraph(
                f"Resume: “{anchor.get('quote')}”",
                styles["small"],
            )
        )
    indicators = q.get("expected_answer_indicators") or []
    if include_indicators and indicators:
        out.append(Paragraph("Expected indicators:", styles["body"]))
        for i in indicators:
            out.append(Paragraph(f"• {i}", styles["body"]))
    follow_ups = q.get("follow_ups") or []
    if include_follow_ups and follow_ups:
        out.append(Paragraph("Follow-ups:", styles["body"]))
        for f in follow_ups:
            out.append(Paragraph(f"• {f}", styles["body"]))
    if include_rationale and q.get("rationale"):
        out.append(Paragraph(f"Rationale: {q['rationale']}", styles["body"]))
    out.append(Spacer(1, 0.3 * cm))
    return out


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
    include_indicators: bool,
    include_follow_ups: bool,
    include_rationale: bool,
    include_resume_anchor: bool,
) -> list:
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
        # Wrap each card in a one-cell table for the bordered look.
        table = Table(
            [[card_flow]],
            colWidths=[16 * cm],
        )
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        flow.append(KeepTogether(table))
        flow.append(Spacer(1, 0.4 * cm))
    return flow
