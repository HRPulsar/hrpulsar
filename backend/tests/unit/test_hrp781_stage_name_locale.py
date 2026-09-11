"""HRP-781: default funnel stages are seeded in the tenant's language.

Every consumer reads ``VacancyStage.name`` straight out of the DB —
candidate lists, funnel analytics, XLSX reports, emails — so the name has
to be written in the tenant's locale at seed time; nothing downstream
could localize a stored English string afterwards.

Three invariants, none of which the type system can hold:

1. ``DEFAULT_RECRUITMENT_STAGES`` and the en catalog agree, so the
   English baseline the migration matches on stays one value.
2. The seed honours ``Tenant.default_locale``.
3. The core migration's inlined table (self-contained by convention)
   agrees with both the tuple and the shipped catalogs.
"""

from __future__ import annotations

import pytest
from app.config import settings
from app.core.i18n import translate
from app.modules.company.models import Tenant
from app.modules.recruitment.models import VacancyStage
from app.modules.recruitment.vacancy_service import (
    DEFAULT_RECRUITMENT_STAGES,
    seed_default_recruitment_stages,
)
from migrations.versions.hrp781stagei18n01_localize_default_stage_names import (
    STAGE_NAMES,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def test_en_catalog_matches_the_seed_tuple() -> None:
    for code, en_name, *_ in DEFAULT_RECRUITMENT_STAGES:
        assert translate(f"recruitment.stage.{code}", "en") == en_name


def test_every_stage_has_a_de_name() -> None:
    """de is the second shipped locale — a missing key would silently
    fall back to English and reopen this ticket for German installs."""
    for code, en_name, *_ in DEFAULT_RECRUITMENT_STAGES:
        assert translate(f"recruitment.stage.{code}", "de") != en_name


def test_migration_table_matches_the_catalogs() -> None:
    assert [row[0] for row in STAGE_NAMES] == [s[0] for s in DEFAULT_RECRUITMENT_STAGES]
    for code, en_name, by_locale in STAGE_NAMES:
        assert translate(f"recruitment.stage.{code}", "en") == en_name
        for locale, localized in by_locale.items():
            assert translate(f"recruitment.stage.{code}", locale) == localized


@pytest.mark.asyncio
async def test_seed_writes_names_in_the_tenant_locale(
    db: AsyncSession, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "available_locales", "de,en")
    tenant.default_locale = "de"
    await db.execute(
        VacancyStage.__table__.delete().where(
            VacancyStage.tenant_id == tenant.id,
            VacancyStage.vacancy_id.is_(None),
        )
    )
    await db.commit()

    assert await seed_default_recruitment_stages(db, tenant.id) == 9
    await db.commit()

    rows = (
        (
            await db.execute(
                select(VacancyStage).where(
                    VacancyStage.tenant_id == tenant.id,
                    VacancyStage.vacancy_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_code = {row.code: row.name for row in rows}
    for code, en_name, *_ in DEFAULT_RECRUITMENT_STAGES:
        assert by_code[code] == translate(f"recruitment.stage.{code}", "de")
        assert by_code[code] != en_name


@pytest.mark.asyncio
async def test_seed_falls_back_to_english_without_a_tenant_locale(
    db: AsyncSession, tenant: Tenant
) -> None:
    """The deployment default decides, and en is the stock one — a
    single-language install must not have to set anything per tenant."""
    tenant.default_locale = None
    await db.execute(
        VacancyStage.__table__.delete().where(
            VacancyStage.tenant_id == tenant.id,
            VacancyStage.vacancy_id.is_(None),
        )
    )
    await db.commit()

    await seed_default_recruitment_stages(db, tenant.id)
    await db.commit()

    rows = (
        (
            await db.execute(
                select(VacancyStage).where(
                    VacancyStage.tenant_id == tenant.id,
                    VacancyStage.vacancy_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_code = {row.code: row.name for row in rows}
    assert by_code == {
        code: en_name for code, en_name, *_ in DEFAULT_RECRUITMENT_STAGES
    }
