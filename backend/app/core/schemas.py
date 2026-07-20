"""Shared response schemas for core infrastructure patterns.

Keep this module small: only shapes that are produced by cross-cutting
infrastructure (e.g. background-task enqueueing) and reused by several
module routers belong here. Domain-specific schemas live in their module's
``schemas.py``.
"""

from pydantic import BaseModel


class TaskAccepted(BaseModel):
    """Response of endpoints that enqueue a background task and return only
    the Celery task id, to be polled via ``GET /api/tasks/{task_id}``.

    Not for endpoints that are polymorphic on ``?sync=`` (their sync branch
    returns the service result) or that add extra fields next to ``task_id``.
    """

    task_id: str
