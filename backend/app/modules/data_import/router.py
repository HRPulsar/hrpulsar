import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sections import require_section
from app.core.upload_validation import assert_declared_size_within_limit
from app.database import get_db
from app.modules.auth.models import User
from app.modules.data_import import service
from app.modules.data_import.schemas import ImportJobList, ImportJobRead

router = APIRouter(tags=["data-import"])

# HRP-831: the import section on the tenant's matrix - ``view`` reads the
# job history, ``manage`` starts an import.
_view = require_section("import", "view")
_manage = require_section("import", "manage")


@router.post(
    "/import/{import_type}",
    response_model=ImportJobRead,
    status_code=201,
    dependencies=[Depends(assert_declared_size_within_limit)],
)
async def start_import(
    import_type: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_manage),
):
    return await service.start_import(
        db, current_user.tenant_id, current_user.id, import_type, file
    )


@router.get("/import/jobs", response_model=ImportJobList)
async def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
):
    items, total = await service.list_jobs(db, current_user.tenant_id, skip, limit)
    return {"items": items, "total": total}


@router.get("/import/jobs/{job_id}", response_model=ImportJobRead)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
):
    return await service.get_job(db, current_user.tenant_id, job_id)
