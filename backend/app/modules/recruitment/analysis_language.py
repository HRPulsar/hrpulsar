"""Output language for recruitment AI content (HRP-628).

The interface locale, the AI content language and the region are three
separate axes. What an analysis is *written in* is the tenant's AI
content language: ``Vacancy.language`` only records the language the
vacancy itself was filled in, so an English-language interview at a
Russian-speaking tenant used to come back with an English report.

Priority: ``TenantAISettings.content_language`` -> ``Vacancy.language``
-> ``"en"``.

"No setting" has to mean "the tenant never chose one", so this reads the
column directly and treats a missing row as undecided.
``ai_settings.get_or_default`` is deliberately not used: it returns a
defaults row, and until HRP-628 it also *persisted* that row on a plain
read, which stamped ``content_language="en"`` on any tenant whose admin
merely opened Settings -> AI. That write is gone (the row is now saved
only when the tenant saves something), so an absent row is once again
evidence of an absent choice.

An explicit ``"en"`` is a real choice and wins over the vacancy
language — the fallback is for tenants who never answered the question,
not for tenants who answered "English".
"""

import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.modules.ai_settings.models import TenantAISettings

__all__ = ["resolve_analysis_language", "resolve_analysis_language_sync"]

DEFAULT_ANALYSIS_LANGUAGE = "en"


def _pick(content_language: str | None, vacancy: Any | None) -> str:
    vacancy_language = getattr(vacancy, "language", None) if vacancy else None
    return (
        (content_language or "").strip()
        or (vacancy_language or "").strip()
        or DEFAULT_ANALYSIS_LANGUAGE
    )


def _stmt(tenant_id: uuid.UUID | str) -> Select[tuple[str]]:
    return select(TenantAISettings.content_language).where(
        TenantAISettings.tenant_id
        == (
            tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
        )
    )


async def resolve_analysis_language(
    db: AsyncSession | None,
    tenant_id: uuid.UUID | str | None,
    vacancy: Any | None,
) -> str:
    """Language the generated analysis/questions must be written in."""
    if db is None or tenant_id is None:
        return _pick(None, vacancy)
    return _pick((await db.execute(_stmt(tenant_id))).scalar_one_or_none(), vacancy)


def resolve_analysis_language_sync(
    db: Session | None,
    tenant_id: uuid.UUID | str | None,
    vacancy: Any | None,
) -> str:
    """Sync twin for the Celery tasks."""
    if db is None or tenant_id is None:
        return _pick(None, vacancy)
    return _pick(db.execute(_stmt(tenant_id)).scalar_one_or_none(), vacancy)
