"""Pydantic schemas for recruitment settings hub, audit log, GDPR (R4b)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

# ─── Scale ─────────────────────────────────────────────────────────


class ScaleConfigCreate(BaseModel):
    name: str = Field(max_length=100)
    min_value: float
    max_value: float
    step: float = 0.5
    labels: dict | None = None
    is_active: bool = True


class ScaleConfigUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    labels: dict | None = None
    is_active: bool | None = None


class ScaleConfigRead(BaseModel):
    id: uuid.UUID
    name: str
    min_value: float
    max_value: float
    step: float
    labels: dict | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── LLM provider config ────────────────────────────────────────────

LLMProviderName = Literal[
    "anthropic", "openai", "gemini", "azure", "yandex", "gigachat"
]


class LLMProviderCreate(BaseModel):
    provider: LLMProviderName
    model: str = Field(max_length=100)
    api_key: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    settings: dict | None = None


class LLMProviderUpdate(BaseModel):
    model: str | None = Field(default=None, max_length=100)
    # api_key === replace; null/missing = no change. Empty string = clear.
    api_key: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    settings: dict | None = None


KeyStatus = Literal["ok", "missing", "decrypt_failed"]


class LLMProviderRead(BaseModel):
    id: uuid.UUID
    provider: str
    model: str
    api_key_masked: str | None = None
    key_status: KeyStatus = "missing"
    is_active: bool
    settings: dict | None = None
    created_at: datetime
    updated_at: datetime


# ─── Transcription provider config ──────────────────────────────────

TranscriptionProviderName = Literal[
    "whisper", "deepgram", "assemblyai", "faster_whisper"
]


class TranscriptionProviderCreate(BaseModel):
    provider: TranscriptionProviderName
    api_key: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    settings: dict | None = None


class TranscriptionProviderUpdate(BaseModel):
    api_key: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    settings: dict | None = None


class TranscriptionProviderRead(BaseModel):
    id: uuid.UUID
    provider: str
    api_key_masked: str | None = None
    key_status: KeyStatus = "missing"
    is_active: bool
    settings: dict | None = None
    created_at: datetime
    updated_at: datetime


# ─── Branding (SCR-95) ───────────────────────────────────────────────


class BrandingRead(BaseModel):
    logo_file_id: uuid.UUID | None = None
    logo_url: str | None = None
    accent_color: str | None = None
    secondary_color: str | None = None
    watermark_text: str | None = None
    raw: dict | None = None


class BrandingUpdate(BaseModel):
    accent_color: str | None = Field(default=None, max_length=20)
    secondary_color: str | None = Field(default=None, max_length=20)
    watermark_text: str | None = Field(default=None, max_length=200)
    extra: dict | None = None


# ─── Retention (SCR-96) ─────────────────────────────────────────────


class RetentionRead(BaseModel):
    interviews_days: int
    resumes_days: int
    consents_days: int
    reports_days: int


class RetentionUpdate(BaseModel):
    interviews_days: int | None = Field(default=None, ge=1, le=3650)
    resumes_days: int | None = Field(default=None, ge=1, le=3650)
    consents_days: int | None = Field(default=None, ge=1, le=3650)
    reports_days: int | None = Field(default=None, ge=1, le=3650)


# ─── Matrix settings (HRP-265) ──────────────────────────────────────


class MatrixSettingsRead(BaseModel):
    """Read shape returned by ``GET /recruitment/settings/matrix``.

    ``divergence_threshold`` is the absolute Manager vs AI score gap (on
    the active assessment scale) at which the Compact matrix / Canvas
    starts marking a cell as divergent. Tenants without an explicit row
    fall back to ``1.0`` — the historical hard-coded default.
    """

    divergence_threshold: float


class MatrixSettingsUpdate(BaseModel):
    # ``gt=0`` rejects the degenerate threshold=0 case where ``abs(m-ai) >=
    # 0`` is always True and every cell with both scores would be flagged
    # as divergent — that hides every real divergence in a sea of amber.
    divergence_threshold: float | None = Field(default=None, gt=0.0, le=10.0)


# ─── Roles (SCR-99 — read-only view) ─────────────────────────────


class RecruitmentRolePermission(BaseModel):
    code: str
    description: str


class RecruitmentRoleRead(BaseModel):
    code: str
    name: str
    description: str
    permissions: list[RecruitmentRolePermission]


# ─── Audit log ──────────────────────────────────────────────────────


class AuditEventRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    user_email: str | None = None
    user_name: str | None = None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None = None
    payload_diff: dict | None = None
    ip: str | None = None
    user_agent: str | None = None
    created_at: datetime


# ─── GDPR ────────────────────────────────────────────────────────────


class GDPRExportRequestCreate(BaseModel):
    candidate_id: uuid.UUID | None = None
    person_id: uuid.UUID | None = None
    email: EmailStr | None = None


class GDPREraseRequest(BaseModel):
    candidate_id: uuid.UUID
    confirm: bool = False


class GDPRExportRead(BaseModel):
    id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID
    status: str
    file_url: str | None = None
    expires_at: datetime | None = None
    requested_by: uuid.UUID | None = None
    error: str | None = None
    created_at: datetime


class GDPRErasureRead(BaseModel):
    id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID
    requested_by: uuid.UUID | None = None
    affected: dict | None = None
    created_at: datetime
