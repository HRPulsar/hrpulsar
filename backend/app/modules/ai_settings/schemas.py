import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ContentLanguage = Literal["en"]
EffortLevel = Literal["fast", "balanced", "thorough", "custom"]
LLMProvider = Literal["anthropic", "openai", "gemini"]


class AISettingsRead(BaseModel):
    """Stored row + effective values resolved through the active preset."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID

    content_language: ContentLanguage
    effort_level: EffortLevel
    llm_model: str | None
    temperature: float
    max_retries: int
    company_context: str | None

    effective_model: str
    effective_provider: LLMProvider
    effective_temperature: float
    effective_max_retries: int
    effective_credit_multiplier: float

    created_at: datetime
    updated_at: datetime


class AISettingsUpdate(BaseModel):
    """All fields optional — null means "leave as is"."""

    content_language: ContentLanguage | None = None
    effort_level: EffortLevel | None = None
    llm_model: str | None = Field(default=None, max_length=100)
    temperature: float | None = Field(default=None, ge=0, le=1)
    max_retries: int | None = Field(default=None, ge=1, le=10)
    company_context: str | None = Field(default=None, max_length=2000)


class EffortPresetRead(BaseModel):
    """One preset row for the GET /presets endpoint."""

    name: EffortLevel
    description: str
    temperature: float
    max_retries: int
    models: dict[LLMProvider, str]


class AllowedModelRead(BaseModel):
    """One whitelist row for the GET /models endpoint."""

    provider: LLMProvider
    model: str
    label: str
    credit_multiplier: float
