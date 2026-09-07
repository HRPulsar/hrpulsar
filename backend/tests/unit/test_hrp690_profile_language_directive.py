"""HRP-690: vacancy profile / individual questions honor the content language.

The tenant's AI content language used to reach the prompt only as a bare
ISO code ("Respond in ru language") buried under kilobytes of English JSON
exemplars — the model answered in English anyway. The fix injects the
named-language directive (HRP-541 pattern) into the system prompt and the
tail of the user prompt.
"""

import uuid
from datetime import datetime, timezone

import pytest
from app.modules.ai_settings.models import TenantAISettings
from app.modules.ai_settings.service import language_directive
from app.modules.company.models import Tenant
from app.modules.recruitment import ai_service, vacancy_profile_service
from app.modules.recruitment.models import (
    Vacancy,
    VacancyProfile,
    VacancyProfileSession,
)
from app.modules.recruitment.schemas import VacancyProfileUpdate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def test_language_directive_names_the_language() -> None:
    assert "Generate ALL content in Russian" in language_directive("ru")
    assert "Generate ALL content in German" in language_directive("de")
    # Unknown / missing codes fall back to English.
    assert "Generate ALL content in English" in language_directive("xx")
    assert "Generate ALL content in English" in language_directive(None)


async def test_generate_vacancy_profile_carries_directive(monkeypatch) -> None:
    captured: dict = {}

    async def fake_generate_json(prompt, **kwargs):
        captured["prompt"] = prompt
        captured["system"] = kwargs["system"]
        return {"competences": []}

    monkeypatch.setattr(ai_service, "generate_json", fake_generate_json)

    await ai_service.generate_vacancy_profile(
        {"title": "Dev", "vacancy_id": "v1", "language": "ru"}
    )

    assert "Generate ALL content in Russian" in captured["system"]
    assert "Generate ALL content in Russian" in captured["prompt"]
    assert "Respond in ru language" not in captured["prompt"]


async def test_generate_individual_questions_carries_directive(monkeypatch) -> None:
    captured: dict = {}

    async def fake_generate_json(prompt, **kwargs):
        captured["prompt"] = prompt
        captured["system"] = kwargs["system"]
        return []

    monkeypatch.setattr(ai_service, "generate_json", fake_generate_json)

    await ai_service.generate_individual_questions(
        {"first_name": "A"}, {"competences": []}, "Dev", language="ru"
    )

    assert "Generate ALL content in Russian" in captured["system"]
    assert "Generate ALL content in Russian" in captured["prompt"]
    assert "Respond in ru language" not in captured["prompt"]


# ---------------------------------------------------------------------------
# HRP-702: the column has to agree with the language the content is in.
#
# HRP-690 routed the generated *content* through resolve_analysis_language,
# but ``VacancyProfile.language`` was still stamped from ``vacancy.language
# or "en"`` — so a profile generated in Russian was recorded as English, and
# every consumer of the column (regeneration, export, report heading) would
# act on the wrong value.
# ---------------------------------------------------------------------------


async def _tenant(db: AsyncSession, content_language: str | None) -> Tenant:
    suffix = uuid.uuid4().hex[:6]
    tenant = Tenant(name=f"Prof {suffix}", slug=f"prof-{suffix}", is_demo=False)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    if content_language is not None:
        db.add(TenantAISettings(tenant_id=tenant.id, content_language=content_language))
        await db.commit()
    return tenant


async def _vacancy(db: AsyncSession, tenant: Tenant, language: str | None) -> Vacancy:
    vacancy = Vacancy(
        tenant_id=tenant.id, title=f"Backend {uuid.uuid4().hex[:4]}", language=language
    )
    db.add(vacancy)
    await db.commit()
    await db.refresh(vacancy)
    return vacancy


async def _apply(db: AsyncSession, tenant: Tenant, vacancy: Vacancy) -> dict:
    """Run the Review-for-save apply path once."""
    session_row = VacancyProfileSession(
        tenant_id=tenant.id,
        vacancy_id=vacancy.id,
        status="ready",
        started_at=datetime.now(timezone.utc),
    )
    db.add(session_row)
    await db.commit()
    await db.refresh(session_row)
    return await vacancy_profile_service.apply_profile_session(
        db,
        tenant.id,
        vacancy.id,
        session_row.id,
        VacancyProfileUpdate(profile_data={"competences": []}),
    )


