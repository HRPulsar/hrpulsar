"""4-sheet consolidated XLSX renderer (HRP-268, FR-23 / FR-24).

The workbook always carries exactly four kinds of sheet, in this order:

1. **Summary** — one row per candidate with profile snippet, manager %,
   AI %, AI data completeness and a computed recommendation.
2. **Matrix** — competences × candidates with side-by-side Manager / AI
   columns, group separators, amber divergence highlight and a SUM-based
   "Total" row.
3. **Detail · {candidate}** — one sheet per candidate carrying resume
   summary, per-competence scoring with citations, blind spots, red
   flags, process findings (reframed for the hiring-manager audience),
   and verdict.
4. **Incomplete data** — candidates whose AI / manager scoring is not
   ready yet, with a "what to do" hint. Always emitted, even empty.

The renderer is intentionally stateless: callers assemble the payload
in the Celery task so the module is exercisable in unit tests without
DB / S3 access.
"""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

# ---------------------------------------------------------------------------
# Style palette — kept tight so a future visual refresh changes one place.
# ---------------------------------------------------------------------------

_HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFFFF")
_HEADER_FILL = PatternFill(start_color="1A1F36", end_color="1A1F36", fill_type="solid")
_GROUP_FILL = PatternFill(start_color="F1F3F8", end_color="F1F3F8", fill_type="solid")
_TOTAL_FILL = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
_AMBER_FILL = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
_EMERALD_FILL = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
_ROSE_FILL = PatternFill(start_color="FECACA", end_color="FECACA", fill_type="solid")

_HEADER_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=True)
_BODY_ALIGN = Alignment(horizontal="left", vertical="top", wrap_text=True)
_CENTER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
_BOLD = Font(name="Calibri", size=11, bold=True)
_THIN_BORDER = Border(
    left=Side(style="thin", color="E2E8F0"),
    right=Side(style="thin", color="E2E8F0"),
    top=Side(style="thin", color="E2E8F0"),
    bottom=Side(style="thin", color="E2E8F0"),
)


def _safe_sheet_title(title: str, *, reserve: int = 0) -> str:
    """Excel sheet titles cap at 31 chars and forbid ``: \\ / ? * [ ]``.

    ``reserve`` keeps the last N characters free so :func:`render_report_xlsx`
    can suffix a dedup counter (`#2`, `#3`) on collision without ever
    exceeding the 31-char limit.
    """
    cleaned = "".join(ch for ch in title if ch not in ":\\/?*[]")
    limit = max(1, 31 - reserve)
    return cleaned[:limit] or "Sheet"


