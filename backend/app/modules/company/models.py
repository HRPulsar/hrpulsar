import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import BaseModel, TenantMixin


class Tenant(BaseModel):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )

    # GF10: Company profile fields
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_size: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # 1-10, 11-50, 51-200, 201-500, 501-1000, 1001-5000, 5000+
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # GF10: Company logo
    logo_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
    )

    # H3: Onboarding wizard
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # R4b: Recruitment branding overrides (accent, watermark, palette JSON)
    recruitment_branding: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # R4c: Recruitment onboarding wizard state — JSONB blob with shape
    # ``{"step": <wizard step>, "dismissed_at": iso, "demo_seeded_at": iso}``.
    # Wizard step values: welcome, vacancy_created, candidate_invited,
    # interview_scheduled, report_reviewed, done.
    recruitment_onboarding: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # HRP-265: per-tenant assessment matrix settings — currently
    # ``{"divergence_threshold": <float>}`` driving the M vs AI gap
    # highlighting in the Compact matrix / Canvas. Lives in JSONB so
    # HRP-206b/c can extend with toolbar defaults without new migrations.
    recruitment_matrix_settings: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )

    # HRP-249 (D1): public-demo sandbox lifecycle. ``is_demo`` flags a
    # throw-away tenant; ``expires_at`` is the hard TTL; ``last_active_at``
    # is a sliding inactivity stamp updated (debounced) by the auth dep.
    # The cleanup beat task purges rows whose ``expires_at`` is in the past
    # or whose ``last_active_at`` is older than
    # ``DEMO_INACTIVITY_TTL_SECONDS``. All three are nullable so non-demo
    # tenants stay untouched.
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    divisions: Mapped[list["Division"]] = relationship(back_populates="tenant")
    activity_fields: Mapped[list["CompanyActivityField"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class Division(BaseModel, TenantMixin):
    __tablename__ = "divisions"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("divisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "employees.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_divisions_manager_id",
        ),
        nullable=True,
        index=True,
    )

    deputy_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "employees.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_divisions_deputy_manager_id",
        ),
        nullable=True,
        index=True,
    )

    parent: Mapped["Division | None"] = relationship(
        remote_side="Division.id", back_populates="children"
    )
    children: Mapped[list["Division"]] = relationship(back_populates="parent")
    tenant: Mapped["Tenant"] = relationship(back_populates="divisions")
    manager = relationship("Employee", foreign_keys=[manager_id], lazy="selectin")
    deputy_manager = relationship(
        "Employee", foreign_keys=[deputy_manager_id], lazy="selectin"
    )


class SpecializationDivision(BaseModel, TenantMixin):
    """Links a specialization (dictionary_item) to a division."""

    __tablename__ = "specialization_divisions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "division_id",
            "specialization_id",
            name="uq_spec_div_tenant",
        ),
    )

    division_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("divisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    specialization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="CASCADE"),
        nullable=False,
    )

    division = relationship("Division", lazy="selectin")
    specialization = relationship("DictionaryItem", lazy="selectin")


# --- GF10: Company Activity Fields ---


class CompanyActivityField(BaseModel, TenantMixin):
    """Links a tenant to activity fields (business sectors)."""

    __tablename__ = "company_activity_fields"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "activity_field_id",
            name="uq_company_activity_field",
        ),
    )

    activity_field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dictionary_items.id", ondelete="CASCADE"),
        nullable=False,
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="activity_fields")
    activity_field = relationship("DictionaryItem", lazy="selectin")
