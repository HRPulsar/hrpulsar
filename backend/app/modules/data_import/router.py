import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.dependencies import require_role
from app.modules.auth.models import User
from app.modules.data_import import service
from app.modules.data_import.schemas import ImportJobList, ImportJobRead

router = APIRouter(tags=["data-import"])


@router.post("/import/{import_type}", response_model=ImportJobRead, status_code=201)
async def start_import(
    import_type: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.start_import(
        db, current_user.tenant_id, current_user.id, import_type, file
    )


@router.get("/import/jobs", response_model=ImportJobList)
async def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    items, total = await service.list_jobs(db, current_user.tenant_id, skip, limit)
    return {"items": items, "total": total}


@router.get("/import/jobs/{job_id}", response_model=ImportJobRead)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return await service.get_job(db, current_user.tenant_id, job_id)