def _coerce(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _set_header_cell(ws: Worksheet, row: int, col: int, value: Any) -> None:
    cell = ws.cell(row=row, column=col, value=_coerce(value))
    cell.font = _HEADER_FONT
    cell.fill = _HEADER_FILL
    cell.alignment = _HEADER_ALIGN
    cell.border = _THIN_BORDER


def _set_body_cell(
    ws: Worksheet,
    row: int,
    col: int,
    value: Any,
    *,
    align: Alignment | None = None,
    fill: PatternFill | None = None,
    bold: bool = False,
) -> None:
    cell = ws.cell(row=row, column=col, value=_coerce(value))
    cell.alignment = align or _BODY_ALIGN
    if fill is not None:
        cell.fill = fill
    if bold:
        cell.font = _BOLD
    cell.border = _THIN_BORDER


def _embed_logo(ws: Worksheet, branding: dict | None, anchor: str = "A1") -> None:
    if not branding or not isinstance(branding.get("logo_png"), bytes):
        return
    try:
        from openpyxl.drawing.image import Image as XLImage

        buf = io.BytesIO(branding["logo_png"])
        img = XLImage(buf)
        img.width = 96
        img.height = 96
        ws.add_image(img, anchor)
    except Exception:  # pragma: no cover  # noqa: BLE001 - never blocks export
        return


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_report_xlsx(
    *,
    vacancy: dict,
    branding: dict | None = None,
    summary_rows: list[dict] | None = None,
    matrix: dict | None = None,
    details: list[dict] | None = None,
    incomplete: list[dict] | None = None,
    audience: str | None = None,
) -> bytes:
    """Build the 4-sheet consolidated workbook and return raw XLSX bytes.

    ``vacancy`` carries ``title``, ``specialization_title``,
    ``division_name`` etc. for the headers across sheets. ``audience``
    is ``recruiter`` (default) or ``hiring_manager`` — the latter
    replaces the raw process-findings text on each Detail sheet with
    the ``positive_reframe`` field, falling back to "Recommendation for
    the next interview" when missing.
    """

    wb = Workbook()
    default_ws: Worksheet | None = wb.active
    used_titles: set[str] = set()

    def _take_sheet(title: str, *, reserve: int = 0) -> Worksheet:
        nonlocal default_ws
        # Dedup on collision (two candidates sharing the first ~22 chars
        # of name) by appending ` #N` *inside* the 31-char budget. The
        # reserve keeps room for the suffix so we never produce a
        # >31-char title that openpyxl warns about + Excel may reject.
        base = _safe_sheet_title(title, reserve=reserve)
        final = base
        counter = 2
        while final in used_titles:
            suffix = f" #{counter}"
            final = _safe_sheet_title(title, reserve=len(suffix)) + suffix
            counter += 1
        used_titles.add(final)
        if default_ws is not None:
            ws = default_ws
            ws.title = final
            default_ws = None
            return ws
        return wb.create_sheet(title=final)

    _render_summary(
        _take_sheet("Summary"), vacancy, summary_rows or [], branding=branding
    )
    _render_matrix(_take_sheet("Matrix"), matrix or {}, branding=branding)
    for detail in details or []:
        title = "Detail · " + (detail.get("candidate_name") or "Candidate")
        # Reserve 4 chars (` #99`) so the dedup counter cannot push the
        # final title past the 31-char limit even for the longest names.
        _render_detail(
            _take_sheet(title, reserve=4),
            detail,
            audience=audience or "recruiter",
            branding=branding,
        )
    _render_incomplete(
        _take_sheet("Incomplete data"), incomplete or [], branding=branding
    )

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Sheet 1 — Summary ranking
# ---------------------------------------------------------------------------


def _render_summary(
    ws: Worksheet, vacancy: dict, rows: list[dict], *, branding: dict | None
) -> None:
    _embed_logo(ws, branding, "G1")
    tenant_name = (branding or {}).get("tenant_name") or ""
    title_line = (
        f"Candidate ranking — {vacancy.get('title') or 'Vacancy'}"
        f"{' | ' + tenant_name if tenant_name else ''}"
    )
    ws.cell(row=1, column=1, value=title_line).font = Font(size=14, bold=True)
    subtitle = " | ".join(
        filter(
            None,
            [
                vacancy.get("specialization_title"),
                vacancy.get("division_name"),
                vacancy.get("employment_type"),
                vacancy.get("location"),
            ],
        )
    )
    if subtitle:
        ws.cell(row=2, column=1, value=subtitle).font = Font(
            size=10, color="6B7280"
        )

    headers = [
        "Candidate",
        "Profile",
        "Manager score",
        "AI score",
        "Data readiness",
        "Recommendation",
    ]
    header_row = 4
    for col, value in enumerate(headers, start=1):
        _set_header_cell(ws, header_row, col, value)
    ws.row_dimensions[header_row].height = 22

    for idx, row in enumerate(rows, start=header_row + 1):
        recommendation = row.get("recommendation") or "review"
        rec_fill = _recommendation_fill(recommendation)
        _set_body_cell(ws, idx, 1, row.get("candidate_name"))
        _set_body_cell(ws, idx, 2, row.get("profile_summary"))
        _set_body_cell(ws, idx, 3, row.get("manager_score_text"))
        _set_body_cell(ws, idx, 4, row.get("ai_score_text"))
        _set_body_cell(ws, idx, 5, row.get("data_readiness"))
        _set_body_cell(ws, idx, 6, recommendation, fill=rec_fill, bold=True)

    notes = [r for r in rows if r.get("note")]
    if notes:
        ws.cell(
            row=header_row + len(rows) + 2,
            column=1,
            value="Notes",
        ).font = _BOLD
        for offset, row in enumerate(notes, start=header_row + len(rows) + 3):
            _set_body_cell(
                ws,
                offset,
                1,
                f"* {row.get('candidate_name')}: {row.get('note')}",
            )

    _autosize(ws, headers, default=24)
    ws.column_dimensions["B"].width = 44
    ws.column_dimensions["F"].width = 28


def _recommendation_fill(value: str) -> PatternFill | None:
    lowered = (value or "").lower()
    if "not" in lowered or "reject" in lowered:
        return _ROSE_FILL
    if "review" in lowered or "additional" in lowered or "check" in lowered:
        return _AMBER_FILL
    if "recommend" in lowered or "hire" in lowered:
        return _EMERALD_FILL
    return None


# ---------------------------------------------------------------------------
# Sheet 2 — Competence matrix
# ---------------------------------------------------------------------------


def _render_matrix(
    ws: Worksheet, matrix: dict, *, branding: dict | None
) -> None:
    _embed_logo(ws, branding, "G1")
    competences: list[dict] = matrix.get("competences") or []
    candidates: list[dict] = matrix.get("candidates") or []
    max_score: float = float(matrix.get("max_score") or 5.0)

    title = matrix.get("title") or "Competence matrix"
    ws.cell(row=1, column=1, value=title).font = Font(size=14, bold=True)
    if matrix.get("disclaimer"):
        ws.cell(row=2, column=1, value=matrix["disclaimer"]).font = Font(
            size=10, color="6B7280"
        )

    header_row = 4
    _set_header_cell(ws, header_row, 1, "Group")
    _set_header_cell(ws, header_row, 2, "Competence")
    _set_header_cell(ws, header_row, 3, "Critical?")
    # Manager columns first, then AI columns — recruiters scan left-to-right.
    col = 4
    manager_first_col = col
    for cand in candidates:
        _set_header_cell(ws, header_row, col, f"M · {cand.get('name')}")
        col += 1
    ai_first_col = col
    for cand in candidates:
        _set_header_cell(ws, header_row, col, f"AI · {cand.get('name')}")
        col += 1
    ai_last_col = col - 1
    ws.row_dimensions[header_row].height = 22

    # Body — group rows + competence rows. The Group column uses fill to
    # visually delimit groups without merged cells (merging would break the
    # SUM formula in the Total row downstream).
    body_start = header_row + 1
    row_idx = body_start
    last_group: str | None = None
    for comp in competences:
        group = comp.get("group") or "—"
        if group != last_group:
            _set_body_cell(ws, row_idx, 1, group, fill=_GROUP_FILL, bold=True)
            last_group = group
        else:
            _set_body_cell(ws, row_idx, 1, "")
        _set_body_cell(ws, row_idx, 2, comp.get("name"))
        critical = (comp.get("criticality") or "").lower()
        crit_label = "Yes" if critical == "critical" else "—"
        _set_body_cell(ws, row_idx, 3, crit_label, align=_CENTER_ALIGN)

        cells: list[dict] = comp.get("cells") or []
        cell_by_cand = {str(c.get("candidate_id")): c for c in cells}
        # Manager values
        for offset, cand in enumerate(candidates):
            entry = cell_by_cand.get(str(cand.get("id"))) or {}
            ms = entry.get("manager_score")
            tone = _AMBER_FILL if entry.get("divergence") else None
            _set_body_cell(
                ws,
                row_idx,
                manager_first_col + offset,
                "" if ms is None else round(float(ms), 1),
                align=_CENTER_ALIGN,
                fill=tone,
            )
        # AI values
        for offset, cand in enumerate(candidates):
            entry = cell_by_cand.get(str(cand.get("id"))) or {}
            ai_score = entry.get("ai_score")
            ai_status = (entry.get("ai_status") or "").lower()
            tone = _AMBER_FILL if entry.get("divergence") else None
            if ai_status == "not_covered":
                text: Any = "n/a"
            elif ai_score is None:
                text = ""
            else:
                text = round(float(ai_score), 1)
            _set_body_cell(
                ws,
                row_idx,
                ai_first_col + offset,
                text,
                align=_CENTER_ALIGN,
                fill=tone,
            )
        row_idx += 1

    # Total row — one SUM per candidate column (Manager + AI side).
    total_row = row_idx
    _set_body_cell(ws, total_row, 1, "Total", fill=_TOTAL_FILL, bold=True)
    _set_body_cell(
        ws,
        total_row,
        2,
        f"out of {round(max_score * len(competences), 1)}",
        fill=_TOTAL_FILL,
        bold=True,
    )
    _set_body_cell(ws, total_row, 3, "", fill=_TOTAL_FILL)
    if competences:
        body_first = body_start
        body_last = total_row - 1
        for col_idx in range(manager_first_col, ai_last_col + 1):
            col_letter = get_column_letter(col_idx)
            formula = f"=SUM({col_letter}{body_first}:{col_letter}{body_last})"
            cell = ws.cell(row=total_row, column=col_idx, value=formula)
            cell.alignment = _CENTER_ALIGN
            cell.fill = _TOTAL_FILL
            cell.font = _BOLD
            cell.border = _THIN_BORDER

    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 36
    ws.column_dimensions["C"].width = 12
    for col_idx in range(manager_first_col, ai_last_col + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 14


# ---------------------------------------------------------------------------
# Sheet 3 — Detail per candidate
# ---------------------------------------------------------------------------


def _render_detail(
    ws: Worksheet,
    detail: dict,
    *,
    audience: str,
    branding: dict | None,
) -> None:
    _embed_logo(ws, branding, "G1")
    name = detail.get("candidate_name") or "Candidate"
    ws.cell(row=1, column=1, value=f"Detail — {name}").font = Font(
        size=14, bold=True
    )
    subtitle_parts = [
        detail.get("position"),
        detail.get("status"),
    ]
    subtitle = " | ".join([s for s in subtitle_parts if s])
    if subtitle:
        ws.cell(row=2, column=1, value=subtitle).font = Font(
            size=10, color="6B7280"
        )

    row = 4
    row = _detail_section(ws, row, "Resume", [detail.get("resume_summary") or "—"])

    hide_findings_for_hm = audience.lower() == "hiring_manager"
    scores = detail.get("scores") or []
    if scores:
        # HM audience: drop AI free-text reasoning + citations from the
        # Scores table — both regularly carry the same kind of
        # candidate-side process narrative as ``process_findings`` does,
        # and shipping them unfiltered would defeat the HM audience swap.
        if hide_findings_for_hm:
            headers = ["Competence", "Manager", "AI"]
            score_rows = [
                [
                    s.get("competence_name"),
                    _format_score(s.get("manager_score")),
                    _format_score(s.get("ai_score")),
                ]
                for s in scores
            ]
        else:
            headers = ["Competence", "Manager", "AI", "Citations", "Reasoning"]
            score_rows = [
                [
                    s.get("competence_name"),
                    _format_score(s.get("manager_score")),
                    _format_score(s.get("ai_score")),
                    "\n".join(s.get("citations") or []),
                    s.get("reasoning") or "",
                ]
                for s in scores
            ]
        row = _detail_table(ws, row, "Scores", headers, score_rows)

    blind_spots = detail.get("blind_spots") or []
    if blind_spots:
        row = _detail_table(
            ws,
            row,
            "Blind spots",
            ["Competence", "Suggested question"],
            [
                [b.get("competence"), b.get("suggested_question")]
                for b in blind_spots
            ],
        )

    findings = detail.get("process_findings") or []
    if findings:
        if hide_findings_for_hm:
            # HM audience: replace raw process-findings text with the
            # positive reframe so the candidate-side issues never reach
            # the manager unfiltered.
            rows = [
                [
                    f.get("finding_type") or "",
                    f.get("positive_reframe")
                    or "Recommendation for the next interview.",
                ]
                for f in findings
            ]
            row = _detail_table(
                ws,
                row,
                "Recommendations for the next interview",
                ["Topic", "Suggestion"],
                rows,
            )
        else:
            row = _detail_table(
                ws,
                row,
                "Process findings",
                ["Type", "Severity", "Description"],
                [
                    [
                        f.get("finding_type") or "",
                        f.get("severity") or "",
                        f.get("description") or "",
                    ]
                    for f in findings
                ],
            )

    # Red flags are candidate-side concerns by definition — HM audience
    # never sees them; the verdict-level risk fields are also redacted
    # below for the same reason.
    red_flags = detail.get("red_flags") or []
    if red_flags and not hide_findings_for_hm:
        row = _detail_table(
            ws,
            row,
            "Red flags",
            ["Type", "Severity", "Description"],
            [
                [
                    f.get("flag_type") or "",
                    f.get("severity") or "",
                    f.get("description") or "",
                ]
                for f in red_flags
            ],
        )

    verdict = detail.get("verdict") or {}
    if verdict:
        verdict_lines = [
            (
                "Verdict",
                verdict.get("verdict_summary")
                or verdict.get("verdict")
                or "—",
            ),
            ("Key strength", verdict.get("key_strength") or "—"),
        ]
        if not hide_findings_for_hm:
            verdict_lines.extend(
                [
                    ("Key risk", verdict.get("key_risk") or "—"),
                    ("Mitigation", verdict.get("risk_mitigation") or "—"),
                ]
            )
        verdict_lines.append(
            (
                "Recommendation",
                verdict.get("recommendation_for_next_step") or "—",
            )
        )
        row = _detail_kv(ws, row, "Verdict", verdict_lines)

    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 40
    ws.column_dimensions["E"].width = 40


def _format_score(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{round(float(value), 1)}"
    return str(value)


def _detail_section(ws: Worksheet, row: int, title: str, lines: list[str]) -> int:
    cell = ws.cell(row=row, column=1, value=title)
    cell.font = _BOLD
    cell.fill = _GROUP_FILL
    cell.alignment = _BODY_ALIGN
    cell.border = _THIN_BORDER
    row += 1
    for line in lines:
        _set_body_cell(ws, row, 1, line)
        row += 1
    return row + 1


def _detail_table(
    ws: Worksheet,
    row: int,
    title: str,
    headers: list[str],
    rows_data: list[list[Any]],
) -> int:
    cell = ws.cell(row=row, column=1, value=title)
    cell.font = _BOLD
    cell.fill = _GROUP_FILL
    cell.alignment = _BODY_ALIGN
    cell.border = _THIN_BORDER
    row += 1
    for col_idx, value in enumerate(headers, start=1):
        _set_header_cell(ws, row, col_idx, value)
    row += 1
    for body_row in rows_data:
        for col_idx, value in enumerate(body_row, start=1):
            _set_body_cell(ws, row, col_idx, value)
        row += 1
    return row + 1


def _detail_kv(
    ws: Worksheet, row: int, title: str, items: list[tuple[str, Any]]
) -> int:
    cell = ws.cell(row=row, column=1, value=title)
    cell.font = _BOLD
    cell.fill = _GROUP_FILL
    cell.alignment = _BODY_ALIGN
    cell.border = _THIN_BORDER
    row += 1
    for key, value in items:
        _set_body_cell(ws, row, 1, key, bold=True)
        _set_body_cell(ws, row, 2, value)
        row += 1
    return row + 1


# ---------------------------------------------------------------------------
# Sheet 4 — Incomplete data (always emitted)
# ---------------------------------------------------------------------------


def _render_incomplete(
    ws: Worksheet, items: list[dict], *, branding: dict | None
) -> None:
    _embed_logo(ws, branding, "G1")
    ws.cell(row=1, column=1, value="Candidates with incomplete data").font = Font(
        size=14, bold=True
    )

    headers = ["Candidate", "What's missing", "What to do"]
    header_row = 3
    for col, value in enumerate(headers, start=1):
        _set_header_cell(ws, header_row, col, value)
    ws.row_dimensions[header_row].height = 22

    if not items:
        cell = ws.cell(
            row=header_row + 1,
            column=1,
            value="All candidates have complete data — no action required.",
        )
        cell.alignment = _BODY_ALIGN
        cell.font = Font(italic=True, color="6B7280")
        ws.merge_cells(
            start_row=header_row + 1,
            start_column=1,
            end_row=header_row + 1,
            end_column=3,
        )
    else:
        for idx, item in enumerate(items, start=header_row + 1):
            _set_body_cell(ws, idx, 1, item.get("candidate_name"))
            _set_body_cell(ws, idx, 2, item.get("missing"))
            _set_body_cell(ws, idx, 3, item.get("action"))

    _autosize(ws, headers, default=28)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _autosize(ws: Worksheet, headers: list[str], default: int = 24) -> None:
    for col_idx, header in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = min(
            max(len(header) + 4, default), 60
        )
