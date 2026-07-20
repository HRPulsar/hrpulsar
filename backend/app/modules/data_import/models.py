import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import BaseModel, TenantMixin


class ImportJob(BaseModel, TenantMixin):
    """Tracks an import operation (CSV/Excel)."""

    __tablename__ = "import_jobs"

    import_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # employees, competences, dictionaries
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", server_default="pending"
    )  # pending, processing, completed, failed
    total_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    processed_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    errors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    initiated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
