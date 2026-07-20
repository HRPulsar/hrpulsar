import uuid

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import BaseModel


class TenantAISettings(BaseModel):
    """Per-tenant configuration applied to every AI generation call.

    Columns map 1:1 to the user-facing PATCH schema except `tenant_id`,
    which is the unique join key. Effective values combine these stored
    columns with `EFFORT_PRESETS` in `service.py` — explicit overrides
    win, presets fill in the rest.
    """

    __tablename__ = "tenant_ai_settings"
    __table_args__ = (
        CheckConstraint(
            "content_language IN ('en')",
            name="ck_tenant_ai_settings_content_language",
        ),
        CheckConstraint(
            "effort_level IN ('fast','balanced','thorough','custom')",
            name="ck_tenant_ai_settings_effort_level",
        ),
        CheckConstraint(
            "temperature >= 0 AND temperature <= 1",
            name="ck_tenant_ai_settings_temperature_range",
        ),
        CheckConstraint(
            "max_retries >= 1 AND max_retries <= 10",
            name="ck_tenant_ai_settings_max_retries_range",
        ),
        CheckConstraint(
            "company_context IS NULL OR length(company_context) <= 2000",
            name="ck_tenant_ai_settings_company_context_length",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    content_language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="en", server_default="en"
    )
    effort_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="balanced", server_default="balanced"
    )

    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    temperature: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.3, server_default="0.3"
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )

    company_context: Mapped[str | None] = mapped_column(String(2000), nullable=True)
