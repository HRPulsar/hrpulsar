"""PDF generation for recruitment artefacts (questions export, FR-13/SCR-65)."""

from __future__ import annotations

import io
import uuid

from fastapi import status
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.modules.company.models import Tenant
from app.modules.recruitment.common import candidate_display_name
from app.modules.recruitment.models import (
    Candidate,
    CandidateQuestion,
    Vacancy,
    VacancyProfile,
)

_PRIORITY_LABELS = {
    "must": "Must",
    "should": "Should",
    "nice_to_ask": "Nice to ask",
}


_PURPOSE_LABELS = {
    "clarification": "Clarification",
    "depth": "Depth",
    "risk": "Risk",
    "motivation": "Motivation",
    "fit": "Fit",
}


async def export_questions_pdf(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    *,
    include_good: bool = True,
    include_acceptable: bool = True,
    include_poor: bool = True,
) -> bytes:
    """Render the candidate's question bank for a vacancy as a PDF document.

    Groups questions by competency. Includes vacancy + candidate header and
    optional reference answers (good / acceptable / poor).
    """
    vacancy_result = await db.execute(
        select(Vacancy).where(
            Vacancy.id == vacancy_id, Vacancy.tenant_id == tenant_id
        )
    )
    vacancy = vacancy_result.scalar_one_or_none()
    if not vacancy:
        raise AppError("vacancy_not_found", status.HTTP_404_NOT_FOUND)

    candidate_result = await db.execute(
        select(Candidate)
        .options(selectinload(Candidate.person))
        .where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    candidate = candidate_result.scalar_one_or_none()
    if not candidate:
        raise AppError("candidate_not_found", status.HTTP_404_NOT_FOUND)

    questions_result = await db.execute(
        select(CandidateQuestion)
        .where(
            CandidateQuestion.tenant_id == tenant_id,
            CandidateQuestion.candidate_id == candidate_id,
            CandidateQuestion.vacancy_id == vacancy_id,
        )
        .order_by(CandidateQuestion.sort_order)
    )
    questions = list(questions_result.scalars().all())

    profile_result = await db.execute(
        select(VacancyProfile).where(
            VacancyProfile.tenant_id == tenant_id,
            VacancyProfile.vacancy_id == vacancy_id,
        )
    )
    profile = profile_result.scalar_one_or_none()
    competence_lookup: dict[str, str] = {}
    if profile and profile.profile_data:
        for item in profile.profile_data.get("competences", []) or []:
            cid = item.get("id")
            name = item.get("name")
            if cid and name:
                competence_lookup[str(cid)] = name

    tenant = await db.get(Tenant, tenant_id)
    tenant_name = tenant.name if tenant else ""

    # HRP-384: prefer the canonical ``Candidate.full_name``. Reading the
    # linked ``Person`` alone printed "(unnamed)" for resume-sourced
    # candidates, which have no ``Person`` row (``person_id`` NULL since
    # HRP-181 REDO). The rest of this PDF is English by design, so the
    # fallback stays a literal.
    candidate_name = candidate_display_name(candidate, fallback="(unnamed)")

    return _render_pdf(
        tenant_name=tenant_name,
        vacancy=vacancy,
        candidate_name=candidate_name,
        questions=questions,
        competence_lookup=competence_lookup,
        include_good=include_good,
        include_acceptable=include_acceptable,
        include_poor=include_poor,
    )


def _render_pdf(
    *,
    tenant_name: str,
    vacancy: Vacancy,
    candidate_name: str,
    questions: list[CandidateQuestion],
    competence_lookup: dict[str, str],
    include_good: bool,
    include_acceptable: bool,
    include_poor: bool,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Interview questions — {candidate_name}",
    )

    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body", parent=styles["BodyText"], fontSize=10, leading=13
    )
    h1 = ParagraphStyle(
        "H1", parent=styles["Heading1"], fontSize=16, leading=20, spaceAfter=8
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=12,
        leading=15,
        spaceBefore=12,
        spaceAfter=6,
    )
    meta = ParagraphStyle(
        "Meta",
        parent=styles["BodyText"],
        fontSize=9,
        textColor=colors.grey,
    )
    answer_label = ParagraphStyle(
        "AnsLabel",
        parent=styles["BodyText"],
        fontSize=9,
        textColor=colors.grey,
        spaceBefore=4,
    )

    story: list = []

    if tenant_name:
        story.append(Paragraph(_escape(tenant_name), meta))
    story.append(Paragraph("Interview questions", h1))
    story.append(
        Paragraph(
            f"<b>Vacancy:</b> {_escape(vacancy.title)}",
            body,
        )
    )
    story.append(
        Paragraph(f"<b>Candidate:</b> {_escape(candidate_name)}", body)
    )
    story.append(Spacer(1, 0.4 * cm))

    if not questions:
        story.append(
            Paragraph(
                "No questions have been generated for this candidate yet.", body
            )
        )
        doc.build(story)
        return buf.getvalue()

    grouped: dict[str, list[CandidateQuestion]] = {}
    for q in questions:
        key = (
            competence_lookup.get(str(q.competence_id))
            if q.competence_id
            else None
        ) or "General"
        grouped.setdefault(key, []).append(q)

    for competence, qs in grouped.items():
        story.append(Paragraph(_escape(competence), h2))

        for idx, q in enumerate(qs, 1):
            priority = _PRIORITY_LABELS.get(q.priority, q.priority)
            purpose = _PURPOSE_LABELS.get(q.purpose, q.purpose)
            header = (
                f"<b>{idx}.</b> {_escape(q.question_text)} "
                f"<font size=8 color='grey'>· {priority} · {purpose}</font>"
            )
            story.append(Paragraph(header, body))
            if q.purpose and q.purpose != "clarification":
                story.append(Paragraph(f"<i>Purpose:</i> {purpose}", answer_label))
            if q.resume_fragment:
                story.append(
                    Paragraph(
                        f"<i>From resume:</i> {_escape(q.resume_fragment)}",
                        answer_label,
                    )
                )
            rows: list[tuple[str, str]] = []
            if include_good and q.good_answer:
                rows.append(("Good answer", q.good_answer))
            if include_acceptable and q.acceptable_answer:
                rows.append(("Acceptable", q.acceptable_answer))
            if include_poor and q.poor_answer:
                rows.append(("Poor", q.poor_answer))
            if rows:
                table_data = [
                    [Paragraph(_escape(label), answer_label), Paragraph(_escape(text), body)]
                    for label, text in rows
                ]
                table = Table(table_data, colWidths=[3 * cm, None])
                table.setStyle(
                    TableStyle(
                        [
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 2),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                            ("TOPPADDING", (0, 0), (-1, -1), 1),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                            ("LINEBEFORE", (0, 0), (0, -1), 0.5, colors.lightgrey),
                        ]
                    )
                )
                story.append(Spacer(1, 0.15 * cm))
                story.append(table)
            story.append(Spacer(1, 0.3 * cm))

    doc.build(story)
    return buf.getvalue()


def _escape(text: str | None) -> str:
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
