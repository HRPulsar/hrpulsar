import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import BaseModel

# Lifecycle: pending → running → ready/error → applied/cancelled.
# `applied` is terminal-success; `cancelled` is terminal-noop. The partial
# unique index below treats {pending, running, ready} as «active» — exactly
# one such row per user is allowed by the DB.
SESSION_STATUSES = ("pending", "running", "ready", "error", "applied", "cancelled")
ACTIVE_STATUSES = ("pending", "running", "ready")
SESSION_SCOPES = (
    "whole_base",
    "group",
    "competence_indicators",
    "specialization_matrix",
)
ERROR_CODES = (
    "service_error",
    "overload",
    "insufficient_data",
    "parse_error",
    # HRP-163: set by the reap-stuck-sessions beat job when a worker
    # exited without updating its row (OOM / SIGKILL / host reboot).
    "reaped_stuck",
)


class CompetenceGenerationSession(BaseModel):
    """One user-initiated AI generation run, plus its derived state."""

    __tablename__ = "competence_generation_sessions"
    __table_args__ = (
        CheckConstraint(
            f"scope IN {SESSION_SCOPES!r}",
            name="ck_compgen_scope",
        ),
        CheckConstraint(
            f"status IN {SESSION_STATUSES!r}",
            name="ck_compgen_status",
        ),
        CheckConstraint(
            f"error_code IS NULL OR error_code IN {ERROR_CODES!r}",
            name="ck_compgen_error_code",
        ),
        Index(
            "ux_compgen_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=("status IN ('pending','running','ready')"),
        ),
        Index("ix_compgen_tenant", "tenant_id"),
        Index("ix_compgen_user", "user_id"),
        Index("ix_compgen_status", "status"),
        Index("ix_compgen_parent", "parent_session_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    base_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    selection_state: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    parent_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("competence_generation_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    prompt_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="cr11.v1", server_default="cr11.v1"
    )
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    applied_idempotency_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    applied_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
