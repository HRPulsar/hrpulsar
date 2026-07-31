import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import BaseModel, TenantMixin


class NotificationTemplate(BaseModel):
    __tablename__ = "notification_templates"
    __table_args__ = (
        UniqueConstraint(
            "code", "locale", name="uq_notification_templates_code_locale"
        ),
    )

    code: Mapped[str] = mapped_column(String(100), nullable=False)
    # One row per (code, locale); non-en rows are seeded by migration as
    # English copies until translated (i18n F4, HRP-478). Lookups resolve
    # the recipient locale first and fall back to the en row.
    locale: Mapped[str] = mapped_column(
        String(10), nullable=False, default="en", server_default="en"
    )
    subject_template: Mapped[str] = mapped_column(String(500), nullable=False)
    body_template: Mapped[str] = mapped_column(String(5000), nullable=False)
    notification_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="email", server_default="email"
    )


class Notification(BaseModel, TenantMixin):
    __tablename__ = "notifications"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_templates.id"),
        nullable=False,
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", server_default="pending"
    )
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EmailLog(BaseModel):
    """Tracks every email sent through the system for delivery monitoring."""

    __tablename__ = "email_logs"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recipient: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    template_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="sent", server_default="sent"
    )  # sent, delivered, bounced, complained, failed
    message_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True, index=True
    )
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    attempts: Mapped[int] = mapped_column(default=1, server_default="1")
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class NotificationPreference(BaseModel):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "event_type", "channel", name="uq_notif_pref_user_event_channel"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # assessment_assigned, pdp_sent, exam_assigned, deadline_reminder, etc.
    channel: Mapped[str] = mapped_column(
        String(50), nullable=False, default="email", server_default="email"
    )  # email, in_app
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
