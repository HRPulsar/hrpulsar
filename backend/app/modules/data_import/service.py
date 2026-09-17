import asyncio
import base64
import csv
import uuid
from io import BytesIO, StringIO
from weakref import WeakKeyDictionary

from fastapi import UploadFile, status
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.data_import.models import ImportJob

VALID_IMPORT_TYPES = {"employees", "dictionaries"}


def read_rows(file_name: str, data: bytes) -> list[tuple[int, tuple]]:
    """``(line number, cells)`` for each data row of an uploaded CSV or XLSX.

    Blank rows are skipped but keep counting, so an error names the line the
    admin sees in the file. The first non-blank row is the header.

    HRP-806: the import page hands out a CSV template, which openpyxl cannot
    open. A German Excel saves plain CSV in Windows-1252 with semicolons, so
    UTF-8 falls back to cp1252 and the delimiter is whichever of ``;`` and
    ``,`` the header uses more. Empty CSV cells read as ``None``, the way
    openpyxl reports empty XLSX cells.
    """
    try:
        if file_name.lower().endswith(".csv"):
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("cp1252")
            header = next((line for line in text.splitlines() if line.strip()), "")
            delimiter = ";" if header.count(";") > header.count(",") else ","
            raw_rows = [
                tuple(cell.strip() or None for cell in row)
                for row in csv.reader(StringIO(text), delimiter=delimiter)
            ]
        else:
            sheet = load_workbook(BytesIO(data), read_only=True).active
            raw_rows = list(sheet.iter_rows(values_only=True))
    # The upload is untrusted: whatever openpyxl or csv fails with (a
    # chartsheet as the active sheet, broken sheet XML, a bad zip) means the
    # file cannot be read, never a 500.
    except Exception:  # noqa: BLE001
        raise AppError("import_file_unreadable", status.HTTP_400_BAD_REQUEST)
    numbered = [
        (line, row)
        for line, row in enumerate(raw_rows, start=1)
        if any(cell is not None for cell in row)
    ]
    return numbered[1:]


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


async def start_import(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    import_type: str,
    file: UploadFile,
) -> dict:
    if import_type not in VALID_IMPORT_TYPES:
        raise AppError(
            "invalid_import_type",
            status.HTTP_400_BAD_REQUEST,
            valid=", ".join(VALID_IMPORT_TYPES),
        )

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
