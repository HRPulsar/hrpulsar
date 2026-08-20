"""Recruitment settings hub — scales, LLM/STT providers, branding, retention.

R4b. Each mutating function has a counterpart entry in
``ee/billing.py:BILLABLE``; read-only listers are listed in
``BILLING_EXEMPT``. Tenants are isolated through ``tenant_id`` checks on
every query.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.core.errors import AppError
from app.core.s3 import get_presigned_url
from app.core.url_guard import ensure_public_base_url
from app.modules.company.models import Tenant
from app.modules.recruitment.models import (
    LLMProviderConfig,
    RecruitmentRetentionConfig,
    ScaleConfig,
    TranscriptionProviderConfig,
)
from app.modules.storage.models import File

log = logging.getLogger(__name__)
from app.modules.recruitment.settings_schemas import (
    BrandingUpdate,
    LLMProviderCreate,
    LLMProviderUpdate,
    MatrixSettingsUpdate,
    RetentionUpdate,
    ScaleConfigCreate,
    ScaleConfigUpdate,
    TranscriptionProviderCreate,
    TranscriptionProviderUpdate,
    ensure_provider_owns_model,
    ensure_yandex_model_is_dispatchable,
)

# ─── Scales (SCR-90) ────────────────────────────────────────────────


async def list_scales(db: AsyncSession, tenant_id: uuid.UUID) -> list[ScaleConfig]:
    result = await db.execute(
        select(ScaleConfig)
        .where(ScaleConfig.tenant_id == tenant_id)
        .order_by(ScaleConfig.created_at.desc())
    )
    return list(result.scalars().all())


async def get_active_scale(
    db: AsyncSession, tenant_id: uuid.UUID
) -> ScaleConfig | None:
    result = await db.execute(
        select(ScaleConfig)
        .where(ScaleConfig.tenant_id == tenant_id, ScaleConfig.is_active.is_(True))
        .order_by(ScaleConfig.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _deactivate_other_scales(
    db: AsyncSession, tenant_id: uuid.UUID, exclude_id: uuid.UUID | None = None
) -> None:
    result = await db.execute(
        select(ScaleConfig).where(
            ScaleConfig.tenant_id == tenant_id, ScaleConfig.is_active.is_(True)
        )
    )
    for scale in result.scalars().all():
        if exclude_id and scale.id == exclude_id:
            continue
        scale.is_active = False


async def create_scale(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: ScaleConfigCreate,
) -> ScaleConfig:
    if data.max_value <= data.min_value:
        raise AppError(
            "scale_max_must_exceed_min",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if data.is_active:
        await _deactivate_other_scales(db, tenant_id)
    scale = ScaleConfig(
        tenant_id=tenant_id,
        name=data.name,
        min_value=data.min_value,
        max_value=data.max_value,
        step=data.step,
        labels=data.labels,
        is_active=data.is_active,
    )
    db.add(scale)
    await db.commit()
    await db.refresh(scale)
    return scale


async def update_scale(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    scale_id: uuid.UUID,
    data: ScaleConfigUpdate,
) -> ScaleConfig:
    scale = await _get_scale(db, tenant_id, scale_id)
    payload = data.model_dump(exclude_unset=True)
    if "is_active" in payload and payload["is_active"]:
        await _deactivate_other_scales(db, tenant_id, exclude_id=scale.id)
    for k, v in payload.items():
        setattr(scale, k, v)
    if scale.max_value <= scale.min_value:
        raise AppError(
            "scale_max_must_exceed_min",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    await db.commit()
    await db.refresh(scale)
    return scale


async def delete_scale(
    db: AsyncSession, tenant_id: uuid.UUID, scale_id: uuid.UUID
) -> None:
    scale = await _get_scale(db, tenant_id, scale_id)
    await db.delete(scale)
    await db.commit()


async def _get_scale(
    db: AsyncSession, tenant_id: uuid.UUID, scale_id: uuid.UUID
) -> ScaleConfig:
    scale = await db.get(ScaleConfig, scale_id)
    if not scale or scale.tenant_id != tenant_id:
        raise AppError("scale_not_found", status.HTTP_404_NOT_FOUND)
    return scale


# ─── LLM providers (SCR-97) ─────────────────────────────────────────


async def list_llm_providers(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[LLMProviderConfig]:
    result = await db.execute(
        select(LLMProviderConfig)
        .where(LLMProviderConfig.tenant_id == tenant_id)
        .order_by(LLMProviderConfig.created_at.desc())
    )
    return list(result.scalars().all())


async def _guard_llm_settings(provider_settings: dict | None) -> None:
    """SSRF guard (saas only): a tenant-set base_url becomes a server-side
    request target for every generation call — it must not point inside
    the platform perimeter. Self-hosted installs pass through (a private
    Ollama/vLLM endpoint is the feature there)."""
    raw = (provider_settings or {}).get("base_url")
    if isinstance(raw, str) and raw:
        await ensure_public_base_url(raw, error_code="llm_base_url_not_public")


async def create_llm_provider(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: LLMProviderCreate,
) -> LLMProviderConfig:
    await _guard_llm_settings(data.settings)
    cfg = LLMProviderConfig(
        tenant_id=tenant_id,
        provider=data.provider,
        model=data.model,
        api_key_encrypted=encrypt_secret(data.api_key) if data.api_key else None,
        is_active=data.is_active,
        settings=data.settings,
    )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return cfg


async def update_llm_provider(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    config_id: uuid.UUID,
    data: LLMProviderUpdate,
) -> LLMProviderConfig:
    cfg = await db.get(LLMProviderConfig, config_id)
    if not cfg or cfg.tenant_id != tenant_id:
        raise AppError("llm_provider_not_found", status.HTTP_404_NOT_FOUND)
    payload = data.model_dump(exclude_unset=True)
    if "settings" in payload:
        await _guard_llm_settings(payload["settings"])
    if payload.get("model"):
        # The patch carries no provider — cross-check the new model against
        # the row's stored one (HRP-498). The row's base_url (patched in the
        # same call, or the stored one) decides whether prefix ownership
        # applies at all: proxies serve upstream model ids verbatim.
        effective_settings = payload.get("settings", cfg.settings)
        try:
            ensure_provider_owns_model(
                cfg.provider, payload["model"], effective_settings
            )
        except ValueError:
            raise AppError(
                "llm_provider_model_mismatch",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                provider=cfg.provider,
                model=payload["model"],
            ) from None
    if payload.get("model") or "settings" in payload:
        # A patch must not strand a Yandex row in the dispatcher's skip
        # zone (HRP-599): dropping the base_url or shortening the model
        # both need the same guard as create.
        effective_settings = payload.get("settings", cfg.settings)
        effective_model = payload.get("model") or cfg.model
        try:
            ensure_yandex_model_is_dispatchable(
                cfg.provider, effective_model, effective_settings
            )
        except ValueError:
            raise AppError(
                "llm_yandex_model_not_dispatchable",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                model=effective_model,
            ) from None
    if "api_key" in payload:
        new_key = payload.pop("api_key")
        cfg.api_key_encrypted = encrypt_secret(new_key) if new_key else None
    for k, v in payload.items():
        setattr(cfg, k, v)
    await db.commit()
    await db.refresh(cfg)
    return cfg


async def delete_llm_provider(
    db: AsyncSession, tenant_id: uuid.UUID, config_id: uuid.UUID
) -> None:
    cfg = await db.get(LLMProviderConfig, config_id)
    if not cfg or cfg.tenant_id != tenant_id:
        raise AppError("llm_provider_not_found", status.HTTP_404_NOT_FOUND)
    await db.delete(cfg)
    await db.commit()


def _decode_api_key(encrypted: str | None, *, context: str) -> tuple[str | None, str]:
    """Decrypt-or-fail-soft helper. Returns ``(masked, key_status)``.

    Read endpoints must never 500 the whole settings page just because a
    single provider's at-rest secret is unreadable (e.g. ENCRYPTION_KEY
    was rotated without re-encrypting). Surfacing ``key_status`` to the
    client lets the UI ask the operator to reset the key explicitly.
    """
    if not encrypted:
        return None, "missing"
    try:
        plain = decrypt_secret(encrypted)
    except ValueError:
        log.warning("settings.decrypt_failed", extra={"context": context})
        return "•••• (decrypt failed)", "decrypt_failed"
    return mask_secret(plain), "ok"


def llm_provider_to_read(cfg: LLMProviderConfig) -> dict:
    masked, key_status = _decode_api_key(
        cfg.api_key_encrypted, context=f"llm_provider:{cfg.id}"
    )
    return {
        "id": cfg.id,
        "provider": cfg.provider,
        "model": cfg.model,
        "api_key_masked": masked,
        "key_status": key_status,
        "is_active": cfg.is_active,
        "settings": cfg.settings,
        "created_at": cfg.created_at,
        "updated_at": cfg.updated_at,
    }


# ─── Transcription providers (SCR-98) ────────────────────────────────


async def list_transcription_providers(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[TranscriptionProviderConfig]:
    result = await db.execute(
        select(TranscriptionProviderConfig)
        .where(TranscriptionProviderConfig.tenant_id == tenant_id)
        .order_by(TranscriptionProviderConfig.created_at.desc())
    )
    return list(result.scalars().all())


async def create_transcription_provider(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: TranscriptionProviderCreate,
) -> TranscriptionProviderConfig:
    cfg = TranscriptionProviderConfig(
        tenant_id=tenant_id,
        provider=data.provider,
        api_key_encrypted=encrypt_secret(data.api_key) if data.api_key else None,
        is_active=data.is_active,
        settings=data.settings,
    )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return cfg


async def update_transcription_provider(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    config_id: uuid.UUID,
    data: TranscriptionProviderUpdate,
) -> TranscriptionProviderConfig:
    cfg = await db.get(TranscriptionProviderConfig, config_id)
    if not cfg or cfg.tenant_id != tenant_id:
        raise AppError("transcription_provider_not_found", status.HTTP_404_NOT_FOUND)
    payload = data.model_dump(exclude_unset=True)
    if "api_key" in payload:
        new_key = payload.pop("api_key")
        cfg.api_key_encrypted = encrypt_secret(new_key) if new_key else None
    for k, v in payload.items():
        setattr(cfg, k, v)
    await db.commit()
    await db.refresh(cfg)
    return cfg


async def delete_transcription_provider(
    db: AsyncSession, tenant_id: uuid.UUID, config_id: uuid.UUID
) -> None:
    cfg = await db.get(TranscriptionProviderConfig, config_id)
    if not cfg or cfg.tenant_id != tenant_id:
        raise AppError("transcription_provider_not_found", status.HTTP_404_NOT_FOUND)
    await db.delete(cfg)
    await db.commit()


def transcription_provider_to_read(cfg: TranscriptionProviderConfig) -> dict:
    masked, key_status = _decode_api_key(
        cfg.api_key_encrypted, context=f"transcription_provider:{cfg.id}"
    )
    return {
        "id": cfg.id,
        "provider": cfg.provider,
        "api_key_masked": masked,
        "key_status": key_status,
        "is_active": cfg.is_active,
        "settings": cfg.settings,
        "created_at": cfg.created_at,
        "updated_at": cfg.updated_at,
    }


# ─── Branding (SCR-95) ──────────────────────────────────────────────


_BRANDING_LOGO_TTL_SECONDS = 3600


async def get_branding(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise AppError("tenant_not_found", status.HTTP_404_NOT_FOUND)
    raw = tenant.recruitment_branding or {}

    logo_url: str | None = None
    if tenant.logo_file_id:
        file_row = await db.get(File, tenant.logo_file_id)
        # Belt-and-braces tenant check: tenant.logo_file_id is set inside
        # the tenant's own admin flow, but resolving the URL still proves
        # the underlying File row belongs to this tenant before signing.
        if file_row is not None and file_row.tenant_id == tenant_id:
            logo_url = get_presigned_url(
                file_row.path, expires_in=_BRANDING_LOGO_TTL_SECONDS
            )

    return {
        "logo_file_id": tenant.logo_file_id,
        "logo_url": logo_url,
        "accent_color": raw.get("accent_color"),
        "secondary_color": raw.get("secondary_color"),
        "watermark_text": raw.get("watermark_text"),
        "raw": raw,
    }


async def get_ui_settings(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """HRP-205 REDO: tenant UI flags readable by every authenticated user.

    The flags live in the same ``tenant.recruitment_branding`` raw dict
    the settings hub already manages (written via the branding ``extra``
    passthrough), but the branding endpoint itself is admin/recruiter/hrd
    only — hiring managers need this read-only slice to reorder their
    candidate-page sections.
    """
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise AppError("tenant_not_found", status.HTTP_404_NOT_FOUND)
    raw = tenant.recruitment_branding or {}
    return {
        "hm_questions_above_resume": bool(raw.get("hm_questions_above_resume")),
        "invited_evaluator_can_play_media": bool(
            raw.get("invited_evaluator_can_play_media")
        ),
    }


async def update_branding(
    db: AsyncSession, tenant_id: uuid.UUID, data: BrandingUpdate
) -> dict:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise AppError("tenant_not_found", status.HTTP_404_NOT_FOUND)
    current = dict(tenant.recruitment_branding or {})
    payload = data.model_dump(exclude_unset=True)
    extra = payload.pop("extra", None)
    if extra is not None:
        current.update(extra)
    for k, v in payload.items():
        if v is None:
            current.pop(k, None)
        else:
            current[k] = v
    tenant.recruitment_branding = current or None
    await db.commit()
    await db.refresh(tenant)
    return await get_branding(db, tenant_id)


# ─── Retention (SCR-96) ─────────────────────────────────────────────


_DEFAULT_RETENTION = {
    "interviews_days": 365,
    "resumes_days": 365,
    "consents_days": 365,
    "reports_days": 365,
}


async def _get_or_create_retention(
    db: AsyncSession, tenant_id: uuid.UUID
) -> RecruitmentRetentionConfig:
    result = await db.execute(
        select(RecruitmentRetentionConfig).where(
            RecruitmentRetentionConfig.tenant_id == tenant_id
        )
    )
    cfg = result.scalar_one_or_none()
    if cfg is not None:
        return cfg

    # Two requests can race past the SELECT and both try to INSERT — the
    # ix_recruitment_retention_configs_tenant_unique index turns the loser
    # into an IntegrityError. Catch it, roll back, and re-SELECT so the
    # caller still gets the winning row instead of a 500.
    cfg = RecruitmentRetentionConfig(tenant_id=tenant_id, **_DEFAULT_RETENTION)
    db.add(cfg)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        result = await db.execute(
            select(RecruitmentRetentionConfig).where(
                RecruitmentRetentionConfig.tenant_id == tenant_id
            )
        )
        cfg = result.scalar_one()
        return cfg
    await db.refresh(cfg)
    return cfg


async def get_retention(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    cfg = await _get_or_create_retention(db, tenant_id)
    return {
        "interviews_days": cfg.interviews_days,
        "resumes_days": cfg.resumes_days,
        "consents_days": cfg.consents_days,
        "reports_days": cfg.reports_days,
    }


async def update_retention(
    db: AsyncSession, tenant_id: uuid.UUID, data: RetentionUpdate
) -> dict:
    cfg = await _get_or_create_retention(db, tenant_id)
    payload = data.model_dump(exclude_unset=True)
    for k, v in payload.items():
        if v is not None:
            setattr(cfg, k, v)
    await db.commit()
    await db.refresh(cfg)
    return await get_retention(db, tenant_id)


# ─── Matrix settings (HRP-265) ──────────────────────────────────────

# Historical default before the per-tenant knob landed. Keep in sync with
# the docstring on ``MatrixSettingsRead`` so the UI placeholder matches
# the actual fallback value.
_DEFAULT_DIVERGENCE_THRESHOLD: float = 1.0


def _matrix_settings_payload(raw: dict | None) -> dict:
    raw = raw or {}
    threshold = raw.get("divergence_threshold")
    try:
        threshold_f = (
            float(threshold) if threshold is not None else _DEFAULT_DIVERGENCE_THRESHOLD
        )
    except (TypeError, ValueError):
        threshold_f = _DEFAULT_DIVERGENCE_THRESHOLD
    return {"divergence_threshold": threshold_f}


async def get_matrix_settings(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise AppError("tenant_not_found", status.HTTP_404_NOT_FOUND)
    return _matrix_settings_payload(tenant.recruitment_matrix_settings)


async def get_divergence_threshold(db: AsyncSession, tenant_id: uuid.UUID) -> float:
    """Resolve the active divergence threshold for ``tenant_id``.

    Falls back to ``_DEFAULT_DIVERGENCE_THRESHOLD`` (1.0) when the tenant
    has never customised the setting. Callers that want to bypass the DB
    lookup (e.g. unit-level helpers) can keep using the constant directly.
    """
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        return _DEFAULT_DIVERGENCE_THRESHOLD
    return _matrix_settings_payload(tenant.recruitment_matrix_settings)[
        "divergence_threshold"
    ]


async def update_matrix_settings(
    db: AsyncSession, tenant_id: uuid.UUID, data: MatrixSettingsUpdate
) -> dict:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise AppError("tenant_not_found", status.HTTP_404_NOT_FOUND)
    current = _matrix_settings_payload(tenant.recruitment_matrix_settings)
    payload = data.model_dump(exclude_unset=True)
    if (
        "divergence_threshold" in payload
        and payload["divergence_threshold"] is not None
    ):
        current["divergence_threshold"] = float(payload["divergence_threshold"])
    tenant.recruitment_matrix_settings = current
    await db.commit()
    await db.refresh(tenant)
    return _matrix_settings_payload(tenant.recruitment_matrix_settings)


# ─── Roles read-only (SCR-99) ────────────────────────────────────────

# Static catalogue — recruitment-specific permissions per role. R4b ships
# this as a read-only view; full RBAC overhaul is owned by a separate
# subsystem and tracked in DEVELOPMENT_PLAN.

RECRUITMENT_ROLES: list[dict] = [
    {
        "code": "admin",
        "name": "Admin",
        "description": "Full recruitment access including settings hub",
        "permissions": [
            {"code": "recruitment.*", "description": "All recruitment actions"},
            {"code": "recruitment.settings.*", "description": "Manage settings hub"},
            {"code": "recruitment.audit.read", "description": "Read audit log"},
            {"code": "recruitment.gdpr.*", "description": "GDPR export and erasure"},
        ],
    },
    {
        "code": "recruiter",
        "name": "Recruiter",
        "description": "Owns the hiring funnel: vacancies, candidates, interviews",
        "permissions": [
            {"code": "recruitment.vacancy.*", "description": "Create/edit vacancies"},
            {"code": "recruitment.candidate.*", "description": "Manage candidates"},
            {"code": "recruitment.interview.*", "description": "Run interviews"},
            {"code": "recruitment.report.create", "description": "Generate reports"},
        ],
    },
    {
        "code": "hiring_manager",
        "name": "Hiring Manager",
        "description": "Reviews candidates and submits assessments for own vacancies",
        "permissions": [
            {"code": "recruitment.candidate.read", "description": "Read candidates"},
            {
                "code": "recruitment.assessment.create",
                "description": "Score candidates",
            },
            {"code": "recruitment.report.read", "description": "Read reports"},
        ],
    },
    {
        "code": "hr",
        "name": "HR",
        "description": "Read-only across the recruitment pipeline plus reports",
        "permissions": [
            {
                "code": "recruitment.*.read",
                "description": "Read-only recruitment access",
            },
            {"code": "recruitment.report.create", "description": "Generate reports"},
        ],
    },
    {
        "code": "hrd",
        "name": "HR Director",
        "description": "Compliance / audit oversight across the org",
        "permissions": [
            {
                "code": "recruitment.*.read",
                "description": "Read-only recruitment access",
            },
            {"code": "recruitment.audit.read", "description": "Read audit log"},
            {"code": "recruitment.gdpr.read", "description": "Read GDPR requests"},
        ],
    },
]


def list_roles() -> list[dict]:
    return RECRUITMENT_ROLES