@pytest.mark.asyncio
async def test_apply_stamps_the_content_language_not_the_vacancy_language(
    db: AsyncSession,
):
    """The reported case: profile written in Russian, column said "en"."""
    tenant = await _tenant(db, "ru")
    vacancy = await _vacancy(db, tenant, "en")

    applied = await _apply(db, tenant, vacancy)

    assert applied["language"] == "ru"
    row = (
        await db.execute(
            select(VacancyProfile).where(VacancyProfile.vacancy_id == vacancy.id)
        )
    ).scalar_one()
    assert row.language == "ru"


@pytest.mark.asyncio
async def test_apply_restamps_an_existing_profile(db: AsyncSession):
    """Re-apply is a regeneration: the row is written in the language of
    the day, so the column must move with it instead of keeping whatever
    the first apply left behind."""
    tenant = await _tenant(db, "ru")
    vacancy = await _vacancy(db, tenant, "en")
    first = await _apply(db, tenant, vacancy)
    assert first["language"] == "ru"

    settings_row = (
        await db.execute(
            select(TenantAISettings).where(TenantAISettings.tenant_id == tenant.id)
        )
    ).scalar_one()
    settings_row.content_language = "de"
    await db.commit()

    second = await _apply(db, tenant, vacancy)
    assert second["version"] == first["version"] + 1
    assert second["language"] == "de"


@pytest.mark.asyncio
async def test_apply_falls_back_to_the_vacancy_then_to_english(db: AsyncSession):
    """Same priority chain as the generated content itself."""
    no_settings = await _tenant(db, None)
    vacancy = await _vacancy(db, no_settings, "de")
    assert (await _apply(db, no_settings, vacancy))["language"] == "de"

    bare = await _tenant(db, None)
    bare_vacancy = await _vacancy(db, bare, None)
    assert (await _apply(db, bare, bare_vacancy))["language"] == "en"


@pytest.mark.asyncio
async def test_celery_task_stamps_the_same_language(db: AsyncSession, monkeypatch):
    """The background twin of the apply path, through the sync resolver.

    Run for real against the test DB (the task opens its own psycopg2
    session) with only the LLM call stubbed, so both branches of the
    upsert — create and re-generate — are the ones that ship. Driven from
    a worker thread because the task calls ``asyncio.run`` itself, exactly
    as it does under a Celery worker.
    """
    import asyncio

    from app.config import settings as app_settings
    from app.modules.ai import providers
    from app.modules.recruitment import ai_service
    from app.modules.recruitment.tasks.generation import generate_profile_task

    from tests.conftest import TEST_DB_URL

    tenant = await _tenant(db, "ru")
    vacancy = await _vacancy(db, tenant, "en")

    captured: dict = {}

    async def fake_generate_vacancy_profile(vacancy_data, credentials=None):
        captured["language"] = vacancy_data["language"]
        return {"competences": []}

    monkeypatch.setattr(app_settings, "database_url", TEST_DB_URL)
    monkeypatch.setattr(providers, "resolve_generation_target_sync", lambda *a: None)
    monkeypatch.setattr(
        ai_service, "generate_vacancy_profile", fake_generate_vacancy_profile
    )

    async def _stored_language() -> tuple[str, int]:
        row = (
            await db.execute(
                select(VacancyProfile)
                .where(VacancyProfile.vacancy_id == vacancy.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        return row.language, row.version

    def _run() -> dict:
        return generate_profile_task(str(vacancy.id), str(tenant.id))

    assert (await asyncio.to_thread(_run))["status"] == "completed"
    # The prompt language and the recorded language are one decision.
    assert captured["language"] == "ru"
    assert await _stored_language() == ("ru", 1)

    # Second run takes the ``existing`` branch, which used to stamp nothing.
    settings_row = (
        await db.execute(
            select(TenantAISettings).where(TenantAISettings.tenant_id == tenant.id)
        )
    ).scalar_one()
    settings_row.content_language = "de"
    await db.commit()

    await asyncio.to_thread(_run)
    assert captured["language"] == "de"
    assert await _stored_language() == ("de", 2)
