"""HRP-749: competence ↔ primitive links and the read-only ``applicable_to``.

Two invariants the coverage layer (W4) will lean on:

* ``competence_primitives.tenant_id`` mirrors ``competences.tenant_id`` —
  the column is denormalised so coverage never joins ``competences`` for a
  tenant filter, and only ``mapping_service`` writes the table.
* the per-competence state row (``competence_mapping_states``) carries the
  verdict and a ``source_fingerprint`` that goes stale when the competence text
  changes, so a renamed competence is re-mapped instead of carrying an old
  verdict — and an empty or rejected mapping is still a mapping.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

import pytest
from app.core.errors import AppError
from app.modules.competence import service as competence_service
from app.modules.competence.models import Competence, CompetenceGroup
from app.modules.competence.schemas import (
    CompetenceBulkCreateItem,
    CompetenceCreate,
    CompetenceRead,
    CompetenceUpdate,
)
from app.modules.primitives import catalog_data, mapping_service
from app.modules.primitives.models import CompetenceMappingState, CompetencePrimitive
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_catalog(db: AsyncSession) -> None:
    await db.execute(catalog_data.seed_insert())
    await db.commit()


async def _competence(
    db: AsyncSession,
    tenant_id: uuid.UUID | None,
    *,
    title: str = "Contract review",
    description: str | None = "Reads contracts against the playbook",
) -> Competence:
    group = CompetenceGroup(title=f"Group {uuid.uuid4().hex[:6]}", tenant_id=tenant_id)
    db.add(group)
    await db.flush()
    comp = Competence(
        title=title, description=description, group_id=group.id, tenant_id=tenant_id
    )
    db.add(comp)
    await db.commit()
    return comp


async def _links(
    db: AsyncSession, competence_id: uuid.UUID
) -> list[CompetencePrimitive]:
    rows = await db.execute(
        select(CompetencePrimitive).where(
            CompetencePrimitive.competence_id == competence_id
        )
    )
    return list(rows.scalars().all())


async def _state(
    db: AsyncSession, competence_id: uuid.UUID
) -> CompetenceMappingState | None:
    return (
        await db.execute(
            select(CompetenceMappingState).where(
                CompetenceMappingState.competence_id == competence_id
            )
        )
    ).scalar_one_or_none()


def _flatten(nodes):
    for node in nodes:
        yield from node.competences
        yield from _flatten(node.children)


def _walk_json(nodes):
    for node in nodes:
        yield node
        yield from _walk_json(node.get("children", []))


class TestApplicableTo:
    async def test_defaults_to_human(self, db, tenant):
        comp = await _competence(db, tenant.id)
        assert comp.applicable_to == "human"

    def test_write_schemas_reject_applicable_to(self):
        # MVP decision: the column is read-only for clients — no editor.
        for schema in (CompetenceCreate, CompetenceUpdate, CompetenceBulkCreateItem):
            assert "applicable_to" not in schema.model_fields, schema.__name__
        assert "applicable_to" in CompetenceRead.model_fields

    def test_read_schema_requires_the_field(self):
        # Required, not defaulted: an explicit constructor that forgets it
        # must fail loudly instead of reporting 'human' for every row.
        with pytest.raises(ValidationError):
            CompetenceRead(
                id=uuid.uuid4(),
                title="x",
                description=None,
                group_id=uuid.uuid4(),
                competence_type_id=None,
                tenant_id=None,
                is_active=True,
                is_published=False,
                created_at="2026-09-08T00:00:00Z",
            )

    async def test_tree_exposes_applicable_to(self, db, tenant):
        comp = await _competence(db, tenant.id)
        tree = await competence_service.get_competence_tree(db, tenant.id)
        read = next(c for c in _flatten(tree) if c.id == comp.id)
        assert read.applicable_to == "human"

    async def test_http_reads_carry_applicable_to(self, db, auth_client, tenant):
        # Every competence read path, not only the tree: the detail endpoint
        # builds its payload by hand (REDO checklist 11 — response contract).
        comp = await _competence(db, tenant.id)

        resp = await auth_client.get(f"/api/competences/{comp.id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["applicable_to"] == "human"

        resp = await auth_client.get("/api/competence-tree")
        assert resp.status_code == 200, resp.text
        found = [
            c
            for node in _walk_json(resp.json())
            for c in node.get("competences", [])
            if c["id"] == str(comp.id)
        ]
        assert found and found[0]["applicable_to"] == "human"

        resp = await auth_client.put(
            f"/api/competences/{comp.id}",
            json={"title": "Renamed", "applicable_to": "agent"},
        )
        assert resp.status_code == 200, resp.text
        # Unknown field in the update schema is ignored, never applied.
        assert resp.json()["applicable_to"] == "human"


class TestApplyMapping:
    async def test_links_and_state_mirror_the_competence_tenant(self, db, tenant):
        await _seed_catalog(db)
        comp = await _competence(db, tenant.id)

        await mapping_service.apply_mapping(db, comp, ["P1", "P2", "P1"])

        links = await _links(db, comp.id)
        assert len(links) == 2
        assert {link.tenant_id for link in links} == {tenant.id}
        state = await _state(db, comp.id)
        assert state is not None
        assert state.tenant_id == tenant.id
        assert state.status == "ai_suggested"
        assert state.source_fingerprint == mapping_service.source_fingerprint(
            comp.title, comp.description
        )
        assert state.reviewed_at is None and state.reviewed_by_id is None

    async def test_origin_competence_keeps_null_tenant(self, db):
        await _seed_catalog(db)
        comp = await _competence(db, None, title=f"Origin {uuid.uuid4().hex[:6]}")

        await mapping_service.apply_mapping(db, comp, ["P3"])

        assert [link.tenant_id for link in await _links(db, comp.id)] == [None]
        assert (await _state(db, comp.id)).tenant_id is None

    async def test_apply_replaces_links_and_upserts_the_state(self, db, tenant, user):
        await _seed_catalog(db)
        comp = await _competence(db, tenant.id)
        await mapping_service.apply_mapping(db, comp, ["P1", "P2"])

        await mapping_service.apply_mapping(
            db, comp, ["P5"], status="manual", reviewed_by_id=user.id
        )

        links = await _links(db, comp.id)
        assert len(links) == 1
        state = await _state(db, comp.id)
        assert state.status == "manual"
        assert state.reviewed_by_id == user.id and state.reviewed_at is not None
        rows = await db.execute(
            select(CompetenceMappingState).where(
                CompetenceMappingState.competence_id == comp.id
            )
        )
        assert len(rows.scalars().all()) == 1

    async def test_empty_codes_keep_the_state_row(self, db, tenant):
        await _seed_catalog(db)
        comp = await _competence(db, tenant.id)

        await mapping_service.apply_mapping(db, comp, [])

        assert await _links(db, comp.id) == []
        assert (await _state(db, comp.id)).status == "ai_suggested"

    async def test_a_concurrent_run_waits_for_the_state_row(
        self, db, tenant, session_factory
    ):
        """An origin competence is shared, so two tenants' runs can reach
        one competence at once. The state upsert takes that row and the link
        replacement rides in the same transaction, so the two cannot
        interleave a delete with the other's insert and leave codes no state
        row explains."""
        await _seed_catalog(db)
        comp = await _competence(db, tenant.id)
        await mapping_service.apply_mapping(db, comp, ["P1"])

        async with session_factory() as holder, session_factory() as second:
            await holder.execute(
                select(CompetenceMappingState)
                .where(CompetenceMappingState.competence_id == comp.id)
                .with_for_update()
            )
            seen_by_second = await second.get(Competence, comp.id)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(
                    mapping_service.apply_mapping(second, seen_by_second, ["P5"]), 1
                )
            await holder.rollback()
            with contextlib.suppress(Exception):
                await second.rollback()

        assert len(await _links(db, comp.id)) == 1

    async def test_unknown_code_or_status_is_rejected(self, db, tenant):
        await _seed_catalog(db)
        comp = await _competence(db, tenant.id)

        with pytest.raises(AppError) as exc:
            await mapping_service.apply_mapping(db, comp, ["P1", "P99"])
        assert exc.value.code == "primitive_not_found"
        with pytest.raises(ValueError):
            await mapping_service.apply_mapping(db, comp, ["P1"], status="whatever")
        assert await _links(db, comp.id) == []
        assert await _state(db, comp.id) is None


class TestFingerprint:
    def test_fingerprint_is_stable_and_text_sensitive(self):
        a = mapping_service.source_fingerprint("Title", "desc")
        assert a == mapping_service.source_fingerprint("Title", "desc")
        assert a != mapping_service.source_fingerprint("Title 2", "desc")
        assert a != mapping_service.source_fingerprint("Title", None)
        assert len(a) == 64

    async def test_state_goes_stale_when_the_title_changes(self, db, tenant):
        await _seed_catalog(db)
        comp = await _competence(db, tenant.id)
        await mapping_service.apply_mapping(db, comp, ["P1"])
        state = await _state(db, comp.id)
        assert mapping_service.is_stale(state, comp) is False

        comp.title = "Contract negotiation"
        await db.commit()

        assert mapping_service.is_stale(state, comp) is True
