import asyncio
import base64
import csv
import re
import uuid
from collections.abc import Iterable
from datetime import date, datetime
from io import BytesIO, StringIO
from typing import NoReturn
from weakref import WeakKeyDictionary

from fastapi import UploadFile, status
from openpyxl import load_workbook
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.data_import.models import ImportJob

VALID_IMPORT_TYPES = {"employees", "dictionaries"}


# Read as Windows-1251, a Western file shows Cyrillic glued to Latin letters
# (Joerg with an umlaut reads "J\u0446rg"); a Russian one never does.
_MIXED_SCRIPT = re.compile(r"[A-Za-z][\u0400-\u04ff]|[\u0400-\u04ff][A-Za-z]")


def _decode_csv(data: bytes) -> str:
    """UTF-8 (with or without BOM), else the ANSI code page Excel saved in.

    A Western Excel saves CSV in Windows-1252, a Russian one in Windows-1251.
    """
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    # ponytail: script heuristic between the two code pages Excel users here
    # save in; a charset detector if another code page ever shows up.
    text = data.decode("cp1251", errors="replace")
    return data.decode("cp1252") if _MIXED_SCRIPT.search(text) else text


def _is_separator_hint(row: tuple) -> bool:
    """``sep=,`` - the line that tells Excel the separator (the template has it)."""
    return isinstance(row[0], str) and row[0].lower().startswith("sep=")


# Data rows one import file may hold, and how many of them the preview shows.
MAX_IMPORT_ROWS = 50_000
PREVIEW_ROWS = 100


def _too_many_rows() -> NoReturn:
    raise AppError(
        "import_too_many_rows", status.HTTP_400_BAD_REQUEST, max=MAX_IMPORT_ROWS
    )


def read_table(file_name: str, data: bytes) -> tuple[tuple, list[tuple[int, tuple]]]:
    """The header row and ``(line number, cells)`` of each data row of an
    uploaded CSV or XLSX.

    The one reader of an import file: the preview, billing and the import
    task all read through it, so they see the same rows (HRP-806).

    Blank rows are skipped but keep counting, so an error names the line the
    admin sees in the file. The first non-blank row is the header, after an
    Excel ``sep=`` line if there is one.

    HRP-806: Excel saves CSV in its locale - a German or Russian one with
    semicolons and in its ANSI code page, so the delimiter is whichever of
    ``;`` and ``,`` the header uses more. Empty CSV cells read as ``None``,
    the way openpyxl reports empty XLSX cells.
    """
    try:
        if file_name.lower().endswith(".csv"):
            text = _decode_csv(data)
            lines = [line for line in text.splitlines() if line.strip()]
            if lines and lines[0].strip().lower().startswith("sep="):
                lines = lines[1:]
            header = lines[0] if lines else ""
            delimiter = ";" if header.count(";") > header.count(",") else ","
            raw_rows: Iterable[tuple] = (
                tuple(cell.strip() or None for cell in row)
                for row in csv.reader(StringIO(text), delimiter=delimiter)
            )
        else:
            sheet = load_workbook(BytesIO(data), read_only=True).active
            raw_rows = sheet.iter_rows(values_only=True)
        # Streamed and capped: a sheet past the limit is refused before it
        # is held in memory. Blank rows do not count (a formatted but empty
        # column runs to the sheet's end); the header and a ``sep=`` line
        # are the two non-data rows allowed on top.
        numbered: list[tuple[int, tuple]] = []
        for line, row in enumerate(raw_rows, start=1):
            if any(cell is not None for cell in row):
                if len(numbered) >= MAX_IMPORT_ROWS + 2:
                    _too_many_rows()
                numbered.append((line, row))
    except AppError:
        raise
    # The upload is untrusted: whatever openpyxl or csv fails with (a
    # chartsheet as the active sheet, broken sheet XML, a bad zip) means the
    # file cannot be read, never a 500.
    except Exception:  # noqa: BLE001
        raise AppError("import_file_unreadable", status.HTTP_400_BAD_REQUEST)
    if numbered and _is_separator_hint(numbered[0][1]):
        numbered = numbered[1:]
    if not numbered:
        return (), []
    if len(numbered) > MAX_IMPORT_ROWS + 1:
        _too_many_rows()
    return numbered[0][1], numbered[1:]


def read_rows(file_name: str, data: bytes) -> list[tuple[int, tuple]]:
    """The data rows of :func:`read_table`."""
    return read_table(file_name, data)[1]


