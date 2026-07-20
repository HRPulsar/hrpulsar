"""SignupRequest model — pre-tenant landing/demo signup record.

Distinct from ``Tenant`` + ``User`` so we don't leave dead rows in the
core tables on reject. Created on form submit, flipped through email
verify → Slack moderation → approve/reject. On approve the row is the
last reference to the verified email before the real account exists;
afterwards it remains as an immutable audit row.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import BaseModel

SIGNUP_STATUSES = (
    "pending_email_verify",
    "pending_moderation",
    "approved",
    "rejected",
    "expired",
)

SIGNUP_SOURCES = ("landing", "demo")


class SignupRequest(BaseModel):
    """Pending sign-up awaiting email verification + Slack moderation.

    Lifecycle:
      pending_email_verify → pending_moderation → approved | rejected

    The row is never deleted post-moderation — it is the audit record
    for how an account came to exist (who approved, when, from where).
    """

    __tablename__ = "signup_requests"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="pending_email_verify",
    )
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="landing",
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    moderated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    moderated_by_slack_user_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    reject_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    slack_message_ts: Mapped[str | None] = mapped_column(String(40), nullable=True)
    demo_tenant_id_snapshot: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
