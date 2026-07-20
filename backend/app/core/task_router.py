"""Generic background task status endpoint.

Uses Celery's AsyncResult to check task status. Works for any Celery task
that stores results in the result backend (Redis).
"""

from celery.result import AsyncResult
from fastapi import APIRouter, Depends

from app.core.celery_app import celery
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User

router = APIRouter(tags=["tasks"])


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    _: User = Depends(get_current_user),
):
    """Check the status of a background task by its Celery task ID."""
    result = AsyncResult(task_id, app=celery)
    response = {
        "task_id": task_id,
        "status": result.status,  # PENDING, STARTED, SUCCESS, FAILURE, RETRY
    }
    if result.successful():
        response["result"] = result.result
    elif result.failed():
        response["error"] = str(result.result)
    return response