def parse_date(value) -> date | None:
    """A cell as a date: an XLSX date, ISO from the template, or DD.MM.YYYY
    as a German or Russian Excel writes a date into CSV."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.date() if isinstance(value, datetime) else value
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


_email = TypeAdapter(EmailStr)

# Leading columns a row of each import type cannot do without.
REQUIRED_COLUMNS = {"employees": 5, "dictionaries": 2}


def row_problem(import_type: str, row: tuple) -> tuple[str, int] | None:
    """Why the import task skips this row - ``(code, column index)`` - or None.

    The import reads columns by position. The preview asks this same
    question, so a file it calls valid is a file the import takes (HRP-806:
    the preview used to match columns by header name and passed a file the
    import then refused row by row).
    """
    for column in range(REQUIRED_COLUMNS[import_type]):
        if column >= len(row) or not row[column]:
            return "required", column
    if import_type == "employees":
        if parse_date(row[4]) is None:
            return "date", 4
        try:
            _email.validate_python(str(row[0]))
        except ValidationError:
            return "email", 0
    return None


_upload_rows: WeakKeyDictionary[UploadFile, list[tuple[int, tuple]]] = (
    WeakKeyDictionary()
)


async def read_upload(file: UploadFile) -> tuple[bytes, list[tuple[int, tuple]]]:
    """The upload's bytes and :func:`read_rows`, parsed off the event loop.

    Billing counts the rows before ``start_import`` runs with the same
    upload, so the parse is kept for the upload's lifetime and a large XLSX
    is read once per request. The upload is left rewound.
    """
    await file.seek(0)
    data = await file.read()
    await file.seek(0)
    if file not in _upload_rows:
        _upload_rows[file] = await asyncio.to_thread(
            read_rows, file.filename or "unnamed", data
        )
    return data, _upload_rows[file]


def _check_import_type(import_type: str) -> None:
    if import_type not in VALID_IMPORT_TYPES:
        raise AppError(
            "invalid_import_type",
            status.HTTP_400_BAD_REQUEST,
            valid=", ".join(VALID_IMPORT_TYPES),
        )


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return (value.date() if isinstance(value, datetime) else value).isoformat()
    return str(value)


async def preview_import(import_type: str, file: UploadFile) -> dict:
    """The file as the import will read it, each row with its problem.

    Read-only: nothing is stored and nothing is charged.
    """
    _check_import_type(import_type)
    await file.seek(0)
    data = await file.read()
    header, rows = await asyncio.to_thread(read_table, file.filename or "unnamed", data)
    problems = [row_problem(import_type, row) for _, row in rows]
    return {
        "columns": [_cell_text(cell) for cell in header],
        "rows": [
            {
                "line": line,
                "cells": [_cell_text(cell) for cell in row],
                "problem": (
                    {"code": problem[0], "column": problem[1]} if problem else None
                ),
            }
            for (line, row), problem in zip(
                rows[:PREVIEW_ROWS], problems[:PREVIEW_ROWS], strict=True
            )
        ],
        "total_rows": len(rows),
        "problem_rows": sum(problem is not None for problem in problems),
    }


async def start_import(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    import_type: str,
    file: UploadFile,
) -> dict:
    _check_import_type(import_type)

    data, rows = await read_upload(file)
    file_name = file.filename or "unnamed"

    job = ImportJob(
        tenant_id=tenant_id,
        import_type=import_type,
        file_name=file_name,
        total_rows=len(rows),
        initiated_by=user_id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Queue Celery task for background processing
    from app.core.task_enqueue import enqueue_task
    from app.modules.data_import.tasks import run_import_task

    b64_data = base64.b64encode(data).decode()
    enqueue_task(
        run_import_task,
        str(job.id),
        str(tenant_id),
        str(user_id),
        import_type,
        b64_data,
        tenant_id=tenant_id,
        user_id=user_id,
        module="data_import",
        action=f"import_{import_type}",
    )

    return _job_to_dict(job)


async def get_job(db: AsyncSession, tenant_id: uuid.UUID, job_id: uuid.UUID) -> dict:
    job = await db.get(ImportJob, job_id)
    if not job or job.tenant_id != tenant_id:
        raise AppError("import_job_not_found", status.HTTP_404_NOT_FOUND)
    return _job_to_dict(job)


async def list_jobs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[dict], int]:
    count_q = select(func.count(ImportJob.id)).where(ImportJob.tenant_id == tenant_id)
    total = (await db.execute(count_q)).scalar() or 0

    result = await db.execute(
        select(ImportJob)
        .where(ImportJob.tenant_id == tenant_id)
        .order_by(ImportJob.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return [_job_to_dict(j) for j in result.scalars().all()], total


def _job_to_dict(j: ImportJob) -> dict:
    return {
        "id": j.id,
        "import_type": j.import_type,
        "file_name": j.file_name,
        "status": j.status,
        "total_rows": j.total_rows,
        "processed_rows": j.processed_rows,
        "error_rows": j.error_rows,
        "errors": j.errors,
        "initiated_by": j.initiated_by,
        "tenant_id": j.tenant_id,
        "started_at": j.started_at,
        "finished_at": j.finished_at,
        "created_at": j.created_at,
    }
