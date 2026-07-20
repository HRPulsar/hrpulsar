import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import BaseModel


class DictionaryItem(BaseModel):
    """
    Unified dictionary item. Covers: grade, specialization, role, goal, project.

    tenant_id = NULL → origin (system-wide, immutable by tenants)
    tenant_id = uuid → custom (tenant-specific)
    """

    __tablename__ = "dictionary_items"
    __table_args__ = (
        UniqueConstraint(
            "type", "title", "tenant_id", name="uq_dict_item_type_title_tenant"
        ),
    )

    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)


class DictionaryItemTenantOverride(Base):
    """HRP-285: per-tenant override for an origin (Source=System) item.

    Only ``is_active`` is overridable — title / description / sort_index
    of origin items remain immutable by tenants. Absence of a row means
    the tenant inherits the origin ``is_active``.
    """

    __tablename__ = "dictionary_item_tenant_overrides"
    __table_args__ = (
        PrimaryKeyConstraint(
            "item_id", "tenant_id", name="pk_dict_item_tenant_override"
        ),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
