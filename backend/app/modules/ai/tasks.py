"""Celery tasks for AI generation endpoints.

Moved off the request handler so a 30–60 s LLM call no longer pins a DB
connection in the FastAPI worker pool.

Each task opens its own short-lived async engine (one per task run, disposed
after) so the Celery worker is fully decoupled from the FastAPI engine that
runs in a different process / event loop.

Billing: precheck happens in the API handler before enqueueing — failure
returns 402 to the caller and the task never starts. consume_credits runs
inside the task after the work succeeds. On task failure (LLM error, DB
error) we don't deduct.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core import billing_hooks
from app.core.celery_app import celery
from app.database import make_async_engine

logger = logging.getLogger(__name__)


def _run_with_async_session(
    coro_factory: Callable[[async_sessionmaker[AsyncSession]], Awaitable[Any]],
) -> Any:
    """Wrap a coroutine with a freshly-created async engine + session factory.

    A new engine per task run keeps the connection pool tied to the event
    loop that asyncio.run() creates. Sharing app.database.engine across
    Celery's prefork workers risks asyncpg "loop is closed" errors when a
    second task lands on the same worker — short-lived engines avoid that.
    """

    async def _inner() -> Any:
        engine = make_async_engine(
            settings.database_url,
            pool_size=2,
            max_overflow=2,
            pool_recycle=300,
            pool_pre_ping=True,
        )
        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            return await coro_factory(session_factory)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


async def _generate_json_with_retries(
    prompt: str,
    *,
    system: str,
    tenant_settings: Any,
    max_retries: int,
    credentials: Any = None,
    model: str | None = None,
) -> Any:
    """Call generate_json, retrying on JSON parse errors up to max_retries times.

    LLM JSON output is occasionally malformed (truncated braces, stray
    commentary). Tenant settings expose `max_retries` so admins can raise
    or lower the budget. Network/provider errors are not retried here —
    Celery's `@task(max_retries=...)` handles those at task level.
    """
    from app.modules.ai import llm_client

    attempts = max(1, max_retries)
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await llm_client.generate_json(
                prompt,
                system=system,
                tenant_settings=tenant_settings,
                credentials=credentials,
                model=model,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            logger.warning(
                "LLM JSON parse failed (attempt %d/%d): %s",
                attempt + 1,
                attempts,
                exc,
            )
    assert last_exc is not None
    raise last_exc


async def _load_settings(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID | None,
) -> Any:
    """Load TenantAISettings (lazy-creating defaults) or return None if no tenant."""
    if tenant_id is None:
        return None
    from app.modules.ai_settings import service as ai_settings_service

    async with session_factory() as db:
        return await ai_settings_service.get_or_default(db, tenant_id)


async def _load_dispatch(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID | None,
    tenant_settings: Any,
) -> tuple[Any, str | None]:
    """``(credentials, model)`` for one generation call, or ``(None, None)``.

    Resolves the tenant's BYOK/local generation target (HRP-465) *and* the
    effective model in one short-lived session from the task's own factory
    — the worker event loop owns it, so no cross-loop connection reuse.

    HRP-500 (review #5): the model must be resolved through the catalog
    here. Celery paths hand ``llm_client`` a ``credentials`` object and no
    session, so the kill-switch inside ``generate()`` never ran and the
    worker dispatched a model the platform admin had disabled — while
    billing (``ee.credits``) priced the substitute it never used. Passing
    the resolved id explicitly makes dispatch and billing agree, and the
    LLM call itself still runs with no session open.
    """
    if tenant_id is None:
        return None, None
    from app.modules.ai import providers
    from app.modules.ai_settings.service import get_effective_model_async

    async with session_factory() as db:
        model = (
            await get_effective_model_async(db, tenant_settings)
            if tenant_settings is not None
            else None
        )
        credentials = await providers.resolve_generation_target(db, tenant_id, model)
    return credentials, model


def _retry_budget(tenant_settings: Any, fallback: int) -> int:
    if tenant_settings is None:
        return fallback
    from app.modules.ai_settings.service import get_effective_max_retries

    return get_effective_max_retries(tenant_settings)


# ---------------------------------------------------------------------------
# generate_positions
# ---------------------------------------------------------------------------


@celery.task(bind=True, max_retries=1, default_retry_delay=10)
def generate_positions_task(
    self,
    tenant_id_str: str,
    user_id_str: str | None,
    cost: float | None = None,
) -> list[dict]:
    """Run generate_positions in the background. Returns the persisted drafts."""
    tenant_id = uuid.UUID(tenant_id_str)
    user_id = uuid.UUID(user_id_str) if user_id_str else None

    async def _run(session_factory: async_sessionmaker[AsyncSession]) -> list[dict]:
        from app.modules.ai import prompts, service
        from app.modules.position.service import _position_to_read

        tenant_settings = await _load_settings(session_factory, tenant_id)
        credentials, model = await _load_dispatch(
            session_factory, tenant_id, tenant_settings
        )

        async with session_factory() as db:
            ctx = await service._collect_context_for_positions(db, tenant_id)
            await db.commit()  # release the advisory lock before the LLM call

        result = await _generate_json_with_retries(
            ctx["prompt"],
            system=prompts.build_system_position(tenant_settings),
            tenant_settings=tenant_settings,
            credentials=credentials,
            model=model,
            max_retries=_retry_budget(tenant_settings, fallback=2),
        )
        items = result if isinstance(result, list) else [result]
        items = items[: ctx["count"]]

        async with session_factory() as db:
            # Re-take the lock and refresh existing_drafts now that we've
            # released the previous transaction. _persist_positions only
            # uses lookup maps + adds/updates rows; the advisory lock is
            # taken inside _collect to serialize concurrent runs.
            ctx2 = await service._collect_context_for_positions(db, tenant_id)
            created = await service._persist_positions(
                db,
                tenant_id,
                items,
                existing_titles=ctx2["existing_titles"],
                existing_drafts=ctx2["existing_drafts"],
                spec_map=ctx2["spec_map"],
                grade_map=ctx2["grade_map"],
                div_map=ctx2["div_map"],
            )
            await billing_hooks.consume_action(
                db,
                tenant_id,
                user_id,
                "ai.generate_positions",
                amount_override=cost,
            )
            await db.commit()
            for p in created:
                await db.refresh(p)
            return [_position_to_read(p, 0) for p in created]

    try:
        return _run_with_async_session(_run)
    except Exception as exc:
        logger.exception("generate_positions_task failed")
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# suggest_pdp
# ---------------------------------------------------------------------------


@celery.task(bind=True, max_retries=1, default_retry_delay=10)
def suggest_pdp_task(
    self,
    tenant_id_str: str,
    user_id_str: str | None,
    assessment_id_str: str,
    cost: float | None = None,
) -> list[dict]:
    """Run suggest_pdp in the background."""
    tenant_id = uuid.UUID(tenant_id_str)
    user_id = uuid.UUID(user_id_str) if user_id_str else None
    assessment_id = uuid.UUID(assessment_id_str)

    async def _run(session_factory: async_sessionmaker[AsyncSession]) -> list[dict]:
        from app.modules.ai import prompts, service

        tenant_settings = await _load_settings(session_factory, tenant_id)
        credentials, model = await _load_dispatch(
            session_factory, tenant_id, tenant_settings
        )

        async with session_factory() as db:
            prompt = await service._collect_context_for_pdp(db, assessment_id)

        result = await _generate_json_with_retries(
            prompt,
            system=prompts.build_system_competence(tenant_settings),
            tenant_settings=tenant_settings,
            credentials=credentials,
            model=model,
            max_retries=_retry_budget(tenant_settings, fallback=2),
        )
        items = result if isinstance(result, list) else [result]

        async with session_factory() as db:
            await billing_hooks.consume_action(
                db,
                tenant_id,
                user_id,
                "ai.generate_pdp_goals",
                amount_override=cost,
            )
            await db.commit()
        return items

    try:
        return _run_with_async_session(_run)
    except Exception as exc:
        logger.exception("suggest_pdp_task failed")
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# generate_competences
# ---------------------------------------------------------------------------


@celery.task(bind=True, max_retries=2, default_retry_delay=10)
def generate_competences_task(
    self,
    tenant_id_str: str | None,
    user_id_str: str | None,
    specialization: str,
    company_description: str = "",
    activity_fields: str = "",
    cost: float | None = None,
) -> list[dict]:
    """Run generate_competences in the background.

    Note the leading tenant_id_str / user_id_str args — the original task
    in app.core.tasks took only the prompt parameters. Older callers must
    migrate or use the legacy task in app.core.tasks (kept for backward
    compatibility with any in-flight queued tasks).
    """
    tenant_id = uuid.UUID(tenant_id_str) if tenant_id_str else None
    user_id = uuid.UUID(user_id_str) if user_id_str else None

    async def _run(session_factory: async_sessionmaker[AsyncSession]) -> list[dict]:
        from app.modules.ai import prompts

        tenant_settings = await _load_settings(session_factory, tenant_id)
        credentials, model = await _load_dispatch(
            session_factory, tenant_id, tenant_settings
        )

        prompt = prompts.GENERATE_COMPETENCES.format(
            specialization=specialization,
            company_description=company_description or "Not specified",
            activity_fields=activity_fields or "Not specified",
        )
        result = await _generate_json_with_retries(
            prompt,
            system=prompts.build_system_competence(tenant_settings),
            tenant_settings=tenant_settings,
            credentials=credentials,
            model=model,
            max_retries=_retry_budget(tenant_settings, fallback=2),
        )
        items = result if isinstance(result, list) else [result]

        if tenant_id is not None:
            async with session_factory() as db:
                await billing_hooks.consume_action(
                    db,
                    tenant_id,
                    user_id,
                    "ai.generate_competences",
                    amount_override=cost,
                )
                await db.commit()

        return items

    try:
        return _run_with_async_session(_run)
    except Exception as exc:
        logger.exception("generate_competences_task failed")
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# generate_indicators
# ---------------------------------------------------------------------------


@celery.task(bind=True, max_retries=2, default_retry_delay=10)
def generate_indicators_task(
    self,
    tenant_id_str: str | None,
    user_id_str: str | None,
    competence_title: str,
    context: str = "",
    cost: float | None = None,
) -> list[dict]:
    """Run generate_indicators in the background."""
    tenant_id = uuid.UUID(tenant_id_str) if tenant_id_str else None
    user_id = uuid.UUID(user_id_str) if user_id_str else None

    async def _run(session_factory: async_sessionmaker[AsyncSession]) -> list[dict]:
        from app.modules.ai import prompts

        tenant_settings = await _load_settings(session_factory, tenant_id)
        credentials, model = await _load_dispatch(
            session_factory, tenant_id, tenant_settings
        )

        prompt = prompts.GENERATE_INDICATORS.format(
            competence_title=competence_title,
            context=context or "General professional context",
        )
        result = await _generate_json_with_retries(
            prompt,
            system=prompts.build_system_competence(tenant_settings),
            tenant_settings=tenant_settings,
            credentials=credentials,
            model=model,
            max_retries=_retry_budget(tenant_settings, fallback=2),
        )
        items = result if isinstance(result, list) else [result]

        if tenant_id is not None:
            async with session_factory() as db:
                await billing_hooks.consume_action(
                    db,
                    tenant_id,
                    user_id,
                    "ai.generate_indicators",
                    amount_override=cost,
                )
                await db.commit()

        return items

    try:
        return _run_with_async_session(_run)
    except Exception as exc:
        logger.exception("generate_indicators_task failed")
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# I3d: Batch embedding generation as async Celery task
# ---------------------------------------------------------------------------


@celery.task(bind=True, max_retries=1, default_retry_delay=30)
def batch_embed_task(self, items: list[dict]) -> dict:
    """Generate embeddings for multiple entities in background.

    Each item: {"entity_type": str, "entity_id": str, "text_content": str}
    """
    import asyncio
    import uuid

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.database import make_sync_engine
    from app.modules.ai import llm_client
    from app.modules.ai.models import Embedding

    engine = make_sync_engine(settings.database_url)
    processed = 0
    errors = []

    try:
        with Session(engine) as db:
            for item in items:
                try:
                    entity_type = item["entity_type"]
                    entity_id = uuid.UUID(item["entity_id"])
                    text_content = item["text_content"]

                    vector = asyncio.run(llm_client.get_embedding(text_content))

                    existing = db.execute(
                        select(Embedding).where(
                            Embedding.entity_type == entity_type,
                            Embedding.entity_id == entity_id,
                        )
                    ).scalar_one_or_none()

                    if existing:
                        existing.text_content = text_content
                        existing.embedding = vector
                    else:
                        db.add(
                            Embedding(
                                entity_type=entity_type,
                                entity_id=entity_id,
                                text_content=text_content,
                                embedding=vector,
                            )
                        )
                    db.commit()
                    processed += 1
                except Exception as e:  # noqa: BLE001 - per-item isolation
                    errors.append(
                        {
                            "entity_id": item.get("entity_id"),
                            "error": str(e),
                        }
                    )
                    logger.warning(
                        "Embedding failed for %s: %s", item.get("entity_id"), e
                    )

        logger.info(
            "Batch embed completed: %d processed, %d errors", processed, len(errors)
        )
        return {"processed": processed, "errors": errors, "total": len(items)}

    except Exception as exc:
        logger.exception("batch_embed_task failed")
        raise self.retry(exc=exc)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Model catalog refresh (HRP-466)
# ---------------------------------------------------------------------------


@celery.task(bind=True, max_retries=0)
def refresh_model_catalog_task(self) -> dict[str, Any]:
    """Daily discovery sweep over every provider with a configured key.

    Core beat schedule entry ``refresh-model-catalog`` (24h) — community
    installs with keys get fresh models without a redeploy too. Each
    provider runs inside its own try/except: an API outage skips that
    provider and never touches existing catalog rows.
    """

    async def _run(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
        from app.modules.ai import model_catalog_service

        async with session_factory() as db:
            summary = await model_catalog_service.run_discovery_sweep(db)
        logger.info("model catalog refresh: %s", summary)
        return summary

    return _run_with_async_session(_run)
