import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import BaseModel, TenantMixin

LIFECYCLE_STATUSES = ("active", "on_hold", "frozen", "closed")


class Position(BaseModel, TenantMixin):
    """Structured job position within an organization."""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "title", name="uq_position_tenant_title"),
        CheckConstraint(
            "lifecycle_status IN ('active','on_hold','frozen','closed')",
            name="ck_position_lifecycle_status",
        ),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    specialization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    grade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    division_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("divisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    headcount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual", server_default="manual"
    )

    specialization = relationship(
        "DictionaryItem", foreign_keys=[specialization_id], lazy="selectin"
    )
    grade = relationship("DictionaryItem", foreign_keys=[grade_id], lazy="selectin")
    division = relationship("Division", lazy="selectin")
