from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ImportJobRead(BaseModel):
    id: uuid.UUID
    import_type: str
    file_name: str
    status: str
    total_rows: int
    processed_rows: int
    error_rows: int
    errors: dict[str, Any] | None = None
    initiated_by: uuid.UUID
    tenant_id: uuid.UUID
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ImportJobList(BaseModel):
    items: list[ImportJobRead]
    total: int
