"""HRP-628: recruitment AI output follows the tenant's content language.

The report language is an AI-content-language question, not a vacancy
attribute: an English-language interview at a Russian-speaking tenant
must still be analysed in Russian.
"""

from __future__ import annotations

import uuid

import pytest
from app.modules.ai_settings.models import TenantAISettings
from app.modules.company.models import Tenant
from app.modules.recruitment.analysis_language import (
    resolve_analysis_language,
    resolve_analysis_language_sync,
)
from app.modules.recruitment.models import Vacancy
from sqlalchemy.ext.asyncio import AsyncSession


async def _tenant(db: AsyncSession, content_language: str | None) -> Tenant:
    suffix = uuid.uuid4().hex[:6]
    tenant = Tenant(name=f"Lang {suffix}", slug=f"lang-{suffix}", is_demo=False)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    if content_language is not None:
        db.add(TenantAISettings(tenant_id=tenant.id, content_language=content_language))
        await db.commit()
    return tenant


@pytest.mark.asyncio
async def test_tenant_content_language_wins_over_vacancy(db: AsyncSession):
    tenant = await _tenant(db, "ru")
    vacancy = Vacancy(tenant_id=tenant.id, title="Backend", language="en")
    assert await resolve_analysis_language(db, tenant.id, vacancy) == "ru"


@pytest.mark.asyncio
async def test_falls_back_to_vacancy_without_ai_settings(db: AsyncSession):
    tenant = await _tenant(db, None)
    vacancy = Vacancy(tenant_id=tenant.id, title="Backend", language="de")
    assert await resolve_analysis_language(db, tenant.id, vacancy) == "de"


@pytest.mark.asyncio
async def test_falls_back_to_en_without_either(db: AsyncSession):
    tenant = await _tenant(db, None)
    assert await resolve_analysis_language(db, tenant.id, None) == "en"
    vacancy = Vacancy(tenant_id=tenant.id, title="Backend", language="")
    assert await resolve_analysis_language(db, tenant.id, vacancy) == "en"


@pytest.mark.asyncio
async def test_opening_the_settings_page_does_not_decide_the_language(
    db: AsyncSession,
):
    """The regression this whole resolver can cause if reads write.

    ``ai_settings.get_or_default`` used to persist a defaults row, so an
    admin who merely opened Settings -> AI left ``content_language="en"``
    behind. This resolver would then read that as a deliberate English
    choice and stop honouring the vacancy language — silently switching
    an existing non-English tenant to English reports, with no way back
    through the UI.
    """
    from app.modules.ai_settings import service as ai_settings_service

    tenant = await _tenant(db, None)
    vacancy = Vacancy(tenant_id=tenant.id, title="Backend", language="de")

    # What the GET endpoint does.
    await ai_settings_service.get_or_default(db, tenant.id)
    await db.commit()

    assert await resolve_analysis_language(db, tenant.id, vacancy) == "de"


@pytest.mark.asyncio
async def test_explicit_english_beats_the_vacancy_language(db: AsyncSession):
    """The other half: "en" chosen on purpose is not a missing answer."""
    tenant = await _tenant(db, "en")
    vacancy = Vacancy(tenant_id=tenant.id, title="Backend", language="de")
    assert await resolve_analysis_language(db, tenant.id, vacancy) == "en"


@pytest.mark.asyncio
async def test_no_session_still_resolves(db: AsyncSession):
    """Question generation may be called without a session (tests, tools)."""
    vacancy = Vacancy(tenant_id=uuid.uuid4(), title="Backend", language="de")
    assert await resolve_analysis_language(None, None, vacancy) == "de"


def test_sync_twin_matches():
    """Sync twin shares the priority logic (pure-function half)."""
    from app.modules.recruitment.analysis_language import _pick

    vacancy = Vacancy(tenant_id=uuid.uuid4(), title="Backend", language="en")
    assert _pick("ru", vacancy) == "ru"
    assert _pick(None, vacancy) == "en"
    assert _pick("  ", vacancy) == "en"
    assert _pick(None, None) == "en"
    assert resolve_analysis_language_sync(None, None, vacancy) == "en"
