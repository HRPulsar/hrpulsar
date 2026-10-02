"""HRP-954: embeddings are tenant-scoped - a user of tenant A gets none of
tenant B's rows from the search, and A's upsert of the same entity key
leaves B's row alone."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from app.modules.ai import service as ai_svc
from app.modules.ai.models import Embedding
from app.modules.company.models import Tenant
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations/versions/v2work12_embeddings_tenant.py"
)

VEC_A = [1.0] + [0.0] * 1535
VEC_B = [0.0, 1.0] + [0.0] * 1534


async def _other_tenant(db: AsyncSession) -> Tenant:
    t = Tenant(
        name=f"Other {uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:8]}"
    )
    db.add(t)
    await db.commit()
    return t


async def _row(db: AsyncSession, tenant_id, entity_id, text: str, vec) -> None:
    db.add(
        Embedding(
            tenant_id=tenant_id,
            entity_type="competence",
            entity_id=entity_id,
            text_content=text,
            embedding=vec,
        )
    )
    await db.commit()


def _embed(vec):
    return patch(
        "app.modules.ai.llm_client.get_embedding",
        new_callable=AsyncMock,
        return_value=vec,
    )


async def test_search_returns_only_the_callers_tenant(db, tenant):
    other = await _other_tenant(db)
    entity_id = uuid.uuid4()
    await _row(db, tenant.id, entity_id, "ours", VEC_A)
    # Same entity key and an identical vector: without the tenant filter
    # this row ranks exactly as high as ours.
    await _row(db, other.id, entity_id, "theirs", VEC_A)
    await _row(db, other.id, uuid.uuid4(), "theirs too", VEC_B)

    with _embed(VEC_A):
        rows = await ai_svc.semantic_search(db, tenant.id, None, "q", limit=10)
    assert [r["text_content"] for r in rows] == ["ours"]

    with _embed(VEC_A):
        rows = await ai_svc.semantic_search(db, other.id, None, "q", "competence")
    assert {r["text_content"] for r in rows} == {"theirs", "theirs too"}


async def test_upsert_never_touches_another_tenants_row(db, tenant):
    other = await _other_tenant(db)
    entity_id = uuid.uuid4()
    await _row(db, other.id, entity_id, "theirs", VEC_B)

    with _embed(VEC_A):
        await ai_svc.create_embedding(db, tenant.id, "competence", entity_id, "ours")
    with _embed(VEC_A):
        await ai_svc.create_embedding(
            db, tenant.id, "competence", entity_id, "ours, edited"
        )

    rows = (
        (await db.execute(select(Embedding).where(Embedding.entity_id == entity_id)))
        .scalars()
        .all()
    )
    assert {(r.tenant_id, r.text_content) for r in rows} == {
        (tenant.id, "ours, edited"),
        (other.id, "theirs"),
    }


async def test_migration_dedupe_keeps_the_latest_duplicate(db):
    spec = importlib.util.spec_from_file_location("v2work12", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # A temp table with the real table's name shadows it for this session
    # only (pg_temp leads search_path), so the migration's exact SQL runs
    # against duplicates the live unique constraint would refuse.
    await db.execute(
        text(
            "CREATE TEMP TABLE embeddings (id uuid, tenant_id uuid, "
            "entity_type text, entity_id uuid, updated_at timestamptz)"
        )
    )
    t1, t2, e = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    older, latest, elsewhere = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO embeddings VALUES "
            "(:older, :t1, 'competence', :e, '2026-09-20T10:00:00Z'), "
            "(:latest, :t1, 'competence', :e, '2026-09-20T10:00:05Z'), "
            # Same entity key in another tenant is not a duplicate.
            "(:elsewhere, :t2, 'competence', :e, '2026-09-20T09:00:00Z')"
        ),
        {
            "older": older,
            "latest": latest,
            "elsewhere": elsewhere,
            "t1": t1,
            "t2": t2,
            "e": e,
        },
    )
    await db.execute(text(mod.DEDUPE_SQL))
    ids = set((await db.execute(text("SELECT id FROM embeddings"))).scalars())
    assert ids == {latest, elsewhere}
    await db.rollback()
